"""스트리머(노래책 프로필) API

- 공개 검색: 승인된 스트리머만 노출 (공개 노출 필터는 repository 에서 처리)
- 프로필 생성/수정/삭제: 오버레이 사용 승인된 유저만 (오버레이 승인 = 노래책 승인)
"""
import re
import uuid
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import get_current_user_api
from app.schemas.users import CurrentUserSchema
from app.schemas.songbook import StreamerProfileUpdateSchema
from app.database.access_request_repository import get_access_request_repository
from app.database.streamer_repository import StreamerRepository, get_streamer_repository
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS

router = APIRouter()

# slug 자동 생성용: 허용 문자(소문자/숫자/한글/_/-) 외 제거
_SLUG_DISALLOWED_RE = re.compile(r"[^a-z0-9가-힣_-]")


async def require_approved_user(user: CurrentUserSchema = Depends(get_current_user_api)) -> CurrentUserSchema:
    """오버레이/노래책 사용 승인된 유저만 통과 (관리자 자동 승인)"""
    repo = get_access_request_repository()
    if not await repo.is_user_approved(user["id"]):
        raise HTTPException(status_code=403, detail="노래책 기능 사용 승인이 필요합니다.")
    return user


def _serialize_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """프로필 row → 응답용 dict (외부 UUID 를 id 로 노출, JSON 컬럼은 repository 에서 이미 파싱됨)"""
    return {
        "id": profile["streamer_id"],
        "name": profile["name"],
        "slug": profile["slug"],
        "description": profile.get("description"),
        "social_links": profile.get("social_links", []),
        "tags": profile.get("tags", []),
        "picture": profile.get("picture"),
        "request_enabled": bool(profile.get("request_enabled")),
        "request_web_enabled": bool(profile.get("request_web_enabled")),
        "request_auto_playlist": bool(profile.get("request_auto_playlist")),
        "request_chat_enabled": bool(profile.get("request_chat_enabled")),
        "request_donation_enabled": bool(profile.get("request_donation_enabled")),
        "default_price_cheese": profile.get("default_price_cheese") or 0,
    }


def _normalize_slug_base(name: Optional[str]) -> str:
    """유저 이름으로 slug 기본값 생성: 소문자화, 공백→하이픈, 허용문자 외 제거, 2자 미만이면 'singer'"""
    base = (name or "").strip().lower()
    base = re.sub(r"\s+", "-", base)
    base = _SLUG_DISALLOWED_RE.sub("", base)
    base = base[:26]  # 중복 suffix(-N) 붙일 여유 확보 (slug 최대 30자)
    if len(base) < 2:
        base = "singer"
    return base


async def _generate_unique_slug(repo: StreamerRepository, name: Optional[str]) -> str:
    """중복되지 않는 slug 생성 (base, base-2, base-3, ...)"""
    base = _normalize_slug_base(name)
    slug = base
    suffix = 2
    while await repo.is_slug_taken(slug):
        if suffix > 100:
            # 비정상적으로 중복이 많으면 UUID 조각으로 강제 유일화
            return f"{base[:23]}-{uuid.uuid4().hex[:6]}"
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@router.get("/")
@limiter.limit(RATE_LIMITS["search"])
async def search_streamers(
    request: Request,
    q: Optional[str] = Query(None, max_length=100, description="검색어 (이름/slug)"),
    limit: int = Query(20, ge=1, le=50),
    repo: StreamerRepository = Depends(get_streamer_repository),
):
    """공개 스트리머 검색 (승인된 스트리머만 노출)"""
    rows = await repo.search_public(q=q, limit=limit)
    items = [
        {
            "id": row["streamer_id"],
            "name": row["name"],
            "slug": row["slug"],
            "description": row.get("description"),
            "tags": row.get("tags", []),
            "picture": row.get("picture"),
        }
        for row in rows
    ]
    return {"items": items}


@router.get("/me")
async def get_my_streamer_profile(
    user: CurrentUserSchema = Depends(get_current_user_api),
    repo: StreamerRepository = Depends(get_streamer_repository),
):
    """내 노래책 프로필 조회 (프로필 유무/승인 여부 포함)"""
    access_repo = get_access_request_repository()
    approved = await access_repo.is_user_approved(user["id"])

    profile = await repo.get_by_user_id(user["id"])
    return {
        "has_profile": profile is not None,
        "approved": approved,
        "profile": _serialize_profile(profile) if profile else None,
    }


@router.post("/", dependencies=[Depends(verify_csrf)])
async def create_streamer_profile(
    user: CurrentUserSchema = Depends(require_approved_user),
    repo: StreamerRepository = Depends(get_streamer_repository),
):
    """노래책 프로필 생성 (slug 는 유저 이름 기반 자동 생성)"""
    existing = await repo.get_by_user_id(user["id"])
    if existing:
        raise HTTPException(status_code=400, detail="이미 노래책 프로필이 있습니다.")

    slug = await _generate_unique_slug(repo, user.get("name"))
    await repo.create_profile(user["id"], slug)

    profile = await repo.get_by_user_id(user["id"])
    if not profile:
        raise HTTPException(status_code=500, detail="프로필 생성에 실패했습니다.")

    return {
        "has_profile": True,
        "approved": True,
        "profile": _serialize_profile(profile),
    }


@router.patch("/me", dependencies=[Depends(verify_csrf)])
async def update_my_streamer_profile(
    payload: StreamerProfileUpdateSchema,
    user: CurrentUserSchema = Depends(require_approved_user),
    repo: StreamerRepository = Depends(get_streamer_repository),
):
    """내 노래책 프로필 수정 (전달된 필드만 갱신)"""
    profile = await repo.get_by_user_id(user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="노래책 프로필이 없습니다.")

    # 명시적으로 전달된 필드만 반영 (nested 모델은 dict 로 변환됨)
    fields = payload.model_dump(exclude_unset=True)

    # slug 는 null 로 비울 수 없음 — 변경 요청일 때만 중복 검사
    if "slug" in fields:
        if fields["slug"] is None:
            fields.pop("slug")
        elif await repo.is_slug_taken(fields["slug"], exclude_user_id=user["id"]):
            raise HTTPException(status_code=400, detail="이미 사용 중인 주소입니다.")

    if fields:
        # social_links/tags 의 JSON 직렬화는 repository 에서 처리
        await repo.update_profile(user["id"], **fields)

    updated = await repo.get_by_user_id(user["id"])
    return {"success": True, "profile": _serialize_profile(updated)}


@router.delete("/me", dependencies=[Depends(verify_csrf)])
async def delete_my_streamer_profile(
    user: CurrentUserSchema = Depends(get_current_user_api),
    repo: StreamerRepository = Depends(get_streamer_repository),
):
    """노래책 프로필 삭제 (하드 삭제 — CASCADE 로 수록곡/신청도 함께 삭제)"""
    await repo.delete_profile(user["id"])
    return {"success": True}
