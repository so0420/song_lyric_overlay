from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from app.core.auth import get_current_user_api
from app.core.overlay_websocket import overlay_manager
from app.database.mariadb import db_handler
from pydantic import BaseModel
from typing import Optional
import json

router = APIRouter()

class OverlaySettingsSchema(BaseModel):
    # 가사 스타일
    font_family: str = "Pretendard"
    font_size: int = 52
    font_color: str = "#FFFFFF"
    highlight_color: str = "#FFE500"
    # 요소별 굵기
    current_line_weight: int = 800
    prev_line_weight: int = 600
    next_line_weight: int = 600
    song_title_weight: int = 800
    artist_weight: int = 600
    # 텍스트 외곽선
    text_stroke: bool = True
    stroke_color: str = "#000000"
    # 요소별 외곽선 두께
    current_line_stroke: int = 3
    prev_line_stroke: int = 2
    next_line_stroke: int = 2
    song_title_stroke: int = 3
    artist_stroke: int = 2
    text_shadow: bool = True
    # 표시 옵션
    animation_enabled: bool = True
    show_prev_line: bool = True
    show_next_line: bool = True
    # 노래 정보
    show_song_title: bool = True
    show_artist: bool = True
    show_now_badge: bool = True
    song_title_size: int = 48
    artist_size: int = 28

@router.get("/settings")
async def get_overlay_settings(user=Depends(get_current_user_api)):
    """오버레이 설정 조회"""
    result = await db_handler.fetch_one(
        "SELECT settings_json FROM user_overlay_settings WHERE user_id = %s",
        (user['id'],)
    )

    if result and result['settings_json']:
        return json.loads(result['settings_json'])

    # 기본값 반환
    return OverlaySettingsSchema().model_dump()

@router.post("/settings")
async def save_overlay_settings(
    settings: OverlaySettingsSchema,
    user=Depends(get_current_user_api)
):
    """오버레이 설정 저장"""
    settings_json = json.dumps(settings.model_dump())

    # UPSERT
    existing = await db_handler.fetch_one(
        "SELECT id FROM user_overlay_settings WHERE user_id = %s",
        (user['id'],)
    )

    if existing:
        await db_handler.execute_query(
            "UPDATE user_overlay_settings SET settings_json = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s",
            (settings_json, user['id'])
        )
    else:
        await db_handler.execute_query(
            "INSERT INTO user_overlay_settings (user_id, settings_json) VALUES (%s, %s)",
            (user['id'], settings_json)
        )

    # 연결된 OBS 오버레이에 설정 변경 알림
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "settings_update",
        "settings": settings.model_dump()
    })

    return {"success": True}

@router.post("/sync")
async def sync_lyrics(
    data: dict,
    user=Depends(get_current_user_api)
):
    """노래하기 페이지에서 가사 동기화 요청"""
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "lyrics_update",
        "data": data
    })
    return {"success": True}

@router.websocket("/ws/{user_id}")
async def overlay_websocket(websocket: WebSocket, user_id: int):
    """OBS 오버레이용 WebSocket 연결"""
    await overlay_manager.connect(websocket, user_id)
    try:
        while True:
            # 클라이언트로부터 메시지 대기 (ping/pong 등)
            data = await websocket.receive_text()
            # 필요시 처리
    except WebSocketDisconnect:
        await overlay_manager.disconnect(websocket, user_id)
    except Exception:
        await overlay_manager.disconnect(websocket, user_id)
