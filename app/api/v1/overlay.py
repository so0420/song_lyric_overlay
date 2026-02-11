from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from app.core.auth import get_current_user_api
from app.core.overlay_websocket import overlay_manager
from app.database.overlay_repository import get_overlay_repository, OverlayRepository
from app.utils.ws_token import generate_ws_token, verify_ws_token, verify_overlay_token
from app.schemas.overlay import OverlaySettingsSchema, LyricsSyncSchema, PlaylistSyncSchema
from app.schemas.common import TokenResponse
import asyncio
import json
import time

router = APIRouter()

@router.get("/settings")
async def get_overlay_settings(
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """오버레이 설정 조회"""
    settings = await overlay_repo.get_settings(user['id'])
    if settings:
        return settings

    # 기본값 반환
    return OverlaySettingsSchema().model_dump()

@router.post("/settings")
async def save_overlay_settings(
    settings: OverlaySettingsSchema,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """오버레이 설정 저장"""
    await overlay_repo.save_settings(user['id'], settings)

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
    return TokenResponse(token=token)

PING_INTERVAL = 30  # 30초마다 ping 전송
PONG_TIMEOUT = 60   # 60초 내 pong 미응답 시 연결 종료


@router.websocket("/ws/{user_id}")
async def overlay_websocket(
    websocket: WebSocket,
    user_id: int,
    token: str = Query(None),
    overlay_token: str = Query(None)
):
    """OBS 오버레이용 WebSocket 연결 (토큰 인증 필수, Heartbeat 지원)"""
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

    last_pong_time = time.time()
    ping_task = None

    async def send_ping():
        """주기적으로 ping 전송"""
        nonlocal last_pong_time
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                # pong 타임아웃 체크
                if time.time() - last_pong_time > PONG_TIMEOUT:
                    await websocket.close(code=4002, reason="Pong timeout")
                    return
                # ping 전송
                await websocket.send_json({"type": "ping"})
        except Exception:
            pass

    try:
        # ping 태스크 시작
        ping_task = asyncio.create_task(send_ping())

        while True:
            # 클라이언트로부터 메시지 대기
            data = await websocket.receive_text()

            # JSON 파싱 및 pong 처리
            try:
                message = json.loads(data)
                if message.get("type") == "pong":
                    last_pong_time = time.time()
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ping_task:
            ping_task.cancel()
        await overlay_manager.disconnect(websocket, user_id)
