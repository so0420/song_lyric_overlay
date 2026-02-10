from fastapi import WebSocket
from typing import Dict, List, Set
import json
import asyncio

class OverlayConnectionManager:
    """오버레이 WebSocket 연결 관리자"""

    def __init__(self):
        # user_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int):
        """새 연결 추가"""
        await websocket.accept()
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)

    async def disconnect(self, websocket: WebSocket, user_id: int):
        """연결 제거"""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]

    async def broadcast_to_user(self, user_id: int, message: dict):
        """특정 유저의 모든 연결에 메시지 전송"""
        if user_id not in self.active_connections:
            return

        dead_connections = set()
        for connection in self.active_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        # 죽은 연결 정리
        if dead_connections:
            async with self._lock:
                for conn in dead_connections:
                    self.active_connections[user_id].discard(conn)

# 싱글톤 인스턴스
overlay_manager = OverlayConnectionManager()
