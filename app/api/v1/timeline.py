from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_api
from app.utils.csrf import verify_csrf
from app.database.chzzk_repository import get_chzzk_channel_repository, ChzzkChannelRepository
from app.database.timeline_repository import get_timeline_repository, TimelineRepository
from app.integrations.chzzk_live import get_live_open_date, now_kst, ChzzkLiveError
from app.schemas.timeline import TimelineRecordCreateSchema

router = APIRouter()

# 방송 시작 기준 경과 시간 상한 (초). openDate 가 오래된 값(오프라인 잔여)일 때 방어.
MAX_ELAPSED_SECONDS = 24 * 60 * 60


@router.post("/record", dependencies=[Depends(verify_csrf)])
async def record_timeline(
    payload: TimelineRecordCreateSchema,
    user=Depends(get_current_user_api),
    channel_repo: ChzzkChannelRepository = Depends(get_chzzk_channel_repository),
    timeline_repo: TimelineRepository = Depends(get_timeline_repository),
):
    """현재 방송의 타임라인 1건 기록 (치지직 연동 유저 전용).

    치지직 live-detail 의 openDate 기준 경과 시간을 계산해 곡 제목과 함께 저장한다.
    """
    channel = await channel_repo.get(user["id"])
    if not channel:
        raise HTTPException(status_code=403, detail="치지직 연동이 필요합니다.")

    try:
        open_date = await get_live_open_date(channel["channel_id"])
    except ChzzkLiveError as e:
        raise HTTPException(status_code=409, detail=str(e))

    elapsed = int((now_kst() - open_date).total_seconds())
    if elapsed < 0 or elapsed > MAX_ELAPSED_SECONDS:
        raise HTTPException(status_code=409, detail="방송 정보를 확인할 수 없습니다. (경과 시간 비정상)")

    record_id = await timeline_repo.add_record(
        user_id=user["id"],
        open_date=open_date,
        elapsed_seconds=elapsed,
        title=payload.title,
    )
    return {
        "id": record_id,
        "elapsed_seconds": elapsed,
        "title": payload.title,
        "open_date": open_date.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/records")
async def list_timeline(
    user=Depends(get_current_user_api),
    timeline_repo: TimelineRepository = Depends(get_timeline_repository),
):
    """유저의 최근 1달 타임라인을 방송(openDate)별로 묶어 반환."""
    rows = await timeline_repo.list_records(user["id"])

    broadcasts: list = []
    index: dict = {}
    for row in rows:
        # DATETIME → "YYYY-MM-DD HH:MM:SS" 문자열 키 (방송 구분)
        key = row["open_date"].strftime("%Y-%m-%d %H:%M:%S")
        group = index.get(key)
        if group is None:
            group = {"open_date": key, "records": []}
            index[key] = group
            broadcasts.append(group)
        group["records"].append({
            "id": row["id"],
            "elapsed_seconds": row["elapsed_seconds"],
            "title": row["title"],
        })
    return {"broadcasts": broadcasts}


@router.delete("/records/{record_id}", dependencies=[Depends(verify_csrf)])
async def delete_timeline_record(
    record_id: int,
    user=Depends(get_current_user_api),
    timeline_repo: TimelineRepository = Depends(get_timeline_repository),
):
    """타임라인 기록 1건 삭제 (본인 것만)."""
    deleted = await timeline_repo.delete_record(user["id"], record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    return {"success": True}
