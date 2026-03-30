from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Request
from app.core.auth import get_current_user_api
from typing import Optional
from app.services.song_service import SongService, get_song_service
from app.integrations.itunes_search_api import itunes_api
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
    """iTunes API를 사용하여 노래 검색 (페이지네이션 지원)"""
    if not q or len(q.strip()) < 1:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

    # 검색어 길이 제한 (DoS 방지)
    if len(q) > 200:
        raise HTTPException(status_code=400, detail="검색어는 200자를 초과할 수 없습니다.")

    try:
        # iTunes API는 offset을 지원하지 않으므로 최대 100개까지 한번에 가져옴
        # 첫 요청 시 100개 가져와서 캐싱하면 좋지만, 간단히 항상 100개 요청
        fetch_limit = 100
        results = await itunes_api.search(term=q, limit=fetch_limit)

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

        # 가사 제목으로 추가 검색 (iTunes 결과에 없는 곡을 맨 앞에 배치)
        lyrics_repo = get_lyrics_repository()
        lyrics_title_matches = await lyrics_repo.find_songs_by_lyrics_title(q, 'it_')
        existing_ext_ids = {r['song_external_id'] for r in formatted_results}
        prepend_results = []
        for item in lyrics_title_matches:
            ext_id = item['song_external_id']
            if ext_id not in existing_ext_ids:
                prepend_results.append({
                    "id": item['id'],
                    "song_external_id": ext_id,
                    "title": item['title'] or '',
                    "artist_name": item['artist_name'] or '',
                    "cover_image_url": item['cover_image_url'] or '',
                    "lyrics_count": 0
                })
                existing_ext_ids.add(ext_id)
        formatted_results = prepend_results + formatted_results

        # 페이지네이션 적용 (가사 개수 조회 전에 슬라이싱)
        total = len(formatted_results)
        paginated_results = formatted_results[offset:offset + limit]

        # 가사 개수 조회 (현재 페이지 결과만)
        if paginated_results:
            external_ids = [r['song_external_id'] for r in paginated_results]
            count_map = await lyrics_repo.get_lyrics_counts(external_ids)

            for r in paginated_results:
                r['lyrics_count'] = count_map.get(r['song_external_id'], 0)

        return {
            "items": paginated_results,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(paginated_results) < total
        }
    except Exception as e:
        logger.error(f"iTunes search error: {e}")
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다.")

@router.post("/custom", dependencies=[Depends(verify_csrf)])
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
@limiter.limit(RATE_LIMITS["search"])
async def search_custom_songs(request: Request, q: str, offset: int = 0, limit: int = 20):
    """Meilisearch를 사용하여 커스텀 노래 검색 (페이지네이션 지원, DB 폴백)"""
    if not q or len(q.strip()) < 1:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

    # 검색어 길이 제한 (DoS 방지)
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

        # 프론트엔드에서 기대하는 형식으로 변환
        for item in results.get('hits', []):
            formatted_results.append({
                "id": item.get('id'),
                "song_external_id": item.get('id'),
                "title": item.get('title', ''),
                "artist_name": item.get('singer', ''),
                "cover_image_url": item.get('image_url'),
                "is_custom": True
            })

        total = results.get('estimatedTotalHits', len(formatted_results))

        # 가사 제목으로 추가 검색 (Meilisearch 결과에 없는 곡 보완)
        lyrics_repo = get_lyrics_repository()
        lyrics_title_matches = await lyrics_repo.find_songs_by_lyrics_title(q, 'custom_')
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
                    "is_custom": True
                })
                existing_ext_ids.add(ext_id)
                added_count += 1
        total += added_count

    except Exception as e:
        # Meilisearch 실패 시 DB 폴백 (가사 제목도 함께 검색)
        use_fallback = True
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
            WHERE s.song_external_id LIKE 'custom_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
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
                "is_custom": True
            })

        # 전체 개수 조회
        count_query = """
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            WHERE s.song_external_id LIKE 'custom_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
        """
        count_result = await db_handler.fetch_one(count_query, (search_pattern, search_pattern, search_pattern))
        total = count_result['total'] if count_result else 0

    # 가사 개수 조회
    if formatted_results:
        lyrics_repo = get_lyrics_repository()
        external_ids = [r['song_external_id'] for r in formatted_results]
        count_map = await lyrics_repo.get_lyrics_counts(external_ids)

        for r in formatted_results:
            r['lyrics_count'] = count_map.get(r['song_external_id'], 0)

    return {
        "items": formatted_results,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(formatted_results) < total,
        "fallback": use_fallback  # 폴백 사용 여부 표시
    }
