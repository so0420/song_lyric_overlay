from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.auth import require_admin
from app.core.overlay_websocket import overlay_manager
from app.database.mariadb import db_handler
from app.database.access_request_repository import get_access_request_repository, AccessRequestRepository
from app.schemas.access_request import AccessRequestRejectSchema, AccessRequestResponseSchema
from typing import List, Optional

router = APIRouter()


@router.get("/websocket/stats")
async def get_websocket_stats(user=Depends(require_admin)):
    """WebSocket 연결 통계 조회"""
    connections = overlay_manager.active_connections

    # 사용자별 연결 정보
    user_connections = []
    total_connections = 0

    for user_id, sockets in connections.items():
        connection_count = len(sockets)
        total_connections += connection_count
        user_connections.append({
            "user_id": user_id,
            "connection_count": connection_count
        })

    # 사용자 정보 조회
    if user_connections:
        user_ids = [uc["user_id"] for uc in user_connections]
        format_strings = ','.join(['%s'] * len(user_ids))
        users = await db_handler.fetch_all(
            f"SELECT id, name, email FROM users WHERE id IN ({format_strings})",
            tuple(user_ids)
        )
        user_map = {u['id']: u for u in users}

        for uc in user_connections:
            user_info = user_map.get(uc["user_id"], {})
            uc["user_name"] = user_info.get("name", "Unknown")
            uc["user_email"] = user_info.get("email", "Unknown")

    # 연결 수 기준 내림차순 정렬
    user_connections.sort(key=lambda x: x["connection_count"], reverse=True)

    return {
        "total_connections": total_connections,
        "unique_users": len(user_connections),
        "connections": user_connections
    }


@router.post("/websocket/disconnect/{user_id}")
async def disconnect_user(user_id: int, user=Depends(require_admin)):
    """특정 사용자의 모든 WebSocket 연결 종료"""
    if user_id not in overlay_manager.active_connections:
        return {"success": False, "message": "해당 사용자의 연결이 없습니다."}

    # 연결 종료 메시지 전송
    await overlay_manager.broadcast_to_user(user_id, {
        "type": "admin_disconnect",
        "message": "관리자에 의해 연결이 종료되었습니다."
    })

    # 연결 종료 (클라이언트가 메시지를 받고 종료하도록 유도)
    disconnected = len(overlay_manager.active_connections.get(user_id, []))

    return {
        "success": True,
        "message": f"{disconnected}개의 연결이 종료 요청되었습니다."
    }


@router.get("/websocket/broadcast")
async def broadcast_message(
    message: str,
    user=Depends(require_admin)
):
    """모든 연결에 메시지 브로드캐스트"""
    total_sent = 0

    for user_id in list(overlay_manager.active_connections.keys()):
        connections = overlay_manager.active_connections.get(user_id, [])
        for _ in connections:
            total_sent += 1
        await overlay_manager.broadcast_to_user(user_id, {
            "type": "admin_message",
            "message": message
        })

    return {
        "success": True,
        "message": f"{total_sent}개의 연결에 메시지가 전송되었습니다."
    }


# ============ Access Request Management ============

@router.get("/access-requests", response_model=List[AccessRequestResponseSchema])
async def get_access_requests(
    status: Optional[str] = Query(None, description="필터: pending, approved, rejected"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """접근 요청 목록 조회"""
    return await repo.get_all_requests(status=status, limit=limit, offset=offset)


@router.get("/access-requests/pending-count")
async def get_pending_count(
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """대기 중인 요청 수 조회"""
    count = await repo.get_pending_count()
    return {"count": count}


@router.get("/access-requests/{request_id}", response_model=AccessRequestResponseSchema)
async def get_access_request(
    request_id: int,
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """특정 요청 조회"""
    request = await repo.get_request_by_id(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다")
    return request


@router.post("/access-requests/{request_id}/approve")
async def approve_access_request(
    request_id: int,
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """요청 승인"""
    success = await repo.approve_request(request_id, user['id'])
    if not success:
        raise HTTPException(status_code=400, detail="요청을 승인할 수 없습니다. 이미 처리되었거나 존재하지 않는 요청입니다.")
    return {"success": True, "message": "요청이 승인되었습니다"}


@router.post("/access-requests/{request_id}/reject")
async def reject_access_request(
    request_id: int,
    data: AccessRequestRejectSchema,
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """요청 거절"""
    success = await repo.reject_request(request_id, user['id'], data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="요청을 거절할 수 없습니다. 이미 처리되었거나 존재하지 않는 요청입니다.")
    return {"success": True, "message": "요청이 거절되었습니다"}


@router.get("/approved-users")
async def get_approved_users(
    search: Optional[str] = Query(None, description="이름 또는 이메일 검색"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """승인된 사용자 목록 조회"""
    users = await repo.get_approved_users(search=search, limit=limit, offset=offset)
    return users


@router.post("/users/{user_id}/revoke-overlay")
async def revoke_overlay_access(
    user_id: int,
    data: AccessRequestRejectSchema,
    user=Depends(require_admin),
    repo: AccessRequestRepository = Depends(get_access_request_repository)
):
    """사용자의 오버레이 접근 권한 취소"""
    await repo.revoke_approval(user_id, user['id'], data.reason)
    return {"success": True, "message": "접근 권한이 취소되었습니다"}
