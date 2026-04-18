from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Request
from app.core.auth import get_current_user, get_current_user_api
from typing import Optional
from app.services.song_service import SongService, get_song_service
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.lyrics_repository import get_lyrics_repository
from app.integrations.itunes_search import search_itunes
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS
from app.utils.log import logger

router = APIRouter()


async def _register_itunes_results(itunes_results: list) -> list:
    """iTunes 검색 결과를 커스텀 노래로 DB/Meilisearch에 등록하고 포맷된 결과 반환"""
    formatted = []
    meilisearch_docs = []

    for item in itunes_results:
        artist_name = item["artist_name"]
        artist_ext_id = f"custom_it_{item['artist_id']}"
        song_ext_id = f"custom_it_{item['track_id']}"

        try:
            # 아티스트 등록 (이미 있으면 무시)
            await db_handler.execute_query(
                """INSERT INTO artists (name, artist_external_id)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE name = VALUES(name)""",
                (artist_name, artist_ext_id),
            )
            artist_row = await db_handler.fetch_one(
                "SELECT id FROM artists WHERE artist_external_id = %s",
                (artist_ext_id,),
            )
            if not artist_row:
                continue

            # 노래 등록 (이미 있으면 커버 이미지만 갱신)
            await db_handler.execute_query(
                """INSERT INTO songs (title, song_external_id, artist_id, cover_image_url)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE cover_image_url = VALUES(cover_image_url)""",
                (item["track_name"], song_ext_id, artist_row["id"], item["artwork_url"]),
            )

            formatted.append({
                "id": song_ext_id,
                "song_external_id": song_ext_id,
                "title": item["track_name"],
                "artist_name": artist_name,
                "cover_image_url": item["artwork_url"],
            })

            meilisearch_docs.append({
                "id": song_ext_id,
                "title": item["track_name"],
                "singer": artist_name,
                "image_url": item["artwork_url"],
                "owner_id": None,
            })
        except Exception as e:
            logger.warning(f"iTunes result registration error: {e}")
            continue

    # Meilisearch 인덱싱 (실패해도 무시)
    if meilisearch_docs:
        try:
            await meilisearch_handler.add_documents(meilisearch_docs)
        except Exception as e:
            logger.warning(f"Meilisearch indexing error for iTunes results: {e}")

    return formatted


@router.get("/search")
@limiter.limit(RATE_LIMITS["search"])
async def search_songs(request: Request, q: str, offset: int = 0, limit: int = 20):
    """노래 검색: iTunes 보강 + Meilisearch/DB 통합"""
    if not q or len(q.strip()) < 1:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

    if len(q) > 200:
        raise HTTPException(status_code=400, detail="검색어는 200자를 초과할 수 없습니다.")

    # 1단계: iTunes 검색 시도 (첫 페이지만, 실패해도 무시)
    itunes_formatted = []
    if offset == 0:
        itunes_results = await search_itunes(term=q, limit=100)
        if itunes_results:
            itunes_formatted = await _register_itunes_results(itunes_results)

    # 2단계: Meilisearch/DB 검색
    formatted_results = []
    total = 0
    use_fallback = False

    try:
        results = await meilisearch_handler.search(
            query=q,
            offset=offset,
            limit=min(limit, 100),
            attributes_to_search_on=["title", "singer"],
        )

        # 결과 없고 공백 있는 쿼리면 공백 제거 후 재시도
        if not results.get("hits") and " " in q:
            nospace_q = q.replace(" ", "")
            results = await meilisearch_handler.search(
                query=nospace_q,
                offset=offset,
                limit=min(limit, 100),
                attributes_to_search_on=["title", "singer"],
            )

        for item in results.get("hits", []):
            formatted_results.append({
                "id": item.get("id"),
                "song_external_id": item.get("id"),
                "title": item.get("title", ""),
                "artist_name": item.get("singer", ""),
                "cover_image_url": item.get("image_url"),
            })

        total = results.get("estimatedTotalHits", len(formatted_results))

        # 가사 제목으로 추가 검색
        lyrics_repo = get_lyrics_repository()
        lyrics_title_matches = await lyrics_repo.find_songs_by_lyrics_title(q)
        existing_ext_ids = {r["song_external_id"] for r in formatted_results}
        added_count = 0
        for item in lyrics_title_matches:
            ext_id = item["song_external_id"]
            if ext_id not in existing_ext_ids:
                formatted_results.append({
                    "id": ext_id,
                    "song_external_id": ext_id,
                    "title": item["title"] or "",
                    "artist_name": item["artist_name"] or "",
                    "cover_image_url": item["cover_image_url"],
                })
                existing_ext_ids.add(ext_id)
                added_count += 1
        total += added_count

    except Exception as e:
        use_fallback = True
        logger.warning(f"Meilisearch search failed, using DB fallback: {e}")
        search_pattern = f"%{q}%"
        # 공백 무시 검색: 쿼리와 필드 모두 공백 제거 후 비교
        nospace_pattern = f"%{q.replace(' ', '')}%"
        fallback_query = """
            SELECT DISTINCT
                s.song_external_id as id, s.title, a.name as singer, s.cover_image_url as image_url
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s
                   OR REPLACE(s.title, ' ', '') LIKE %s
                   OR REPLACE(a.name, ' ', '') LIKE %s
                   OR REPLACE(l.title, ' ', '') LIKE %s)
            ORDER BY s.title ASC
            LIMIT %s OFFSET %s
        """
        fallback_results = await db_handler.fetch_all(
            fallback_query,
            (search_pattern, search_pattern, search_pattern,
             nospace_pattern, nospace_pattern, nospace_pattern,
             limit, offset)
        )
        for item in fallback_results:
            formatted_results.append({
                "id": item.get("id"),
                "song_external_id": item.get("id"),
                "title": item.get("title", ""),
                "artist_name": item.get("singer", ""),
                "cover_image_url": item.get("image_url"),
            })
        count_query = """
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s
                   OR REPLACE(s.title, ' ', '') LIKE %s
                   OR REPLACE(a.name, ' ', '') LIKE %s
                   OR REPLACE(l.title, ' ', '') LIKE %s)
        """
        count_result = await db_handler.fetch_one(
            count_query,
            (search_pattern, search_pattern, search_pattern,
             nospace_pattern, nospace_pattern, nospace_pattern)
        )
        total = count_result["total"] if count_result else 0

    # 3단계: iTunes 결과 병합 (Meilisearch에 아직 인덱싱 안 된 것 보완)
    if itunes_formatted:
        existing_ext_ids = {r["song_external_id"] for r in formatted_results}
        for item in itunes_formatted:
            if item["song_external_id"] not in existing_ext_ids:
                formatted_results.append(item)
                existing_ext_ids.add(item["song_external_id"])
                total += 1

    # 4단계: 가사 개수 조회 → 가사 있는 노래 우선 정렬
    if formatted_results:
        lyrics_repo = get_lyrics_repository()
        external_ids = [r["song_external_id"] for r in formatted_results]
        count_map = await lyrics_repo.get_lyrics_counts(external_ids)
        for r in formatted_results:
            r["lyrics_count"] = count_map.get(r["song_external_id"], 0)
        formatted_results.sort(key=lambda r: r["lyrics_count"], reverse=True)

    return {
        "items": formatted_results,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(formatted_results) < total,
        "fallback": use_fallback,
    }


@router.post("/custom", dependencies=[Depends(verify_csrf)])
async def register_custom_song(
    title: str = Form(...),
    artist: str = Form(...),
    image: Optional[UploadFile] = File(None),
    service: SongService = Depends(get_song_service),
    user=Depends(get_current_user),
):
    return await service.create_custom_song(
        title=title,
        artist=artist,
        image=image,
        owner_id=user["id"] if user else None,
    )


@router.get("/info")
async def get_song_info(
    external_id: str,
    service: SongService = Depends(get_song_service),
):
    """external_id로 곡 정보 조회"""
    song = await service.get_song_info(external_id)
    if song:
        return song
    raise HTTPException(status_code=404, detail="Song not found")
