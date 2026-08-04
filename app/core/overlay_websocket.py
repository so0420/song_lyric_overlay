from fastapi import WebSocket
from typing import Dict, List, Set
import json
import asyncio

class OverlayConnectionManager:
    """오버레이 WebSocket 연결 관리자"""

    def __init__(self):
        # user_id -> set of WebSocket connections
        self.overlay_connections: Dict[int, Set[WebSocket]] = {}  # OBS 오버레이
        self.singer_connections: Dict[int, Set[WebSocket]] = {}   # 노래하기 페이지
        self._lock = asyncio.Lock()

    @property
    def active_connections(self) -> Dict[int, Set[WebSocket]]:
        """모든 연결 반환 (호환용)"""
        merged: Dict[int, Set[WebSocket]] = {}
        for user_id, conns in self.overlay_connections.items():
            merged.setdefault(user_id, set()).update(conns)
        for user_id, conns in self.singer_connections.items():
            merged.setdefault(user_id, set()).update(conns)
        return merged

    async def connect(self, websocket: WebSocket, user_id: int, connection_type: str = "overlay"):
        """새 연결 추가"""
        await websocket.accept()
        pool = self.overlay_connections if connection_type == "overlay" else self.singer_connections
        async with self._lock:
            if user_id not in pool:
                pool[user_id] = set()
            pool[user_id].add(websocket)

    async def disconnect(self, websocket: WebSocket, user_id: int, connection_type: str = "overlay"):
        """연결 제거"""
        pool = self.overlay_connections if connection_type == "overlay" else self.singer_connections
        async with self._lock:
            if user_id in pool:
                pool[user_id].discard(websocket)
                if not pool[user_id]:
                    del pool[user_id]

    async def broadcast_to_singers(self, user_id: int, message: dict):
        """노래하기 페이지 연결에만 메시지 전송"""
        if user_id not in self.singer_connections:
            return

        dead_connections = set()
        for connection in self.singer_connections[user_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        if dead_connections:
            async with self._lock:
                if user_id in self.singer_connections:
                    for conn in dead_connections:
                        self.singer_connections[user_id].discard(conn)

    async def broadcast_to_overlays(self, user_id: int, message: dict, exclude: WebSocket = None):
        """OBS 오버레이 연결에만 메시지 전송

        exclude: 보낸 연결 자신에게는 되돌려주지 않을 때 지정한다.
                 (가사 보기 창이 자기 스크롤 상태를 다른 오버레이로 중계하는 경우)
        """
        if user_id not in self.overlay_connections:
            return

        dead_connections = set()
        for connection in list(self.overlay_connections[user_id]):
            if connection is exclude:
                continue
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)

        if dead_connections:
            async with self._lock:
                if user_id in self.overlay_connections:
                    for conn in dead_connections:
                        self.overlay_connections[user_id].discard(conn)

    async def broadcast_to_user(self, user_id: int, message: dict):
        """특정 유저의 모든 연결(OBS + 노래하기)에 메시지 전송"""
        all_conns = set()
        if user_id in self.overlay_connections:
            all_conns.update(self.overlay_connections[user_id])
        if user_id in self.singer_connections:
            all_conns.update(self.singer_connections[user_id])

        if not all_conns:
            return

        dead_overlay = set()
        dead_singer = set()
        for connection in all_conns:
            try:
                await connection.send_json(message)
            except Exception:
                if user_id in self.overlay_connections and connection in self.overlay_connections[user_id]:
                    dead_overlay.add(connection)
                if user_id in self.singer_connections and connection in self.singer_connections[user_id]:
                    dead_singer.add(connection)

        if dead_overlay or dead_singer:
            async with self._lock:
                for conn in dead_overlay:
                    if user_id in self.overlay_connections:
                        self.overlay_connections[user_id].discard(conn)
                for conn in dead_singer:
                    if user_id in self.singer_connections:
                        self.singer_connections[user_id].discard(conn)

# 싱글톤 인스턴스
overlay_manager = OverlayConnectionManager()
