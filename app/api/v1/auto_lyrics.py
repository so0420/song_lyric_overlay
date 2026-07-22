"""자동 가사(LRCLIB) 적용 기록 API.

노래하기 탭에서 가사 없는 곡에 LRCLIB 싱크 가사를 적용하면 여기에 기록을 남긴다.
'이 곡만 오프셋' 을 조정하면 그 값을 기록에 반영해, 관리자가 나중에 검토 후
정식 가사로 등록할 수 있게 한다.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_api
from app.database.auto_lyrics_repository import get_auto_lyrics_repository, AutoLyricsRepository
from app.schemas.auto_lyrics import AutoLyricsApplySchema, OffsetPatchSchema
from app.utils.csrf import verify_csrf
from app.utils.log import logger

router = APIRouter()


@router.post("/apply", dependencies=[Depends(verify_csrf)])
async def apply_auto_lyrics(
    data: AutoLyricsApplySchema,
    user=Depends(get_current_user_api),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """자동 가사 적용 기록 저장(upsert). 반환한 import_id 로 이후 오프셋을 갱신한다."""
    # 프론트는 외부 ID만 안정적으로 가지고 있으므로 숫자 songs.id 로 해석한다.
    song_id = await repo.resolve_song_id(data.song_external_id)
    if not song_id:
        raise HTTPException(status_code=404, detail="곡을 찾을 수 없습니다.")

    import_id = await repo.upsert_import(
        user_id=user["id"],
        song_id=song_id,
        lyrics_data=data.lyrics_data,
        source=data.source,
        source_id=data.source_id,
        track_name=data.track_name,
        artist_name=data.artist_name,
        album_name=data.album_name,
        duration=data.duration,
        synced_lyrics=data.synced_lyrics,
        mr_youtube_video_id=data.mr_youtube_video_id,
        offset_ms=data.offset_ms,
    )
    if not import_id:
        raise HTTPException(status_code=500, detail="자동 가사 기록 저장에 실패했습니다.")
    logger.info(f"자동 가사 적용 기록: import_id={import_id}, song_id={song_id}, user={user['id']}")
    return {"import_id": import_id}


@router.patch("/{import_id}/offset", dependencies=[Depends(verify_csrf)])
async def update_offset(
    import_id: int,
    data: OffsetPatchSchema,
    user=Depends(get_current_user_api),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """'이 곡만 오프셋' 조정값을 기록에 반영 (본인 소유 기록만)."""
    updated = await repo.update_offset(import_id, user["id"], data.offset_ms)
    if not updated:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없거나 수정 권한이 없습니다.")
    return {"success": True, "offset_ms": data.offset_ms}
