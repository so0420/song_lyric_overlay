from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from app.core.auth import get_current_user_api
from typing import Optional
from app.services.song_service import SongService, get_song_service
from app.integrations.ITunes_search_api import itunes_api
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler

router = APIRouter()

@router.get("/search")
async def search_songs(q: str, limit: int = 20):
    """iTunes API를 사용하여 노래 검색"""
    if not q or len(q.strip()) < 1:
        return []

    try:
        results = await itunes_api.search(term=q, limit=min(limit, 100))

        # 프론트엔드에서 기대하는 형식으로 변환
        formatted_results = []
        for item in results:
            song_external_id = f"it_{item['track_id']}"

            formatted_results.append({
                "id": item['track_id'],
                "song_external_id": song_external_id,
                "title": item['track_name'],
                "artist_name": item['artist_name'],
                "cover_image_url": item['artwork_url'],
                "lyrics_count": 0  # 기본값, 실제로는 DB에서 조회 필요
            })

        # 가사 개수 조회 (DB에 등록된 곡들만)
        if formatted_results:
            external_ids = [r['song_external_id'] for r in formatted_results]
            format_strings = ','.join(['%s'] * len(external_ids))
            query = f"""
                SELECT s.song_external_id, COUNT(l.id) as cnt
                FROM songs s
                JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1
                WHERE s.song_external_id IN ({format_strings})
                GROUP BY s.song_external_id
            """
            counts = await db_handler.fetch_all(query, tuple(external_ids))
            count_map = {c['song_external_id']: c['cnt'] for c in counts}

            for r in formatted_results:
                r['lyrics_count'] = count_map.get(r['song_external_id'], 0)

        return formatted_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/custom")
async def register_custom_song(
    title: str = Form(...),
    artist: str = Form(...),
    image: Optional[UploadFile] = File(None),
    service: SongService = Depends(get_song_service),
    user=Depends(get_current_user_api)
):
    return await service.create_custom_song(
        title=title,
        artist=artist,
        image=image,
        owner_id=user['id']
    )

@router.get("/info")
async def get_song_info(
    external_id: str,
    service: SongService = Depends(get_song_service)
):
    """external_id로 곡 정보 조회"""
    song = await service.get_song_info(external_id)

    if song:
        return song

    if external_id.startswith("it_"):
        raise HTTPException(status_code=404, detail="Song not found in local DB. Please add it to songbook first or search again.")

    raise HTTPException(status_code=404, detail="Song not found")

@router.get("/search/custom")
async def search_custom_songs(q: str, limit: int = 20):
    """Meilisearch를 사용하여 커스텀 노래 검색"""
    if not q or len(q.strip()) < 1:
        return []

    try:
        results = await meilisearch_handler.search(
            query=q,
            limit=min(limit, 100),
            attributes_to_search_on=["title", "singer"]
        )

        # 프론트엔드에서 기대하는 형식으로 변환
        formatted_results = []
        for item in results:
            formatted_results.append({
                "id": item.get('id'),
                "song_external_id": item.get('id'),
                "title": item.get('title', ''),
                "artist_name": item.get('singer', ''),
                "cover_image_url": item.get('image_url'),
                "is_custom": True
            })

        # 가사 개수 조회
        if formatted_results:
            external_ids = [r['song_external_id'] for r in formatted_results]
            format_strings = ','.join(['%s'] * len(external_ids))
            query = f"""
                SELECT s.song_external_id, COUNT(l.id) as cnt
                FROM songs s
                JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1
                WHERE s.song_external_id IN ({format_strings})
                GROUP BY s.song_external_id
            """
            counts = await db_handler.fetch_all(query, tuple(external_ids))
            count_map = {c['song_external_id']: c['cnt'] for c in counts}

            for r in formatted_results:
                r['lyrics_count'] = count_map.get(r['song_external_id'], 0)

        return formatted_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
