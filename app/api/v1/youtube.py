from fastapi import APIRouter, Query, HTTPException
from app.integrations.youtube_api import youtube_api
from app.utils.log import logger

router = APIRouter()

QUOTA_MESSAGE = "오늘의 유튜브 검색 한도를 모두 사용했습니다. 잠시 후 다시 시도해주세요."


def _is_quota_error(e: Exception) -> bool:
    """공식 API 쿼터 소진 여부. 소진 시 검색이 불가능하므로 일반 오류와 구분해 안내한다."""
    err = str(e)
    return "quotaExceeded" in err or "403" in err


@router.get("/search")
async def search_youtube(
    q: str = Query(...),
    page_token: str = Query(None),
):
    try:
        return await youtube_api.search_videos(q, page_token=page_token)
    except Exception as e:
        logger.error(f"YouTube search failed: {e}")
        if _is_quota_error(e):
            raise HTTPException(status_code=503, detail=QUOTA_MESSAGE)
        raise HTTPException(status_code=500, detail="유튜브 검색 중 오류가 발생했습니다.")


@router.get("/info")
async def get_video_info(
    video_id: str = Query(...),
):
    try:
        return await youtube_api.get_video_by_id(video_id)
    except Exception as e:
        logger.error(f"YouTube get video failed: {e}")
        if _is_quota_error(e):
            raise HTTPException(status_code=503, detail=QUOTA_MESSAGE)
        raise HTTPException(status_code=500, detail="영상 정보 조회 중 오류가 발생했습니다.")
