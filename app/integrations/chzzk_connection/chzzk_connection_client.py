"""jamkubot 채팅 릴레이(relay.jamkubot.com) 연결 클라이언트

relay.jamkubot.com 에 Socket.IO 로 접속해 마스터 토큰으로 전체 채널('all')을 구독하고,
들어오는 message 중 연동된 스트리머 채널의 것만 chzzk_event_handler 로 넘긴다.
CHZZK_RELAY_TOKEN(잼쿠봇 마스터 토큰)이 설정돼 있어야 동작한다.

채널별로 구독하지 않는 이유: V3 릴레이는 소켓 하나에 채널 8개까지만 받고, 앞 구독이
끝나기 전에 온 구독은 'Too many requests.' 로 거절하며, 실패가 5번 쌓이면 연결을 끊는다.
연동 채널을 한꺼번에 구독하면 연결·끊김을 끝없이 반복한다(2026-10-07).

주의: relay 서버는 구버전 Socket.IO 프로토콜이므로 python-socketio==4.6.1 이 필요하다.
"""
import asyncio
import logging
import socketio

from app.utils.config import settings
from app.utils.log import logger
from app.integrations.chzzk_connection.chzzk_event_handler import chzzk_event_handler
from app.database.chzzk_repository import ChzzkChannelRepository

# engineio/socketio 의 저수준 노이즈 억제
# (종료 시 나는 'packet queue is empty, aborting' 등 — 진짜 오류는 ERROR 로 유지)
class _EngineIONoiseFilter(logging.Filter):
    """emit 시점에서 무해한 저수준 메시지를 걸러낸다(레벨 변경에 영향받지 않음)."""
    _DROP = ("packet queue is empty",)

    def filter(self, record):
        msg = record.getMessage()
        return not any(s in msg for s in self._DROP)


for _noisy in ("engineio", "engineio.client", "socketio", "socketio.client"):
    _lg = logging.getLogger(_noisy)
    _lg.setLevel(logging.WARNING)
    _lg.addFilter(_EngineIONoiseFilter())

# 연동 채널 목록 갱신 주기(초) — 새로 연동/해제한 스트리머 반영 + 구독 실패 재시도
_REFRESH_INTERVAL = 30
_ALL = "all"


class ChzzkConnectionClient:
    def __init__(self):
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # 무제한 재연결
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False,
        )
        self._running = False
        self._channels: frozenset[str] = frozenset()  # 처리할 연동 채널 uid
        self._subscribed = False  # 릴레이가 'all' 구독을 승인했는지
        self._channel_repo = ChzzkChannelRepository()
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        @self.sio.event
        async def connect():
            logger.info("[ChzzkRelay] 릴레이에 연결됨")
            self._subscribed = False
            await self._subscribe()

        @self.sio.event
        async def disconnect():
            logger.warning("[ChzzkRelay] 릴레이 연결 끊김")
            self._subscribed = False

        @self.sio.event
        async def connect_error(data):
            logger.error(f"[ChzzkRelay] 연결 실패: {data}")

        @self.sio.on("message")
        async def on_message(data):
            # 'all' 구독이라 모든 채널의 이벤트가 온다 — 연동 채널 것만 처리
            if isinstance(data, dict) and data.get("streamerUid") in self._channels:
                await chzzk_event_handler.handle_message(data)

        @self.sio.on("subscribed")
        async def on_subscribed(data):
            if not isinstance(data, dict):
                return
            if data.get("success"):
                if data.get("streamerUid") == _ALL:
                    self._subscribed = True
                    logger.info(f"[ChzzkRelay] 전체 채널 구독 완료 (연동 채널 {len(self._channels)}개 처리)")
            else:
                # 다음 갱신 주기에 다시 시도한다
                logger.warning(f"[ChzzkRelay] 구독 실패: {data.get('message')}")

        @self.sio.on("error")
        async def on_error(data):
            logger.error(f"[ChzzkRelay] 에러: {data}")

        @self.sio.on("systemStatus")
        async def on_system_status(data):
            pass

        @self.sio.on("streamerStatus")
        async def on_streamer_status(data):
            pass

    async def _refresh_channels(self):
        """연동된 채널 목록을 다시 읽는다 (실패하면 이전 목록 유지)"""
        try:
            channels = frozenset(await self._channel_repo.get_all_channel_ids())
        except Exception as e:
            logger.error(f"[ChzzkRelay] 채널 목록 조회 실패: {e}")
            return
        if channels != self._channels:
            logger.info(f"[ChzzkRelay] 연동 채널 {len(self._channels)}개 -> {len(channels)}개")
            self._channels = channels

    async def _subscribe(self):
        """마스터 토큰으로 전체 채널 구독 (결과는 'subscribed' 이벤트로 온다)"""
        if not self.sio.connected:
            return
        await self.sio.emit("subscribe", {"streamerUid": _ALL, "token": settings.chzzk_relay_token})

    async def start(self):
        """릴레이 연결 + 구독 동기화 루프 (릴레이 토큰 없으면 비활성)"""
        if not settings.chzzk_relay_token:
            logger.info("[ChzzkRelay] 릴레이 토큰 미설정 — 채팅 연동 비활성화")
            return
        self._running = True
        url = settings.chzzk_relay_url
        # 연결 직후 들어오는 메시지를 거르지 않도록 목록을 먼저 읽는다
        await self._refresh_channels()
        try:
            while self._running:
                if not self.sio.connected:
                    try:
                        logger.info(f"[ChzzkRelay] 릴레이 연결 시도: {url}")
                        await self.sio.connect(url, transports=["websocket", "polling"])
                    except Exception as e:
                        logger.error(f"[ChzzkRelay] 연결 실패: {e}")
                        await asyncio.sleep(5)
                        continue
                # 주기적으로 연동 채널 목록 갱신 + 구독이 안 됐으면 재시도
                await asyncio.sleep(_REFRESH_INTERVAL)
                await self._refresh_channels()
                if self.sio.connected and not self._subscribed:
                    await self._subscribe()
        except asyncio.CancelledError:
            pass  # 서버 종료 — finally 에서 정리
        finally:
            # 취소/강제 종료 중에도 안전하게 — 정리 실패가 종료 흐름을 막지 않게 한다
            try:
                await self.disconnect()
            except BaseException:
                pass

    async def disconnect(self):
        """릴레이 연결 해제 + 소켓 세션 정리 (Unclosed session 방지)"""
        self._running = False
        try:
            if self.sio.connected:
                # 종료 중 소켓이 응답 없으면 무한정 기다리지 않도록 시간 제한
                await asyncio.wait_for(self.sio.disconnect(), timeout=2)
                logger.info("[ChzzkRelay] 연결 해제됨")
        except (Exception, asyncio.CancelledError):
            pass
        # engineio 의 aiohttp 세션이 남아있으면 닫는다
        try:
            eio = getattr(self.sio, "eio", None)
            session = getattr(eio, "http", None) if eio else None
            if session is not None and not session.closed:
                await session.close()
        except Exception:
            pass


# 싱글톤 인스턴스
chzzk_connection_client = ChzzkConnectionClient()
