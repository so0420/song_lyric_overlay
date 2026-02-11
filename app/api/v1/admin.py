from fastapi import APIRouter, Depends
from app.core.auth import require_admin
from app.core.overlay_websocket import overlay_manager
from app.database.mariadb import db_handler

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
