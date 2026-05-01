from fastapi import APIRouter, Depends, Query, HTTPException, Request
from app.core.auth import get_current_user_api, get_current_user
from app.core.lyrics_access import can_view_lyrics
from app.database.lyrics_repository import get_lyrics_repository, LyricsRepository
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.integrations.itunes_search import search_itunes_cached
from app.api.v1.songs import register_itunes_results
from app.schemas.lyrics import LyricsCreateSchema, LyricsUpdateSchema, LyricsMemoSchema
from app.schemas.common import IdResponse
from app.utils.csrf import verify_csrf
from app.utils.log import logger

router = APIRouter()

# 페이지네이션 기본값
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _user_ctx(user):
    """user dict → (user_id, is_admin). 익명이면 (None, False)."""
    if not user:
        return None, False
    return user.get("id"), bool(user.get("is_admin"))


async def _collect_search_candidate_ids(q: str) -> list:
    """iTunes + Meilisearch 검색으로 후보 song_external_id 수집 (중복 제거, 입력 순서 유지).

    iTunes 는 항상 호출(캐시되어 있음)해서 페이지네이션 사이에 후보가 달라지지 않게 한다.
    DB/Meilisearch 등록은 캐시 미스(=라이브 호출) 일 때만 한 번 수행한다.
    """
    candidate_ids: list[str] = []
    seen: set[str] = set()

    def add(eid):
        if eid and eid not in seen:
            candidate_ids.append(eid)
            seen.add(eid)

    try:
        itunes_results, from_cache = await search_itunes_cached(term=q, limit=100)
        if itunes_results:
            if not from_cache:
                await register_itunes_results(itunes_results)
            for r in itunes_results:
                add(f"custom_it_{r['track_id']}")
    except Exception as e:
        logger.warning(f"iTunes search failed: {e}")

    try:
        ms_results = await meilisearch_handler.search(
            query=q, offset=0, limit=200,
            attributes_to_search_on=["title", "singer"],
        )
        if not ms_results.get("hits") and " " in q:
            ms_results = await meilisearch_handler.search(
                query=q.replace(" ", ""), offset=0, limit=200,
                attributes_to_search_on=["title", "singer"],
            )
        for hit in ms_results.get("hits", []):
            add(hit.get("id"))
    except Exception as e:
        logger.warning(f"Meilisearch failed: {e}")

    return candidate_ids


@router.get("/songs")
async def get_songs_with_lyrics(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    type: str = Query("all", pattern="^(all|custom)$"),
    q: str = Query(None),
    sort: str = Query("recent", pattern="^(recent|title_asc|title_desc|artist_asc|artist_desc)$"),
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """접근 가능한 가사가 있는 모든 노래 목록 조회 (페이지네이션, 검색, 정렬 지원).

    검색어(q)가 있으면 iTunes/Meilisearch 로 후보를 보강해 DB LIKE 가 놓치는 곡도 잡는다.
    """
    user_id, is_admin = _user_ctx(user)
    extra_ids: list[str] = []
    if q:
        extra_ids = await _collect_search_candidate_ids(q)
    return await repo.get_all_songs_with_lyrics(
        user_id=user_id, is_admin=is_admin,
        offset=offset, limit=limit, song_type=type, search=q, sort=sort,
        extra_external_ids=extra_ids or None,
    )


@router.get("/search")
async def search_lyrics(
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """접근 가능한 가사가 있는 노래 검색 (iTunes/Meilisearch 보강).

    /lyrics/songs 와 동일한 경로(get_all_songs_with_lyrics + extra_external_ids)를 사용해
    SQL 단계에서 정렬·페이지네이션이 일어나 결과가 결정적이 되도록 한다.
    """
    user_id, is_admin = _user_ctx(user)
    extra_ids = await _collect_search_candidate_ids(q)
    return await repo.get_all_songs_with_lyrics(
        user_id=user_id, is_admin=is_admin,
        offset=offset, limit=limit, search=q, sort="recent",
        extra_external_ids=extra_ids or None,
    )


@router.get("/")
async def get_available_lyrics(
    song_external_id: str = Query(...),
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """특정 곡에 대해 사용 가능한 가사 목록 조회"""
    user_id, is_admin = _user_ctx(user)
    return await repo.get_lyrics_by_external_id(song_external_id, user_id=user_id, is_admin=is_admin)


@router.get("/my")
async def get_my_lyrics(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """자신이 작성한 가사 목록 조회 (visibility 무관, 본인 것 전부)"""
    items, total = await repo.get_my_lyrics(user['id'], offset=offset, limit=limit)
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total
    }


@router.get("/song/{song_id}")
async def get_lyrics_by_song(
    song_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """특정 노래의 가사 목록 조회 (즐겨찾기 정보 포함)"""
    return await repo.get_lyrics_by_song_id_with_favorites(
        song_id, user['id'], is_admin=bool(user.get('is_admin')),
    )


@router.get("/{lyrics_id}")
async def get_lyrics_detail(
    lyrics_id: int,
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 상세 조회 (visibility 권한 체크)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    if not await can_view_lyrics(lyrics, user, repo):
        if not user:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        raise HTTPException(status_code=403, detail="이 가사에 접근할 권한이 없습니다.")
    return lyrics


@router.post("/", dependencies=[Depends(verify_csrf)])
async def create_lyrics(
    request: Request,
    data: LyricsCreateSchema,
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 작성 저장 (비로그인 시 익명으로 저장)"""
    owner_id = user['id'] if user else None
    is_admin = bool(user and user.get('is_admin'))

    # 가사 이름 중복 체크 (로그인 사용자만)
    if owner_id and data.title:
        is_duplicate = await repo.check_title_duplicate(owner_id, data.song_id, data.title)
        if is_duplicate:
            raise HTTPException(status_code=400, detail="같은 노래에 동일한 제목의 가사가 이미 존재합니다.")

    # 관리자만 visibility 지정 가능, 그 외는 기본값(public)
    visibility = data.visibility if (is_admin and data.visibility) else "public"

    lyrics_id = await repo.create_lyrics(
        owner_id=owner_id,
        song_id=data.song_id,
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data,
        visibility=visibility,
    )

    # 익명 사용자: 세션에 생성한 가사 ID 기록
    if not owner_id:
        anon_ids = request.session.get('anon_lyrics_ids', [])
        anon_ids.append(lyrics_id)
        request.session['anon_lyrics_ids'] = anon_ids

    return IdResponse(id=lyrics_id)


@router.patch("/{lyrics_id}", dependencies=[Depends(verify_csrf)])
async def update_lyrics(
    request: Request,
    lyrics_id: int,
    data: LyricsUpdateSchema,
    user=Depends(get_current_user),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 수정 (비로그인 시 본인이 생성한 익명 가사만 수정 가능)"""
    owner_id = user['id'] if user else None
    is_admin = bool(user and user.get('is_admin'))

    # 익명 사용자: 세션에 기록된 가사만 수정 가능
    if not owner_id:
        anon_ids = request.session.get('anon_lyrics_ids', [])
        if lyrics_id not in anon_ids:
            raise HTTPException(status_code=403, detail="수정 권한이 없습니다.")

    # 가사 이름 중복 체크 (로그인 사용자만)
    if owner_id and data.title:
        is_duplicate = await repo.check_title_duplicate(owner_id, None, data.title, exclude_id=lyrics_id)
        if is_duplicate:
            raise HTTPException(status_code=400, detail="같은 노래에 동일한 제목의 가사가 이미 존재합니다.")

    updated = await repo.update_lyrics(
        lyrics_id=lyrics_id,
        owner_id=owner_id,
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data
    )
    if not updated:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없거나 수정 권한이 없습니다.")

    # 관리자가 visibility 동시에 변경하려 한 경우 별도 반영
    if is_admin and data.visibility:
        await repo.update_visibility(lyrics_id, data.visibility)

    return {"success": True}


@router.delete("/{lyrics_id}", dependencies=[Depends(verify_csrf)])
async def delete_lyrics(
    lyrics_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 삭제"""
    await repo.delete_lyrics(lyrics_id, user['id'])
    return {"success": True}


# 즐겨찾기 API
@router.post("/favorites/{lyrics_id}", dependencies=[Depends(verify_csrf)])
async def add_favorite(
    lyrics_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 즐겨찾기 추가 (visibility 권한 필요)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")
    if not await can_view_lyrics(lyrics, user, repo):
        raise HTTPException(status_code=403, detail="이 가사에 접근할 권한이 없습니다.")

    success = await repo.add_favorite(user['id'], lyrics_id)
    if not success:
        raise HTTPException(status_code=400, detail="이미 즐겨찾기에 추가되었습니다.")
    return {"success": True}


@router.delete("/favorites/{lyrics_id}", dependencies=[Depends(verify_csrf)])
async def remove_favorite(
    lyrics_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 즐겨찾기 제거"""
    await repo.remove_favorite(user['id'], lyrics_id)
    return {"success": True}


# 메모 API
@router.get("/{lyrics_id}/memo")
async def get_memo(
    lyrics_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사에 대한 내 메모 조회 (visibility 권한 필요)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")
    if not await can_view_lyrics(lyrics, user, repo):
        raise HTTPException(status_code=403, detail="이 가사에 접근할 권한이 없습니다.")

    memo = await repo.get_memo(user['id'], lyrics_id)
    return {"memo": memo['memo'] if memo else "", "updated_at": memo['updated_at'] if memo else None}


@router.put("/{lyrics_id}/memo", dependencies=[Depends(verify_csrf)])
async def save_memo(
    lyrics_id: int,
    data: LyricsMemoSchema,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사에 대한 내 메모 저장 (visibility 권한 필요)"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="가사를 찾을 수 없습니다.")
    if not await can_view_lyrics(lyrics, user, repo):
        raise HTTPException(status_code=403, detail="이 가사에 접근할 권한이 없습니다.")

    if data.memo.strip():
        await repo.save_memo(user['id'], lyrics_id, data.memo.strip())
    else:
        await repo.delete_memo(user['id'], lyrics_id)
    return {"success": True}


@router.get("/favorites/my")
async def get_my_favorites(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """내 즐겨찾기 가사 목록 조회 (현재 접근 가능한 가사만)"""
    items, total = await repo.get_my_favorites(
        user['id'], is_admin=bool(user.get('is_admin')), offset=offset, limit=limit,
    )
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total
    }
