"""관리자 전용: 자동 가사(LRCLIB) 기록 검토 및 정식 가사 등록 API."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import require_admin
from app.database.auto_lyrics_repository import get_auto_lyrics_repository, AutoLyricsRepository
from app.database.lyrics_repository import get_lyrics_repository, LyricsRepository
from app.database.songbook_repository import get_songbook_repository
from app.schemas.auto_lyrics import AutoLyricsLinkSchema
from app.utils.audit import log_audit, get_client_ip, AuditAction
from app.utils.csrf import verify_csrf
from app.utils.log import logger

router = APIRouter()

REGISTERED_TITLE = "LRCLIB 자동"


def _bake_offset(lyrics_data: str, offset_ms: int) -> str:
    """'이 곡만 오프셋' 을 타임스탬프에 반영해 오프셋 없이도 맞는 lyrics_data 를 만든다.

    재생 규칙이 `표시시각 = currentTime + offset >= start` 이므로,
    오프셋을 없애려면 각 start/end 에서 offset 을 빼면 된다. (0 미만은 0 으로 클램프)
    """
    if not lyrics_data or not offset_ms:
        return lyrics_data
    try:
        segments = json.loads(lyrics_data)
    except (json.JSONDecodeError, TypeError):
        return lyrics_data
    for seg in segments:
        if "start" in seg and isinstance(seg["start"], (int, float)):
            seg["start"] = max(0, round(seg["start"] - offset_ms))
        if "end" in seg and isinstance(seg["end"], (int, float)):
            seg["end"] = max(0, round(seg["end"] - offset_ms))
    return json.dumps(segments, ensure_ascii=False)


@router.get("/auto-lyrics")
async def list_auto_lyrics(
    status: str = Query("pending", pattern="^(pending|editing|registered|ignored|all)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """자동 가사 기록 목록 (기본: 등록 대기 중)."""
    status_filter = None if status == "all" else status
    items, total = await repo.list_imports(status=status_filter, offset=offset, limit=limit)
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total,
    }


@router.post("/auto-lyrics/{import_id}/claim-edit", dependencies=[Depends(verify_csrf)])
async def claim_edit_auto_lyrics(
    import_id: int,
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """'편집기에서 보기': 기록을 editing 으로 옮겨 pending 리스트에서 빼고 편집기 URL 반환."""
    rec = await repo.get_import(import_id)
    if not rec:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if rec["status"] == "registered":
        raise HTTPException(status_code=400, detail="이미 정식 등록된 기록입니다.")
    if not rec.get("lyrics_data"):
        raise HTTPException(status_code=400, detail="편집할 가사 데이터가 없습니다.")

    await repo.mark_editing(import_id, admin["id"])
    return {"success": True, "editor_url": f"/lyrics/?auto_import_id={import_id}"}


@router.get("/auto-lyrics/{import_id}/editor-data")
async def auto_lyrics_editor_data(
    import_id: int,
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """편집기 로드용 데이터: 곡 정보 + 오프셋 반영(baked)된 가사 + MR 영상."""
    rec = await repo.get_import_with_song(import_id)
    if not rec:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    baked = _bake_offset(rec.get("lyrics_data") or "[]", rec.get("offset_ms") or 0)
    return {
        "import_id": import_id,
        "song_id": rec["song_id"],
        "song_external_id": rec.get("song_external_id"),
        "title": rec.get("song_title"),
        "artist": rec.get("song_artist"),
        "cover_image_url": rec.get("song_cover"),
        "lyrics_data": baked,
        "mr_youtube_video_id": rec.get("mr_youtube_video_id"),
        "offset_ms": rec.get("offset_ms") or 0,
        "status": rec.get("status"),
    }


@router.post("/auto-lyrics/{import_id}/link", dependencies=[Depends(verify_csrf)])
async def link_auto_lyrics(
    import_id: int,
    data: AutoLyricsLinkSchema,
    request: Request,
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """편집기에서 저장해 만든 가사를 이 기록의 정식 가사로 연결(검증 표시 + 등록 처리).

    편집기가 POST /api/v1/lyrics/ 로 만든 lyrics_id 를 받아, 그 가사를 검증(is_verified=1)
    처리하고 기록을 registered 로 확정한다.
    """
    rec = await repo.get_import(import_id)
    if not rec:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")

    lyrics = await lyrics_repo.get_lyrics_by_id(data.lyrics_id)
    if not lyrics or lyrics.get("deleted_at"):
        raise HTTPException(status_code=404, detail="연결할 가사를 찾을 수 없습니다.")
    if lyrics["song_id"] != rec["song_id"]:
        raise HTTPException(status_code=400, detail="가사와 기록의 곡이 일치하지 않습니다.")

    # 원자적 선점 (동시/중복 연결 방지). 이미 registered 면 중단.
    if not await repo.claim_for_register(import_id, admin["id"]):
        raise HTTPException(status_code=400, detail="이미 정식 등록된 기록입니다.")

    await lyrics_repo.set_verified(data.lyrics_id, True)
    try:
        linked = await get_songbook_repository().autolink_song_lyrics(rec["song_id"], data.lyrics_id)
        if linked:
            logger.info(f"자동 가사 편집 등록 후 노래책 연결: lyrics_id={data.lyrics_id}, {linked}건")
    except Exception as e:
        logger.warning(f"노래책 자동 연결 실패 (lyrics_id={data.lyrics_id}): {e}")

    await repo.set_registered_lyrics(import_id, data.lyrics_id)

    await log_audit(
        actor_id=admin["id"],
        action=AuditAction.LYRICS_IMPORT_REGISTER,
        target_type="lyrics",
        target_id=data.lyrics_id,
        details={"import_id": import_id, "song_id": rec["song_id"], "via": "editor"},
        ip_address=get_client_ip(request),
    )
    return {"success": True, "lyrics_id": data.lyrics_id}


@router.post("/auto-lyrics/{import_id}/register", dependencies=[Depends(verify_csrf)])
async def register_auto_lyrics(
    import_id: int,
    request: Request,
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """자동 가사 기록을 정식 가사(song_lyrics, is_verified=1)로 등록.

    맞춘 오프셋을 타임스탬프에 반영하고, 관리자 소유(owner_id=NULL)·공개 가사로 만든 뒤
    노래책에 자동 연결한다.
    """
    rec = await repo.get_import(import_id)
    if not rec:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if rec["status"] == "registered":
        raise HTTPException(status_code=400, detail="이미 정식 등록된 기록입니다.")
    if not rec.get("lyrics_data"):
        raise HTTPException(status_code=400, detail="등록할 가사 데이터가 없습니다.")

    # 가사 생성 전에 기록을 원자적으로 선점 → 동시 요청 중복 등록 방지
    if not await repo.claim_for_register(import_id, admin["id"]):
        raise HTTPException(status_code=400, detail="이미 정식 등록된 기록입니다.")

    baked = _bake_offset(rec["lyrics_data"], rec.get("offset_ms") or 0)

    # 관리자 등록 = owner_id NULL, 공개, 검증됨
    lyrics_id = await lyrics_repo.create_lyrics(
        owner_id=None,
        song_id=rec["song_id"],
        mr_youtube_video_id=rec.get("mr_youtube_video_id"),
        lyrics_data=baked,
        title=REGISTERED_TITLE,
        visibility="public",
    )
    await lyrics_repo.set_verified(lyrics_id, True)

    # 노래책 자동 연결 (가사 없던 수록곡에 붙임)
    try:
        linked = await get_songbook_repository().autolink_song_lyrics(rec["song_id"], lyrics_id)
        if linked:
            logger.info(f"자동 가사 정식 등록 후 노래책 연결: lyrics_id={lyrics_id}, {linked}건")
    except Exception as e:
        logger.warning(f"노래책 자동 연결 실패 (lyrics_id={lyrics_id}): {e}")

    await repo.set_registered_lyrics(import_id, lyrics_id)

    await log_audit(
        actor_id=admin["id"],
        action=AuditAction.LYRICS_IMPORT_REGISTER,
        target_type="lyrics",
        target_id=lyrics_id,
        details={
            "import_id": import_id,
            "song_id": rec["song_id"],
            "source": rec.get("source"),
            "source_id": rec.get("source_id"),
            "offset_ms": rec.get("offset_ms"),
        },
        ip_address=get_client_ip(request),
    )
    return {"success": True, "lyrics_id": lyrics_id}


@router.post("/auto-lyrics/{import_id}/ignore", dependencies=[Depends(verify_csrf)])
async def ignore_auto_lyrics(
    import_id: int,
    request: Request,
    admin=Depends(require_admin),
    repo: AutoLyricsRepository = Depends(get_auto_lyrics_repository),
):
    """자동 가사 기록을 '무시' 처리 (목록에서 숨김)."""
    rec = await repo.get_import(import_id)
    if not rec:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    if rec["status"] == "registered":
        raise HTTPException(status_code=400, detail="이미 정식 등록된 기록입니다.")

    await repo.mark_ignored(import_id, admin["id"])
    await log_audit(
        actor_id=admin["id"],
        action=AuditAction.LYRICS_IMPORT_IGNORE,
        target_type="auto_lyrics_import",
        target_id=import_id,
        ip_address=get_client_ip(request),
    )
    return {"success": True}
