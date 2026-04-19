from fastapi import APIRouter, Query, HTTPException
from app.integrations.youtube_api import youtube_api
from app.utils.log import logger

router = APIRouter()


@router.get("/search")
async def search_youtube(
    q: str = Query(...),
    page_token: str = Query(None),
):
    try:
        return await youtube_api.search_videos(q, page_token=page_token)
    except Exception as e:
        logger.error(f"YouTube search failed: {e}")
        raise HTTPException(status_code=500, detail="유튜브 검색 중 오류가 발생했습니다.")


@router.get("/info")
async def get_video_info(
    video_id: str = Query(...),
):
    try:
        return await youtube_api.get_video_by_id(video_id)
    except Exception as e:
        logger.error(f"YouTube get video failed: {e}")
        raise HTTPException(status_code=500, detail="영상 정보 조회 중 오류가 발생했습니다.")
