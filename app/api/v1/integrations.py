from fastapi import APIRouter, Depends, HTTPException
from app.database.mariadb import get_mariadb_handler, MariaDBHandler
from app.core.auth import get_current_user_api
from app.utils.config import settings

router = APIRouter()

@router.get("/chzzk/status")
async def get_chzzk_status(user=Depends(get_current_user_api), db: MariaDBHandler = Depends(get_mariadb_handler)):
    """현재 치지직 연동 상태를 확인합니다."""
    # 기본 앱 ID 사용 (필요시 여러 앱 지원 확장 가능)
    app_id = settings.chzzk_default_app_id
    
    sql = "SELECT channel_name FROM user_chzzk_tokens WHERE user_id = %s AND app_id = %s"
    token = await db.fetch_one(sql, (user['id'], app_id))
    
    if token:
        return {"is_connected": True, "channel_name": token['channel_name']}
    else:
        return {"is_connected": False, "channel_name": None}

@router.delete("/chzzk")
async def disconnect_chzzk(user=Depends(get_current_user_api), db: MariaDBHandler = Depends(get_mariadb_handler)):
    """치지직 연동을 해제합니다."""
    app_id = settings.chzzk_default_app_id
    sql = "DELETE FROM user_chzzk_tokens WHERE user_id = %s AND app_id = %s"
    await db.execute_query(sql, (user['id'], app_id))
    return {"success": True}
