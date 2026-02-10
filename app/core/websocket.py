import json
import asyncio
from typing import Dict, List, Set
from fastapi import WebSocket
from app.database.redis.redis import redis
from app.utils.log import logger

class ConnectionManager:
    def __init__(self):
        # streamer_id -> { WebSocket: Set[event_types] }
        # 만약 Set이 비어있거나 "*"를 포함하면 모든 이벤트를 수신합니다.
        self.active_connections: Dict[str, Dict[WebSocket, Set[str]]] = {}
        self._pubsub_task = None

    async def start(self):
        """Redis 구독 태스크를 시작합니다."""
        if self._pubsub_task is None:
            self._pubsub_task = asyncio.create_task(self._redis_subscriber())
            logger.info("WebSocket Redis Subscriber started.")

    async def stop(self):
        """Redis 구독 태스크를 중지합니다."""
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None
            logger.info("WebSocket Redis Subscriber stopped.")

    async def connect(self, websocket: WebSocket, streamer_id: str, initial_events: List[str] = None):
        await websocket.accept()
        if streamer_id not in self.active_connections:
            self.active_connections[streamer_id] = {}
        
        # 초기 구독 이벤트 설정 (없으면 "*"로 모든 이벤트 수신)
        self.active_connections[streamer_id][websocket] = set(initial_events) if initial_events else {"*"}
        logger.debug(f"Client connected to streamer {streamer_id}. Events: {self.active_connections[streamer_id][websocket]}")

    def disconnect(self, websocket: WebSocket, streamer_id: str):
        if streamer_id in self.active_connections:
            if websocket in self.active_connections[streamer_id]:
                del self.active_connections[streamer_id][websocket]
            if not self.active_connections[streamer_id]:
                del self.active_connections[streamer_id]
        logger.debug(f"Client disconnected from streamer {streamer_id}.")

    async def subscribe(self, websocket: WebSocket, streamer_id: str, events: List[str]):
        """클라이언트의 구독 이벤트를 업데이트합니다."""
        if streamer_id in self.active_connections and websocket in self.active_connections[streamer_id]:
            self.active_connections[streamer_id][websocket] = set(events)
            logger.debug(f"Client subscriptions updated for {streamer_id}: {events}")

    async def broadcast_to_streamer(self, streamer_id: str, message: dict):
        """특정 스트리머 채널에 접속 중인 클라이언트 중 해당 이벤트를 구독한 대상에게만 전송"""
        if streamer_id in self.active_connections:
            event_type = message.get("type", "*")
            message_str = json.dumps(message, ensure_ascii=False)
            
            send_tasks = []
            for ws, subscriptions in self.active_connections[streamer_id].items():
                # 모든 이벤트(*)를 구독했거나, 특정 이벤트 타입이 구독 목록에 있는 경우
                if "*" in subscriptions or event_type in subscriptions:
                    send_tasks.append(ws.send_text(message_str))
            
            if send_tasks:
                await asyncio.gather(*send_tasks, return_exceptions=True)

    async def publish_event(self, streamer_id: str, event_type: str, data: dict):
        """이벤트를 Redis에 발행합니다."""
        payload = {
            "type": event_type,
            "streamer_id": str(streamer_id),
            "data": data
        }
        await redis.client.publish(f"songbook:streamer:{streamer_id}", json.dumps(payload, ensure_ascii=False))

    async def _redis_subscriber(self):
        """Redis Pub/Sub 수신부"""
        pubsub = redis.client.pubsub()
        await pubsub.psubscribe("songbook:streamer:*")
        
        try:
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        channel = message["channel"]
                        streamer_id = channel.split(":")[-1]
                        data = json.loads(message["data"])
                        await self.broadcast_to_streamer(streamer_id, data)
                    except Exception as e:
                        logger.error(f"Error processing Redis WS message: {e}")
        except asyncio.CancelledError:
            await pubsub.punsubscribe("songbook:streamer:*")
            await pubsub.close()

ws_manager = ConnectionManager()
