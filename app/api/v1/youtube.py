from fastapi import APIRouter, Query, Depends
from app.core.auth import get_current_user_api
from app.integrations.youtube_api import youtube_api

router = APIRouter()

@router.get("/search")
async def search_youtube(
    q: str = Query(...),
    page_token: str = Query(None),
    user=Depends(get_current_user_api)
):
    return await youtube_api.search_videos(q, page_token=page_token)

@router.get("/info")
async def get_video_info(
    video_id: str = Query(...),
    user=Depends(get_current_user_api)
):
    return await youtube_api.get_video_by_id(video_id)
