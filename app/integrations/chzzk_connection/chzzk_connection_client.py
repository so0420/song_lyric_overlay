"""
Chzzk Connection Socket Client
Node.js chzzk_connection_socket 서버에 연결하여 
모든 채팅/도네이션/구독 이벤트를 수신합니다.
"""

import asyncio
import socketio
from app.utils.config import settings
from app.utils.log import logger
from app.integrations.chzzk_connection.chzzk_event_handler import chzzk_event_handler
import json


class ChzzkConnectionClient:
    """
    chzzk_connection_socket Node.js 서버에 연결하는 Socket.IO 클라이언트
    """

    def __init__(self):
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # 무제한 재연결
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False
        )
        self._running = False
        self._task = None
        self._setup_event_handlers()

    def _get_master_token(self) -> str:
        """
        환경변수에서 마스터 토큰 가져오기 (쉼표로 구분, 첫 번째 사용)
        """
        master_tokens = settings.socket_server_master_token
        if not master_tokens:
            return ""
        
        # 쉼표로 구분된 경우 첫 번째 토큰 사용
        tokens = [t.strip() for t in master_tokens.split(',')]
        return tokens[0] if tokens else ""

    def _get_server_url(self) -> str:
        """
        Socket 서버 URL 생성
        """
        port = settings.socket_server_port
        return f"http://localhost:{port}"

    def _setup_event_handlers(self):
        """
        Socket.IO 이벤트 핸들러 설정
        """

        @self.sio.event
        async def connect():
            logger.info("[ChzzkConnectionClient] 서버에 연결됨")

        @self.sio.event
        async def connected(raw_data):
            logger.info(f"[ChzzkConnectionClient] 인증 성공: {raw_data}")
            # 'all' 구독
            await self.sio.emit('subscribe', {'channelId': 'all'})

        @self.sio.event
        async def subscribed(raw_data):
            logger.info(f"[ChzzkConnectionClient] 구독 성공: {raw_data}")

        @self.sio.event
        async def disconnect():
            logger.warning("[ChzzkConnectionClient] 서버 연결 끊김")

        @self.sio.event
        async def error(raw_data):
            logger.error(f"[ChzzkConnectionClient] 에러: {raw_data}")

        @self.sio.event
        async def chat(raw_data):
            await chzzk_event_handler.handle_chat(raw_data)

        @self.sio.event
        async def donation(raw_data):
            await chzzk_event_handler.handle_donation(raw_data)

        @self.sio.event
        async def subscription(raw_data):
            await chzzk_event_handler.handle_subscription(raw_data)

        @self.sio.event
        async def status(raw_data):
            await chzzk_event_handler.handle_status(raw_data)

        @self.sio.event
        async def client_activity(raw_data):
            await chzzk_event_handler.handle_client_activity(raw_data)

    async def connect(self):
        """
        서버에 연결
        """
        server_url = self._get_server_url()
        master_token = self._get_master_token()

        if not master_token:
            logger.error("[ChzzkConnectionClient] 마스터 토큰이 설정되지 않았습니다")
            return False

        try:
            logger.info(f"[ChzzkConnectionClient] 서버 연결 시도: {server_url}")
            await self.sio.connect(
                server_url,
                auth={'token': master_token},
                transports=['websocket', 'polling']
            )
            return True
        except Exception as e:
            logger.error(f"[ChzzkConnectionClient] 연결 실패: {e}")
            return False

    async def disconnect(self):
        """
        서버 연결 해제
        """
        self._running = False
        if self.sio.connected:
            await self.sio.disconnect()
            logger.info("[ChzzkConnectionClient] 연결 해제됨")

    async def start(self):
        """
        클라이언트 시작 (연결 유지)
        """
        self._running = True

        while self._running:
            if not self.sio.connected:
                connected = await self.connect()
                if not connected:
                    # 연결 실패 시 5초 후 재시도
                    await asyncio.sleep(5)
                    continue

            # 연결 상태 유지
            await asyncio.sleep(1)


# 싱글톤 인스턴스
chzzk_connection_client = ChzzkConnectionClient()
