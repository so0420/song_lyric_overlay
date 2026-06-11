"""jamkubot 채팅 릴레이(relay.jamkubot.com) 연결 클라이언트

relay.jamkubot.com 에 Socket.IO 로 접속해 연동된 스트리머 채널을 마스터 토큰으로
구독하고, 들어오는 message 이벤트를 chzzk_event_handler 로 넘긴다.
CHZZK_RELAY_TOKEN 이 설정돼 있어야 동작한다.

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

# 구독 목록 갱신 주기(초) — 새로 연동/해제한 스트리머 반영
_REFRESH_INTERVAL = 30


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
        self._subscribed: set[str] = set()
        self._channel_repo = ChzzkChannelRepository()
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        @self.sio.event
        async def connect():
            logger.info("[ChzzkRelay] 릴레이에 연결됨")
            self._subscribed.clear()
            await self._sync_subscriptions()

        @self.sio.event
        async def disconnect():
            logger.warning("[ChzzkRelay] 릴레이 연결 끊김")
            self._subscribed.clear()

        @self.sio.event
        async def connect_error(data):
            logger.error(f"[ChzzkRelay] 연결 실패: {data}")

        @self.sio.on("message")
        async def on_message(data):
            await chzzk_event_handler.handle_message(data)

        @self.sio.on("subscribed")
        async def on_subscribed(data):
            if isinstance(data, dict) and not data.get("success", True):
                logger.warning(f"[ChzzkRelay] 구독 실패: {data.get('message')} ({data.get('streamerUid')})")

        @self.sio.on("error")
        async def on_error(data):
            logger.error(f"[ChzzkRelay] 에러: {data}")

        @self.sio.on("systemStatus")
        async def on_system_status(data):
            pass

        @self.sio.on("streamerStatus")
        async def on_streamer_status(data):
            pass

    async def _sync_subscriptions(self):
        """연동된 채널 목록과 현재 구독 상태를 맞춘다 (신규 구독 / 해제분 구독취소)"""
        if not self.sio.connected:
            return
        token = settings.chzzk_relay_token
        try:
            channel_ids = set(await self._channel_repo.get_all_channel_ids())
        except Exception as e:
            logger.error(f"[ChzzkRelay] 채널 목록 조회 실패: {e}")
            return

        for uid in channel_ids - self._subscribed:
            await self.sio.emit("subscribe", {"streamerUid": uid, "token": token})
            self._subscribed.add(uid)
            logger.info(f"[ChzzkRelay] 구독: {uid}")

        for uid in self._subscribed - channel_ids:
            await self.sio.emit("unsubscribe", {"streamerUid": uid, "token": token})
            self._subscribed.discard(uid)
            logger.info(f"[ChzzkRelay] 구독 해제: {uid}")

    async def start(self):
        """릴레이 연결 + 구독 동기화 루프 (릴레이 토큰 없으면 비활성)"""
        if not settings.chzzk_relay_token:
            logger.info("[ChzzkRelay] 릴레이 토큰 미설정 — 채팅 연동 비활성화")
            return
        self._running = True
        url = settings.chzzk_relay_url
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
                # 주기적으로 구독 목록 동기화 (새 연동/해제 반영)
                await asyncio.sleep(_REFRESH_INTERVAL)
                await self._sync_subscriptions()
        except asyncio.CancelledError:
            pass  # 서버 종료 — finally 에서 정리
        finally:
            await self.disconnect()

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
