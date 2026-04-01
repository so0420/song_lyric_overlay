from fastapi import APIRouter, Depends, Query, HTTPException, Request
from app.core.auth import get_current_user_api, get_current_user
from app.database.lyrics_repository import get_lyrics_repository, LyricsRepository
from app.schemas.lyrics import LyricsCreateSchema, LyricsUpdateSchema
from app.schemas.common import IdResponse
from app.utils.csrf import verify_csrf

router = APIRouter()

# 페이지네이션 기본값
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

@router.get("/songs")
async def get_songs_with_lyrics(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    type: str = Query("all", pattern="^(all|itunes|custom)$"),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """공개된 가사가 있는 모든 노래 목록 조회 (페이지네이션 지원)"""
    return await repo.get_all_songs_with_lyrics(offset=offset, limit=limit, song_type=type)

@router.get("/search")
async def search_lyrics(
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """공개된 가사가 있는 노래 검색 (음원 + 커스텀 분리, 페이지네이션 지원)"""
    results = await repo.search_all_songs_with_lyrics(q, offset=offset, limit=limit)
    return results

@router.get("/")
async def get_available_lyrics(
    song_external_id: str = Query(...),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """특정 곡에 대해 사용 가능한 가사 목록 조회"""
    return await repo.get_lyrics_by_external_id(song_external_id)

@router.get("/my")
async def get_my_lyrics(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """자신이 작성한 가사 목록 조회 (페이지네이션 지원)"""
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
    return await repo.get_lyrics_by_song_id_with_favorites(song_id, user['id'])

@router.get("/{lyrics_id}")
async def get_lyrics_detail(
    lyrics_id: int,
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 상세 조회"""
    lyrics = await repo.get_lyrics_by_id(lyrics_id)
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
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

    # 가사 이름 중복 체크 (로그인 사용자만)
    if owner_id and data.title:
        is_duplicate = await repo.check_title_duplicate(owner_id, data.song_id, data.title)
        if is_duplicate:
            raise HTTPException(status_code=400, detail="같은 노래에 동일한 제목의 가사가 이미 존재합니다.")

    lyrics_id = await repo.create_lyrics(
        owner_id=owner_id,
        song_id=data.song_id,
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data
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

    await repo.update_lyrics(
        lyrics_id=lyrics_id,
        owner_id=owner_id,
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data
    )
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
    """가사 즐겨찾기 추가"""
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

@router.get("/favorites/my")
async def get_my_favorites(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """내 즐겨찾기 가사 목록 조회 (페이지네이션 지원)"""
    items, total = await repo.get_my_favorites(user['id'], offset=offset, limit=limit)
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < total
    }
