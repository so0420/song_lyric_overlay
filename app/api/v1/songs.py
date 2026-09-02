import re

from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, Request, Query
from pydantic import BaseModel, field_validator
from app.core.auth import get_current_user, get_current_user_api, require_admin
from typing import Optional
from app.services.song_service import SongService, get_song_service
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.lyrics_repository import get_lyrics_repository
from app.database.songbook_repository import SONGBOOK_COVER_EXPR
from app.integrations.itunes_search import search_itunes
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS
from app.utils.log import logger


class SongUpdateSchema(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    cover_image_url: Optional[str] = None

    @field_validator("cover_image_url")
    @classmethod
    def validate_cover_image_url(cls, v: Optional[str]) -> Optional[str]:
        """커버 이미지 URL 은 http(s) 주소만 (빈 문자열은 '지우기' 뜻이라 그대로 통과).

        노래책 수록곡에 올린 커버는 우리 서빙 경로(/api/v1/songbook/cover-image/...)
        로 내려간다. 그 값이 이 API 로 되돌아와 songs.cover_image_url 에 박히면
        한 사람이 자기 노래책에 올린 커버가 전체 곡의 커버가 되어 버린다.
        상대 경로를 막아 그 경로를 끊는다 (속성 주입 차단도 겸한다).
        """
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""
        if len(v) > 1000:
            raise ValueError("커버 이미지 URL이 너무 깁니다.")
        if not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("커버 이미지 URL은 http(s) 주소만 사용할 수 있습니다.")
        return v

router = APIRouter()

# artists.name / songs.title 은 VARCHAR(512) (migration_song_title_length.sql).
# iTunes 표기가 그보다 길게 오는 경우까지 있어, 삽입 전에 잘라주지 않으면
# "Data too long" 으로 해당 곡 등록이 통째로 실패한다.
_NAME_MAX_LEN = 512


def _fit(value: Optional[str], max_len: int = _NAME_MAX_LEN) -> Optional[str]:
    """DB 컬럼 길이에 맞춰 문자열을 자른다. 값이 비어 있으면 None."""
    if not value:
        return None
    value = value.strip()
    return value[:max_len] if value else None


async def register_itunes_results(itunes_results: list) -> list:
    """iTunes 검색 결과를 커스텀 노래로 DB/Meilisearch에 등록하고 포맷된 결과 반환.
    기존에 관리자가 수정한 제목/가수명은 덮어쓰지 않도록 보존한다."""
    formatted = []
    meilisearch_docs = []

    for item in itunes_results:
        itunes_artist = _fit(item["artist_name"])
        itunes_title = _fit(item["track_name"])
        if not itunes_artist or not itunes_title:
            continue
        artist_ext_id = f"custom_it_{item['artist_id']}"
        song_ext_id = f"custom_it_{item['track_id']}"

        try:
            # 아티스트: 신규일 때만 이름 삽입. 이미 있으면 기존 이름(수정본 포함) 보존
            await db_handler.execute_query(
                """INSERT INTO artists (name, artist_external_id)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE id = id""",
                (itunes_artist, artist_ext_id),
            )
            artist_row = await db_handler.fetch_one(
                "SELECT id, name FROM artists WHERE artist_external_id = %s",
                (artist_ext_id,),
            )
            if not artist_row:
                continue
            current_artist_name = artist_row["name"]

            # 노래: 신규일 때만 제목/이미지 삽입. 이미 있으면 기존 값 보존
            await db_handler.execute_query(
                """INSERT INTO songs (title, song_external_id, artist_id, cover_image_url)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE id = id""",
                (itunes_title, song_ext_id, artist_row["id"], item["artwork_url"]),
            )
            song_row = await db_handler.fetch_one(
                "SELECT title, cover_image_url FROM songs WHERE song_external_id = %s",
                (song_ext_id,),
            )
            if not song_row:
                continue
            current_title = song_row["title"]
            current_cover = song_row["cover_image_url"]

            formatted.append({
                "id": song_ext_id,
                "song_external_id": song_ext_id,
                "title": current_title,
                "artist_name": current_artist_name,
                "cover_image_url": current_cover,
            })

            meilisearch_docs.append({
                "id": song_ext_id,
                "title": current_title,
                "singer": current_artist_name,
                "image_url": current_cover,
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


# 내 노래책 표기를 한 번에 가져올 최대 건수. 검색 한 번에 딸려가는 부수 질의라
# 상한을 둔다 (표기를 붙인 곡이 이보다 많으면 검색어에 걸린 것부터 채워진다).
_MY_SONGBOOK_NAME_LIMIT = 100


def _nospace_contains(query: str, *names) -> bool:
    """공백/대소문자를 무시한 부분 일치. 아래 SQL 의 LIKE 조건과 같은 판정을 파이썬에서 한다.

    (REPLACE(...) LIKE %nospace% 가 공백 포함 LIKE 를 포함하므로 이 하나로 충분하다)
    """
    nq = query.replace(" ", "").lower()
    if not nq:
        return False
    return any(n and nq in n.replace(" ", "").lower() for n in names)


async def _my_songbook_names(user, q: str, external_ids: list) -> dict:
    """로그인 사용자가 **자기** 노래책에서 곡에 붙인 표기 → {song_external_id: {...}}

    전체 곡 검색(Meilisearch)은 원곡 표기만 알고 있다. 그런데 노래책 주인에게는
    자기가 붙인 이름이 곧 그 곡의 이름이라, 그 이름으로도 찾히고 그 이름으로 보여야
    노래책·오버레이·재생목록이 서로 어긋나지 않는다.

    한 질의로 두 가지를 가져온다:
      ① 지금 결과에 들어 있는 곡의 표기 — 결과 라벨을 내 표기로 바꾸기 위해
      ② 검색어가 내 표기에만 걸리는 곡 — 결과에 없으면 덧붙이기 위해 (matched=True)

    다른 사람의 표기는 st.user_id 조건에서 배제되므로 남의 노래책 표기가
    전체 곡 검색에 섞이는 일은 없다.
    """
    if not user or not user.get("id"):
        return {}

    like = f"%{q}%"
    nospace = f"%{q.replace(' ', '')}%"
    conds = [
        "sb.custom_title LIKE %s", "sb.custom_artist LIKE %s",
        "REPLACE(sb.custom_title, ' ', '') LIKE %s",
        "REPLACE(sb.custom_artist, ' ', '') LIKE %s",
    ]
    params = [user["id"], like, like, nospace, nospace]
    if external_ids:
        placeholders = ", ".join(["%s"] * len(external_ids))
        conds.append(f"s.song_external_id IN ({placeholders})")
        params.extend(external_ids)
    params.append(_MY_SONGBOOK_NAME_LIMIT)

    sql = f"""
        SELECT s.song_external_id, sb.custom_title, sb.custom_artist,
               s.title AS original_title, a.name AS original_artist_name,
               {SONGBOOK_COVER_EXPR} AS cover_image_url
        FROM streamer_songbooks sb
        JOIN streamers st ON sb.streamer_id = st.id
        JOIN songs s ON sb.song_id = s.id
        LEFT JOIN artists a ON s.artist_id = a.id
        WHERE st.user_id = %s
          AND (sb.custom_title IS NOT NULL OR sb.custom_artist IS NOT NULL)
          AND ({' OR '.join(conds)})
        LIMIT %s
    """
    try:
        rows = await db_handler.fetch_all(sql, tuple(params))
    except Exception as e:
        # 부수 기능이므로 실패해도 검색 자체는 그대로 돌려준다
        logger.warning(f"내 노래책 표기 조회 실패: {e}")
        return {}

    result = {}
    for row in rows:
        ext_id = row["song_external_id"]
        if not ext_id:
            continue
        row = dict(row)
        # IN 절로 딸려온 것과 검색어에 실제로 걸린 것을 구분한다 (덧붙일지 판단용)
        row["matched"] = _nospace_contains(q, row.get("custom_title"), row.get("custom_artist"))
        result[ext_id] = row
    return result


@router.get("/search")
@limiter.limit(RATE_LIMITS["search"])
async def search_songs(
    request: Request,
    q: str,
    offset: int = 0,
    limit: int = 20,
    user=Depends(get_current_user),
):
    """노래 검색: iTunes 보강 + Meilisearch/DB 통합

    로그인 사용자에게는 자기 노래책에서 붙인 표기도 함께 검색·노출된다
    (my_songbook_title / my_songbook_artist_name — _my_songbook_names 참고).
    """
    if not q or len(q.strip()) < 1:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}

    if len(q) > 200:
        raise HTTPException(status_code=400, detail="검색어는 200자를 초과할 수 없습니다.")

    # 1단계: iTunes 검색 시도 (첫 페이지만, 실패해도 무시)
    itunes_formatted = []
    if offset == 0:
        itunes_results = await search_itunes(term=q, limit=100)
        if itunes_results:
            itunes_formatted = await register_itunes_results(itunes_results)

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

    # 4단계: 내 노래책 표기 반영 (로그인 사용자 본인 것만)
    #  - 결과에 있는 곡: 내가 붙인 이름을 함께 내려준다 (라벨 교체 여부는 화면이 정한다)
    #  - 내 표기에만 걸린 곡: 결과에 없으면 덧붙인다 (iTunes 병합과 같이 첫 페이지에서만
    #    — 매 페이지마다 덧붙이면 페이지를 넘길 때 같은 곡이 반복된다)
    my_names = await _my_songbook_names(user, q, [r["song_external_id"] for r in formatted_results])
    if my_names:
        existing_ext_ids = {r["song_external_id"] for r in formatted_results}
        for r in formatted_results:
            info = my_names.get(r["song_external_id"])
            if info:
                r["my_songbook_title"] = info["custom_title"]
                r["my_songbook_artist_name"] = info["custom_artist"]
        if offset == 0:
            for ext_id, info in my_names.items():
                if ext_id in existing_ext_ids or not info["matched"]:
                    continue
                formatted_results.append({
                    "id": ext_id,
                    "song_external_id": ext_id,
                    "title": info["original_title"] or "",
                    "artist_name": info["original_artist_name"] or "",
                    "cover_image_url": info["cover_image_url"],
                    "my_songbook_title": info["custom_title"],
                    "my_songbook_artist_name": info["custom_artist"],
                })
                existing_ext_ids.add(ext_id)
                total += 1

    # 5단계: 가사 개수 조회 → 가사 있는 노래 우선 정렬
    if formatted_results:
        lyrics_repo = get_lyrics_repository()
        external_ids = [r["song_external_id"] for r in formatted_results]
        count_map = await lyrics_repo.get_lyrics_counts(external_ids)
        for r in formatted_results:
            r["lyrics_count"] = count_map.get(r["song_external_id"], 0)

        # 같은 제목+가수인 중복 곡(앨범아트만 다름)은 하나로 합침 (가사 보유 레코드를 대표로)
        deduped = []
        seen = {}
        for r in formatted_results:
            key = ((r.get("title") or "").strip().lower(), (r.get("artist_name") or "").strip().lower())
            if key in seen:
                idx = seen[key]
                if r.get("lyrics_count", 0) > deduped[idx].get("lyrics_count", 0):
                    deduped[idx] = r  # 가사가 더 많은 레코드를 대표로 교체
                continue
            seen[key] = len(deduped)
            deduped.append(r)
        formatted_results = deduped

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


async def _reindex_songs_in_meilisearch(song_ids: list):
    """주어진 song.id 목록에 대해 Meilisearch 문서 재인덱싱"""
    if not song_ids:
        return
    placeholders = ",".join(["%s"] * len(song_ids))
    rows = await db_handler.fetch_all(
        f"""SELECT s.song_external_id as id, s.title, a.name as singer,
                   s.cover_image_url as image_url, s.owner_id
            FROM songs s
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.id IN ({placeholders})""",
        tuple(song_ids),
    )
    if not rows:
        return
    docs = [
        {
            "id": r["id"],
            "title": r["title"] or "",
            "singer": r["singer"] or "",
            "image_url": r["image_url"],
            "owner_id": r["owner_id"],
        }
        for r in rows
        if r["id"]
    ]
    if docs:
        try:
            await meilisearch_handler.add_documents(docs)
        except Exception as e:
            logger.warning(f"Meilisearch reindex error: {e}")


@router.get("/admin/search")
async def admin_search_songs(
    q: Optional[str] = Query(None, max_length=100, description="검색어(곡명/가수명)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    admin=Depends(require_admin),
):
    """관리자 곡 정보 수정용 곡 검색 (관리자 전용).

    노래책에 등록됐거나 가사가 있는 모든 곡을 반환한다 — 가사 없는 노래책 곡도 포함.
    각 곡의 가사 개수(lyrics_count)와 노래책 등록 수(songbook_count)를 함께 준다.
    """
    # 편집 대상: 가사가 있거나 노래책에 등록된 곡
    where = """
        WHERE (EXISTS (SELECT 1 FROM song_lyrics l WHERE l.song_id = s.id AND l.deleted_at IS NULL)
               OR EXISTS (SELECT 1 FROM streamer_songbooks sb WHERE sb.song_id = s.id))
    """
    params: list = []
    if q:
        where += """ AND (s.title LIKE %s OR a.name LIKE %s
                          OR REPLACE(s.title, ' ', '') LIKE %s OR REPLACE(a.name, ' ', '') LIKE %s)"""
        like = f"%{q}%"
        nospace = f"%{q.replace(' ', '')}%"
        params += [like, like, nospace, nospace]

    rows = await db_handler.fetch_all(
        f"""
        SELECT s.id AS song_id, s.song_external_id, s.title,
               a.name AS artist_name, s.cover_image_url,
               (SELECT COUNT(*) FROM song_lyrics l
                  WHERE l.song_id = s.id AND l.deleted_at IS NULL) AS lyrics_count,
               (SELECT COUNT(*) FROM streamer_songbooks sb WHERE sb.song_id = s.id) AS songbook_count
        FROM songs s
        LEFT JOIN artists a ON s.artist_id = a.id
        {where}
        ORDER BY s.title ASC, s.id ASC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    count_row = await db_handler.fetch_one(
        f"SELECT COUNT(*) AS total FROM songs s LEFT JOIN artists a ON s.artist_id = a.id {where}",
        tuple(params),
    )
    total = count_row["total"] if count_row else 0
    return {
        "items": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


@router.patch("/{external_id}", dependencies=[Depends(verify_csrf)])
async def update_song(
    external_id: str,
    payload: SongUpdateSchema,
    admin=Depends(require_admin),
):
    """노래 제목/가수명 수정 (관리자 전용).
    가수명 변경 시 같은 아티스트의 모든 노래가 영향을 받는다."""
    song_row = await db_handler.fetch_one(
        "SELECT id, artist_id FROM songs WHERE song_external_id = %s",
        (external_id,),
    )
    if not song_row:
        raise HTTPException(status_code=404, detail="Song not found")

    affected_song_ids = [song_row["id"]]

    # 제목 수정
    if payload.title is not None:
        new_title = payload.title.strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="제목은 비워둘 수 없습니다.")
        await db_handler.execute_query(
            "UPDATE songs SET title = %s WHERE id = %s",
            (new_title, song_row["id"]),
        )

    # 커버 이미지 URL 수정 (빈 문자열이면 NULL로 저장)
    if payload.cover_image_url is not None:
        new_cover = payload.cover_image_url.strip()
        await db_handler.execute_query(
            "UPDATE songs SET cover_image_url = %s WHERE id = %s",
            (new_cover if new_cover else None, song_row["id"]),
        )

    # 가수명 수정 (아티스트 이름 변경 — 같은 아티스트의 모든 노래 영향)
    if payload.artist is not None and song_row["artist_id"]:
        new_artist = payload.artist.strip()
        if not new_artist:
            raise HTTPException(status_code=400, detail="가수명은 비워둘 수 없습니다.")
        await db_handler.execute_query(
            "UPDATE artists SET name = %s WHERE id = %s",
            (new_artist, song_row["artist_id"]),
        )
        # 같은 아티스트의 모든 노래 재인덱싱 대상에 포함
        sibling_rows = await db_handler.fetch_all(
            "SELECT id FROM songs WHERE artist_id = %s",
            (song_row["artist_id"],),
        )
        affected_song_ids = list({r["id"] for r in sibling_rows} | {song_row["id"]})

    # Meilisearch 재인덱싱
    await _reindex_songs_in_meilisearch(affected_song_ids)

    # 업데이트된 현재 상태 반환
    updated = await db_handler.fetch_one(
        """SELECT s.song_external_id, s.title, a.name as artist_name, s.cover_image_url
           FROM songs s LEFT JOIN artists a ON s.artist_id = a.id
           WHERE s.id = %s""",
        (song_row["id"],),
    )
    return {
        "song_external_id": updated["song_external_id"],
        "title": updated["title"],
        "artist_name": updated["artist_name"],
        "cover_image_url": updated["cover_image_url"],
    }
