from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from app.core.auth import get_current_user_api
from app.core.overlay_websocket import overlay_manager
from app.database.overlay_repository import get_overlay_repository, OverlayRepository
from app.utils.ws_token import (
    generate_ws_token,
    verify_ws_token,
    verify_overlay_token_async,
    get_or_create_overlay_token,
    generate_overlay_token
)
from app.utils.csrf import verify_csrf
from app.schemas.overlay import (
    OverlaySettingsSchema,
    LyricsInitSchema,
    LyricsTimeSyncSchema,
    PlaylistSyncSchema,
    OverlayPresetCreateSchema,
    OverlayPresetUpdateSchema,
    OverlayPresetResponseSchema
)
from typing import List
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

@router.post("/settings", dependencies=[Depends(verify_csrf)])
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

@router.post("/sync-init", dependencies=[Depends(verify_csrf)])
async def sync_lyrics_init(
    data: LyricsInitSchema,
    user=Depends(get_current_user_api)
):
    """곡 시작 시 전체 가사 데이터 + 시간 전송"""
    await overlay_manager.broadcast_to_overlays(user['id'], {
        "type": "lyrics_init",
        "data": data.model_dump()
    })
    return {"success": True}

@router.post("/sync-time", dependencies=[Depends(verify_csrf)])
async def sync_lyrics_time(
    data: LyricsTimeSyncSchema,
    user=Depends(get_current_user_api)
):
    """주기적 시간 동기화"""
    await overlay_manager.broadcast_to_overlays(user['id'], {
        "type": "lyrics_time_sync",
        "data": data.model_dump()
    })
    return {"success": True}

@router.post("/sync-playlist", dependencies=[Depends(verify_csrf)])
async def sync_playlist(
    data: PlaylistSyncSchema,
    user=Depends(get_current_user_api)
):
    """재생목록 동기화 요청"""
    await overlay_manager.broadcast_to_overlays(user['id'], {
        "type": "playlist_update",
        "data": data.model_dump()
    })
    return {"success": True}

@router.get("/ws-token")
async def get_ws_token(user=Depends(get_current_user_api)):
    """WebSocket 연결용 일회용 토큰 발급"""
    token = await generate_ws_token(user['id'])
    return TokenResponse(token=token)


@router.get("/overlay-token")
async def get_current_overlay_token(user=Depends(get_current_user_api)):
    """오버레이 영구 토큰 조회"""
    token = await get_or_create_overlay_token(user['id'])
    return TokenResponse(token=token)


@router.post("/overlay-token/regenerate", dependencies=[Depends(verify_csrf)])
async def regenerate_overlay_token(user=Depends(get_current_user_api)):
    """오버레이 토큰 재발급 (기존 토큰 무효화)"""
    # 기존 연결 종료 알림
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "token_invalidated",
        "message": "토큰이 재발급되어 연결이 종료됩니다."
    })

    # 새 토큰 생성 (기존 토큰 자동 삭제)
    new_token = await generate_overlay_token(user['id'])

    return {
        "success": True,
        "token": new_token,
        "message": "토큰이 재발급되었습니다. OBS에서 새 URL을 설정해주세요."
    }


# ============ Preset Endpoints ============

@router.get("/presets", response_model=List[OverlayPresetResponseSchema])
async def get_presets(
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """프리셋 목록 조회"""
    return await overlay_repo.get_presets(user['id'])


@router.post("/presets", response_model=OverlayPresetResponseSchema, dependencies=[Depends(verify_csrf)])
async def create_preset(
    data: OverlayPresetCreateSchema,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """새 프리셋 생성"""
    preset_id = await overlay_repo.create_preset(user['id'], data)
    preset = await overlay_repo.get_preset(preset_id, user['id'])
    return preset


@router.get("/presets/{preset_id}", response_model=OverlayPresetResponseSchema)
async def get_preset(
    preset_id: int,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """특정 프리셋 조회"""
    preset = await overlay_repo.get_preset(preset_id, user['id'])
    if not preset:
        raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")
    return preset


@router.put("/presets/{preset_id}", response_model=OverlayPresetResponseSchema, dependencies=[Depends(verify_csrf)])
async def update_preset(
    preset_id: int,
    data: OverlayPresetUpdateSchema,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """프리셋 수정"""
    success = await overlay_repo.update_preset(preset_id, user['id'], data)
    if not success:
        raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")
    preset = await overlay_repo.get_preset(preset_id, user['id'])
    return preset


@router.delete("/presets/{preset_id}", dependencies=[Depends(verify_csrf)])
async def delete_preset(
    preset_id: int,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """프리셋 삭제"""
    success = await overlay_repo.delete_preset(preset_id, user['id'])
    if not success:
        raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")
    return {"success": True}


@router.post("/presets/{preset_id}/activate", dependencies=[Depends(verify_csrf)])
async def activate_preset(
    preset_id: int,
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """프리셋 활성화 (현재 설정에 적용)"""
    success = await overlay_repo.activate_preset(preset_id, user['id'])
    if not success:
        raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")

    # 프리셋 설정 가져오기
    preset = await overlay_repo.get_preset(preset_id, user['id'])

    # 연결된 OBS 오버레이에 설정 변경 알림
    await overlay_manager.broadcast_to_user(user['id'], {
        "type": "settings_update",
        "settings": preset['settings']
    })

    return {"success": True, "message": f"'{preset['name']}' 프리셋이 적용되었습니다"}


@router.post("/presets/save-current", dependencies=[Depends(verify_csrf)])
async def save_current_as_preset(
    name: str = Query(..., min_length=1, max_length=100),
    user=Depends(get_current_user_api),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository)
):
    """현재 설정을 새 프리셋으로 저장"""
    # 현재 설정 가져오기
    current_settings = await overlay_repo.get_settings(user['id'])
    if not current_settings:
        current_settings = OverlaySettingsSchema().model_dump()

    # 프리셋 생성
    preset_data = OverlayPresetCreateSchema(
        name=name,
        settings=OverlaySettingsSchema(**current_settings)
    )
    preset_id = await overlay_repo.create_preset(user['id'], preset_data)
    preset = await overlay_repo.get_preset(preset_id, user['id'])
    return preset


PING_INTERVAL = 30  # 30초마다 ping 전송
PONG_TIMEOUT = 60   # 60초 내 pong 미응답 시 연결 종료


@router.websocket("/ws")
async def overlay_websocket(
    websocket: WebSocket,
    token: str = Query(None),
    overlay_token: str = Query(None)
):
    """WebSocket 연결 (토큰 인증 필수, Heartbeat 지원)

    - token: 일회용 토큰 → singer 연결 (노래하기 페이지)
    - overlay_token: 영구 토큰 → overlay 연결 (OBS)

    보안: user_id는 URL에 포함하지 않고 토큰에서만 추출합니다.
    """
    verified_user_id = None
    connection_type = None

    # 1. 일회용 토큰 검증 (노래하기 페이지 → singer)
    if token:
        verified_user_id = await verify_ws_token(token)
        connection_type = "singer"
    # 2. 오버레이 영구 토큰 검증 (OBS → overlay)
    elif overlay_token:
        verified_user_id = await verify_overlay_token_async(overlay_token)
        connection_type = "overlay"

    # 검증 실패 - 토큰이 없거나 유효하지 않음
    if verified_user_id is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await overlay_manager.connect(websocket, verified_user_id, connection_type)

    # overlay(OBS) 연결 시 singer에게 현재 상태 재전송 요청
    if connection_type == "overlay":
        await overlay_manager.broadcast_to_singers(verified_user_id, {
            "type": "request_init"
        })

    last_pong_time = time.time()
    ping_task = None

    # singer → overlay로 중계할 메시지 타입
    RELAY_TO_OVERLAY_TYPES = {"lyrics_time_sync", "lyrics_init", "playlist_update"}

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

            # JSON 파싱 및 처리
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "pong":
                    last_pong_time = time.time()
                elif connection_type == "singer" and msg_type in RELAY_TO_OVERLAY_TYPES:
                    # singer → overlay 중계
                    await overlay_manager.broadcast_to_overlays(verified_user_id, message)
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        # 서버 종료 등으로 태스크가 취소된 경우 — 조용히 정리
        pass
    except Exception:
        pass
    finally:
        if ping_task:
            ping_task.cancel()
        try:
            await overlay_manager.disconnect(websocket, verified_user_id, connection_type)
        except Exception:
            pass
