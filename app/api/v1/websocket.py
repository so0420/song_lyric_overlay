from typing import Optional, List
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.core.websocket import ws_manager
from app.utils.log import logger
from app.database.mariadb import db_handler

router = APIRouter()

@router.websocket("/{token}")
async def websocket_endpoint(
    websocket: WebSocket, 
    token: str,
    events: Optional[str] = Query(None) # 예: ?events=NEW_SONG,LYRICS
):
    # 토큰으로 스트리머 정보 조회
    # token을 경로 파라미터로 받아 해당 스트리머의 streamer_id를 찾습니다.
    streamer = await db_handler.fetch_one(
        "SELECT streamer_id FROM streamers WHERE token = %s",
        (token,)
    )
    
    if not streamer:
        logger.warning(f"WebSocket connection rejected: invalid token {token}")
        await websocket.accept() 
        await websocket.send_text(json.dumps({"type": "ERROR", "message": "Invalid token"}, ensure_ascii=False))
        await websocket.close(code=1008) # Policy Violation
        return

    streamer_id = str(streamer['streamer_id'])
    
    # 쿼리 스트링으로 들어온 초기 구독 이벤트 파싱
    initial_events = events.split(",") if events else None
    
    # 조회된 streamer_id를 식별자로 사용하여 연결
    logger.info(f"Connecting to WebSocket for streamer {streamer_id} with events {initial_events}")
    await ws_manager.connect(websocket, streamer_id, initial_events)
    logger.info(f"WebSocket connection established for streamer {streamer_id} with events {initial_events}")
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data_str = await websocket.receive_text()
            try:
                data = json.loads(data_str)
                # 구독 업데이트 요청 처리: {"action": "subscribe", "events": ["EVENT1", "EVENT2"]}
                if data.get("action") == "subscribe":
                    new_events = data.get("events", [])
                    await ws_manager.subscribe(websocket, streamer_id, new_events)
                    # 확인 메시지 전송
                    logger.info(f"Subscription updated for streamer {streamer_id} with events {new_events}")
                    await websocket.send_text(json.dumps({
                        "type": "SUBSCRIPTION_CONFIRMED", 
                        "events": list(new_events)
                    }, ensure_ascii=False))
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received from streamer {streamer_id}")
                pass
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket connection closed for streamer {streamer_id}")
        ws_manager.disconnect(websocket, streamer_id)
    except Exception as e:
        logger.error(f"WebSocket error for streamer {streamer_id}: {e}")
        ws_manager.disconnect(websocket, streamer_id)