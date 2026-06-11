from fastapi import APIRouter, Depends

from app.core.auth import get_current_user_api
from app.utils.config import settings
from app.utils.csrf import verify_csrf
from app.database.chzzk_repository import get_chzzk_channel_repository, ChzzkChannelRepository

router = APIRouter()


@router.get("/chzzk/status")
async def get_chzzk_status(
    user=Depends(get_current_user_api),
    channel_repo: ChzzkChannelRepository = Depends(get_chzzk_channel_repository),
):
    """현재 로그인 유저의 치지직 연동 상태"""
    configured = bool(settings.chzzk_client_id and settings.chzzk_interlock_redirect_uri)
    channel = await channel_repo.get(user["id"])
    if channel:
        return {
            "configured": configured,
            "is_connected": True,
            "channel_name": channel.get("channel_name"),
            "channel_id": channel.get("channel_id"),
        }
    return {"configured": configured, "is_connected": False, "channel_name": None, "channel_id": None}


@router.delete("/chzzk", dependencies=[Depends(verify_csrf)])
async def disconnect_chzzk(
    user=Depends(get_current_user_api),
    channel_repo: ChzzkChannelRepository = Depends(get_chzzk_channel_repository),
):
    """치지직 연동 해제 (채널 매핑 삭제)"""
    await channel_repo.delete(user["id"])
    return {"success": True}
