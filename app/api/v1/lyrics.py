from fastapi import APIRouter, Depends, Query, HTTPException
from app.core.auth import get_current_user_api, get_current_user
from app.database.lyrics_repository import get_lyrics_repository, LyricsRepository
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

router = APIRouter()

class LyricsCreateSchema(BaseModel):
    song_id: int
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str # JSON string or structured data

class LyricsUpdateSchema(BaseModel):
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str

@router.get("/search")
async def search_lyrics(
    q: str = Query(..., min_length=1),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """공개된 가사가 있는 노래 검색"""
    return await repo.search_songs_with_lyrics(q)

@router.get("/search/custom")
async def search_custom_lyrics(
    q: str = Query(..., min_length=1),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """공개된 가사가 있는 커스텀 노래 검색"""
    return await repo.search_custom_songs_with_lyrics(q)

@router.get("/")
async def get_available_lyrics(
    song_external_id: str = Query(...),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """특정 곡에 대해 사용 가능한 가사 목록 조회"""
    return await repo.get_lyrics_by_external_id(song_external_id)

@router.get("/my")
async def get_my_lyrics(
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """자신이 작성한 가사 목록 조회"""
    return await repo.get_my_lyrics(user['id'])

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

@router.post("/")
async def create_lyrics(
    data: LyricsCreateSchema,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 작성 저장"""
    # 가사 이름 중복 체크 (내 가사들 중에서)
    if data.title:
        is_duplicate = await repo.check_title_duplicate(user['id'], data.song_id, data.title)
        if is_duplicate:
            raise HTTPException(status_code=400, detail="같은 노래에 동일한 제목의 가사가 이미 존재합니다.")

    lyrics_id = await repo.create_lyrics(
        owner_id=user['id'],
        song_id=data.song_id,
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data
    )
    return {"id": lyrics_id}

@router.patch("/{lyrics_id}")
async def update_lyrics(
    lyrics_id: int,
    data: LyricsUpdateSchema,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 수정"""
    # 가사 이름 중복 체크 (내 가사들 중에서, 자기 자신 제외)
    if data.title:
        is_duplicate = await repo.check_title_duplicate(user['id'], None, data.title, exclude_id=lyrics_id)
        if is_duplicate:
            raise HTTPException(status_code=400, detail="같은 노래에 동일한 제목의 가사가 이미 존재합니다.")

    await repo.update_lyrics(
        lyrics_id=lyrics_id,
        owner_id=user['id'],
        title=data.title,
        mr_youtube_video_id=data.mr_youtube_video_id,
        lyrics_data=data.lyrics_data
    )
    return {"success": True}

@router.delete("/{lyrics_id}")
async def delete_lyrics(
    lyrics_id: int,
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """가사 삭제"""
    await repo.delete_lyrics(lyrics_id, user['id'])
    return {"success": True}

# 즐겨찾기 API
@router.post("/favorites/{lyrics_id}")
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

@router.delete("/favorites/{lyrics_id}")
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
    user=Depends(get_current_user_api),
    repo: LyricsRepository = Depends(get_lyrics_repository)
):
    """내 즐겨찾기 가사 목록 조회"""
    return await repo.get_my_favorites(user['id'])
