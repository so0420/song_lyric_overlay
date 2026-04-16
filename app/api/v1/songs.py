from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Request
from app.core.auth import get_current_user, get_current_user_api
from typing import Optional
from app.services.song_service import SongService, get_song_service
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.lyrics_repository import get_lyrics_repository
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS
from app.utils.log import logger

router = APIRouter()

@router.get("/search")
@limiter.limit(RATE_LIMITS["search"])
async def search_songs(request: Request, q: str, offset: int = 0, limit: int = 20):
    """Meilisearch를 사용하여 노래 검색 (페이지네이션 지원, DB 폴백)"""
    if not q or len(q.strip()) < 1:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

    if len(q) > 200:
        raise HTTPException(status_code=400, detail="검색어는 200자를 초과할 수 없습니다.")

    formatted_results = []
    total = 0
    use_fallback = False

    try:
        # Meilisearch 검색 시도
        results = await meilisearch_handler.search(
            query=q,
            offset=offset,
            limit=min(limit, 100),
            attributes_to_search_on=["title", "singer"]
        )

        for item in results.get('hits', []):
            formatted_results.append({
                "id": item.get('id'),
                "song_external_id": item.get('id'),
                "title": item.get('title', ''),
                "artist_name": item.get('singer', ''),
                "cover_image_url": item.get('image_url'),
            })

        total = results.get('estimatedTotalHits', len(formatted_results))

        # 가사 제목으로 추가 검색 (Meilisearch 결과에 없는 곡 보완)
        lyrics_repo = get_lyrics_repository()
        lyrics_title_matches = await lyrics_repo.find_songs_by_lyrics_title(q)
        existing_ext_ids = {r['song_external_id'] for r in formatted_results}
        added_count = 0
        for item in lyrics_title_matches:
            ext_id = item['song_external_id']
            if ext_id not in existing_ext_ids:
                formatted_results.append({
                    "id": ext_id,
                    "song_external_id": ext_id,
                    "title": item['title'] or '',
                    "artist_name": item['artist_name'] or '',
                    "cover_image_url": item['cover_image_url'],
                })
                existing_ext_ids.add(ext_id)
                added_count += 1
        total += added_count

    except Exception as e:
        # Meilisearch 실패 시 DB 폴백
        use_fallback = True
        logger.warning(f"Meilisearch search failed, using DB fallback: {e}")
        search_pattern = f"%{q}%"
        fallback_query = """
            SELECT DISTINCT
                s.song_external_id as id,
                s.title,
                a.name as singer,
                s.cover_image_url as image_url
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
            ORDER BY s.title ASC
            LIMIT %s OFFSET %s
        """
        fallback_results = await db_handler.fetch_all(
            fallback_query, (search_pattern, search_pattern, search_pattern, limit, offset)
        )

        for item in fallback_results:
            formatted_results.append({
                "id": item.get('id'),
                "song_external_id": item.get('id'),
                "title": item.get('title', ''),
                "artist_name": item.get('singer', ''),
                "cover_image_url": item.get('image_url'),
            })

        count_query = """
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
        """
        count_result = await db_handler.fetch_one(count_query, (search_pattern, search_pattern, search_pattern))
        total = count_result['total'] if count_result else 0

    # 가사 개수 조회 → 가사 있는 노래 우선 정렬
    if formatted_results:
        lyrics_repo = get_lyrics_repository()
        external_ids = [r['song_external_id'] for r in formatted_results]
        count_map = await lyrics_repo.get_lyrics_counts(external_ids)

        for r in formatted_results:
            r['lyrics_count'] = count_map.get(r['song_external_id'], 0)
        formatted_results.sort(key=lambda r: r['lyrics_count'], reverse=True)

    return {
        "items": formatted_results,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(formatted_results) < total,
        "fallback": use_fallback
    }

@router.post("/custom", dependencies=[Depends(verify_csrf)])
async def register_custom_song(
    title: str = Form(...),
    artist: str = Form(...),
    image: Optional[UploadFile] = File(None),
    service: SongService = Depends(get_song_service),
    user=Depends(get_current_user)
):
    return await service.create_custom_song(
        title=title,
        artist=artist,
        image=image,
        owner_id=user['id'] if user else None
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
    raise HTTPException(status_code=404, detail="Song not found")
