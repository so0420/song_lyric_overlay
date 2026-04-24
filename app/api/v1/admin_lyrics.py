"""관리자 전용: 가사 공개 범위 및 화이트리스트 관리 API."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional

from app.core.auth import require_admin
from app.database.lyrics_repository import get_lyrics_repository, LyricsRepository
from app.schemas.lyrics import VisibilityPatchSchema, WhitelistPutSchema
from app.utils.audit import log_audit, get_client_ip, AuditAction
from app.utils.csrf import verify_csrf

router = APIRouter()


@router.get("/users/search")
async def search_users(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    admin=Depends(require_admin),
    repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """화이트리스트 UI 자동완성: 이름/이메일 LIKE 검색"""
    return await repo.search_users(q, limit=limit)


@router.get("/lyrics/{lyrics_id}/visibility")
async def get_visibility(
    lyrics_id: int,
    admin=Depends(require_admin),
    repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """가사의 현재 visibility 와 화이트리스트 조회"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")
    whitelist = await repo.get_whitelist(lyrics_id)
    return {
        "lyrics_id": lyrics_id,
        "visibility": lyrics["visibility"],
        "whitelist": whitelist,
    }


@router.patch("/lyrics/{lyrics_id}/visibility", dependencies=[Depends(verify_csrf)])
async def patch_visibility(
    lyrics_id: int,
    data: VisibilityPatchSchema,
    request: Request,
    admin=Depends(require_admin),
    repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """visibility 변경 (관리자 전용)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")

    old = lyrics["visibility"]
    if old == data.visibility:
        return {"success": True, "visibility": data.visibility, "changed": False}

    updated = await repo.update_visibility(lyrics_id, data.visibility)
    if not updated:
        raise HTTPException(status_code=400, detail="visibility 변경 실패")

    await log_audit(
        actor_id=admin["id"],
        action=AuditAction.LYRICS_VISIBILITY_CHANGE,
        target_type="lyrics",
        target_id=lyrics_id,
        details={"old": old, "new": data.visibility},
        ip_address=get_client_ip(request),
    )

    return {"success": True, "visibility": data.visibility, "changed": True}


@router.put("/lyrics/{lyrics_id}/whitelist", dependencies=[Depends(verify_csrf)])
async def put_whitelist(
    lyrics_id: int,
    data: WhitelistPutSchema,
    request: Request,
    admin=Depends(require_admin),
    repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """화이트리스트 전체 교체 (관리자 전용)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")

    # 중복 제거
    unique_ids = list(dict.fromkeys(data.user_ids))

    try:
        diff = await repo.replace_whitelist(lyrics_id, unique_ids, granted_by=admin["id"])
    except Exception as e:
        # FK 위반 등 (존재하지 않는 user_id)
        raise HTTPException(status_code=400, detail=f"화이트리스트 저장 실패: {e}") from e

    if diff["added"] or diff["removed"]:
        await log_audit(
            actor_id=admin["id"],
            action=AuditAction.LYRICS_WHITELIST_CHANGE,
            target_type="lyrics",
            target_id=lyrics_id,
            details={"added": diff["added"], "removed": diff["removed"]},
            ip_address=get_client_ip(request),
        )

    whitelist = await repo.get_whitelist(lyrics_id)
    return {"success": True, "whitelist": whitelist, "diff": diff}
