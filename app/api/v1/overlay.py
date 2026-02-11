from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from app.core.auth import get_current_user_api
from app.core.overlay_websocket import overlay_manager
from app.database.mariadb import db_handler
from app.utils.ws_token import generate_ws_token, verify_ws_token, verify_overlay_token
from app.schemas.overlay import OverlaySettingsSchema, LyricsSyncSchema, PlaylistSyncSchema
import json

router = APIRouter()

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
    data: LyricsSyncSchema,
    user=Depends(get_current_user_api)
):
    """노래하기 페이지에서 가사 동기화 요청"""
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "lyrics_update",
        "data": data.model_dump()
    })
    return {"success": True}

@router.post("/sync-playlist")
async def sync_playlist(
    data: PlaylistSyncSchema,
    user=Depends(get_current_user_api)
):
    """재생목록 동기화 요청"""
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "playlist_update",
        "data": data.model_dump()
    })
    return {"success": True}

@router.get("/ws-token")
async def get_ws_token(user=Depends(get_current_user_api)):
    """WebSocket 연결용 일회용 토큰 발급"""
    token = await generate_ws_token(user['id'])
    return {"token": token}

@router.websocket("/ws/{user_id}")
async def overlay_websocket(
    websocket: WebSocket,
    user_id: int,
    token: str = Query(None),
    overlay_token: str = Query(None)
):
    """OBS 오버레이용 WebSocket 연결 (토큰 인증 필수)"""
    verified_user_id = None

    # 1. 일회용 토큰 검증 (노래하기 페이지에서 사용)
    if token:
        verified_user_id = await verify_ws_token(token)
    # 2. 오버레이 영구 토큰 검증 (OBS에서 사용)
    elif overlay_token:
        verified_user_id = verify_overlay_token(overlay_token)

    # 검증 실패
    if verified_user_id is None or verified_user_id != user_id:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

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
