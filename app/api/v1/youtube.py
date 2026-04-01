from fastapi import APIRouter, Query
from app.integrations.youtube_api import youtube_api

router = APIRouter()

@router.get("/search")
async def search_youtube(
    q: str = Query(...),
    page_token: str = Query(None),
):
    return await youtube_api.search_videos(q, page_token=page_token)

@router.get("/info")
async def get_video_info(
    video_id: str = Query(...),
):
    return await youtube_api.get_video_by_id(video_id)
