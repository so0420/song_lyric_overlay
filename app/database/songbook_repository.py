from app.database.mariadb import db_handler
from app.database.streamer_repository import parse_json_field, dump_json_field
from typing import Optional, Dict, Any, List
import json


# 공통 SELECT: 수록곡 + 노래/아티스트/연결 가사 메타데이터
# (soft delete 된 가사는 FK SET NULL 이 발동하지 않으므로 JOIN 조건으로 걸러 lyrics_id 가 NULL 로 나온다)
# 커버는 수록곡별 지정 커버가 없으면 곡 자체의 커버로 폴백한다
# recent_request_count: 최근 1달간 이 곡(같은 스트리머)의 신청 횟수 (상관 서브쿼리)
_SONGBOOK_SELECT = """
    SELECT sb.id AS entry_id, sb.sort_order, sb.difficulty, sb.memo, sb.tags AS song_tags,
           sb.mr_youtube_video_id, sb.audio_file_id,
           COALESCE(sb.cover_image_url, s.cover_image_url) AS cover_image_url,
           s.id AS song_id, s.song_external_id, s.title, s.length_ms,
           a.name AS artist_name,
           l.id AS lyrics_id, l.title AS lyrics_title, l.mr_youtube_video_id AS lyrics_mr_video_id,
           l.audio_file_id AS lyrics_audio_file_id,
           (SELECT COUNT(*) FROM song_request_logs rl
            WHERE rl.song_id = sb.song_id AND rl.streamer_id = sb.streamer_id
              AND rl.requested_at >= NOW() - INTERVAL 1 MONTH) AS recent_request_count
    FROM streamer_songbooks sb
    JOIN songs s ON sb.song_id = s.id
    LEFT JOIN artists a ON s.artist_id = a.id
    LEFT JOIN song_lyrics l ON sb.lyrics_id = l.id AND l.deleted_at IS NULL
"""


# 정렬 옵션 → ORDER BY 절 (화이트리스트; 항상 마지막에 sb.id 로 안정 정렬)
# recent_request_count 는 _SONGBOOK_SELECT 의 별칭이라 ORDER BY 에서 참조 가능
# sort_order 는 추가 시 MAX+1 로만 매겨지므로 DESC = 최근에 추가한 곡이 위
_SORT_ORDERS = {
    "default": "sb.sort_order DESC, sb.id DESC",
    "requests": "recent_request_count DESC, sb.sort_order DESC, sb.id DESC",
    "requests_asc": "recent_request_count ASC, sb.sort_order DESC, sb.id DESC",
}


def _build_filters(q: Optional[str], tags: Optional[List[str]], has_lyrics: Optional[bool] = None):
    """검색어/태그/가사보유 필터 SQL 조각과 파라미터를 생성한다.

    has_lyrics: True=가사 있는 곡만, False=가사 없는 곡만, None=전체
    (가사 보유 판정은 LEFT JOIN 된 song_lyrics l.id 기준 — 호출 쿼리에 해당 JOIN 필요)
    """
    sql = ""
    params: list = []
    if q:
        sql += " AND (s.title LIKE %s OR a.name LIKE %s)"
        pattern = f"%{q}%"
        params.extend([pattern, pattern])
    if tags:
        for tag in tags:
            sql += " AND JSON_CONTAINS(sb.tags, %s)"
            params.append(json.dumps(tag, ensure_ascii=False))
    if has_lyrics is True:
        sql += " AND l.id IS NOT NULL"
    elif has_lyrics is False:
        sql += " AND l.id IS NULL"
    return sql, params


class SongbookRepository:
    def __init__(self, db=db_handler):
        self.db = db

    # ---------------------------------------------------------------
    # 조회
    # ---------------------------------------------------------------
    async def get_songbook(
        self,
        streamer_internal_id: int,
        q: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 500,
        offset: int = 0,
        has_lyrics: Optional[bool] = None,
        sort: str = "default",
    ) -> List[Dict[str, Any]]:
        """노래책 수록곡 목록 조회 (검색어/태그/가사보유 필터, 정렬, 페이지네이션)

        sort: default=최근 추가순, requests=최근 1달 신청 많은 순, requests_asc=적은 순
        """
        filter_sql, filter_params = _build_filters(q, tags, has_lyrics)
        order_by = _SORT_ORDERS.get(sort, _SORT_ORDERS["default"])
        query = (
            _SONGBOOK_SELECT
            + " WHERE sb.streamer_id = %s"
            + filter_sql
            + f" ORDER BY {order_by} LIMIT %s OFFSET %s"
        )
        params = (streamer_internal_id, *filter_params, limit, offset)
        rows = await self.db.fetch_all(query, params)

        for row in rows:
            # 태그 JSON 파싱 + 가사 연결 여부 플래그
            row["tags"] = parse_json_field(row.pop("song_tags", None), [])
            row["has_lyrics"] = row.get("lyrics_id") is not None
        return rows

    async def count_songbook(
        self,
        streamer_internal_id: int,
        q: Optional[str] = None,
        tags: Optional[List[str]] = None,
        has_lyrics: Optional[bool] = None,
    ) -> int:
        """노래책 수록곡 총 개수 (get_songbook 과 동일 필터)"""
        filter_sql, filter_params = _build_filters(q, tags, has_lyrics)
        query = (
            """
            SELECT COUNT(*) AS total
            FROM streamer_songbooks sb
            JOIN songs s ON sb.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON sb.lyrics_id = l.id AND l.deleted_at IS NULL
            WHERE sb.streamer_id = %s
            """
            + filter_sql
        )
        result = await self.db.fetch_one(query, (streamer_internal_id, *filter_params))
        return result["total"] if result else 0

    async def get_entry(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """수록곡 단건 조회 (소유권 검증용 user_id 포함)"""
        query = """
            SELECT sb.*, st.user_id
            FROM streamer_songbooks sb
            JOIN streamers st ON sb.streamer_id = st.id
            WHERE sb.id = %s
        """
        row = await self.db.fetch_one(query, (entry_id,))
        if row:
            row["tags"] = parse_json_field(row.get("tags"), [])
        return row

    # ---------------------------------------------------------------
    # 생성 / 수정 / 삭제
    # ---------------------------------------------------------------
    async def add_song(
        self,
        streamer_id: int,
        song_id: int,
        lyrics_id: Optional[int] = None,
        mr_youtube_video_id: Optional[str] = None,
        audio_file_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
        difficulty: Optional[int] = None,
        memo: Optional[str] = None,
        cover_image_url: Optional[str] = None,
    ) -> Optional[int]:
        """수록곡 추가. 같은 곡을 다시 추가하면 메타데이터만 갱신한다 (sort_order 유지).

        Returns:
            수록곡 entry id (ON DUPLICATE 시 lastrowid 를 신뢰할 수 없어 재조회로 반환)
        """
        count_res = await self.db.fetch_one(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM streamer_songbooks WHERE streamer_id = %s",
            (streamer_id,),
        )
        next_sort = count_res["next_sort"] if count_res else 1

        query = """
            INSERT INTO streamer_songbooks
                (streamer_id, sort_order, song_id, mr_youtube_video_id, audio_file_id, lyrics_id,
                 cover_image_url, tags, difficulty, memo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mr_youtube_video_id = VALUES(mr_youtube_video_id),
                audio_file_id = VALUES(audio_file_id),
                lyrics_id = VALUES(lyrics_id),
                cover_image_url = VALUES(cover_image_url),
                tags = VALUES(tags),
                difficulty = VALUES(difficulty),
                memo = VALUES(memo)
        """
        await self.db.execute_query(
            query,
            (
                streamer_id, next_sort, song_id, mr_youtube_video_id, audio_file_id, lyrics_id,
                cover_image_url, dump_json_field(tags), difficulty, memo,
            ),
        )

        res = await self.db.fetch_one(
            "SELECT id FROM streamer_songbooks WHERE streamer_id = %s AND song_id = %s",
            (streamer_id, song_id),
        )
        return res["id"] if res else None

    async def update_entry(self, entry_id: int, **kwargs) -> bool:
        """수록곡 동적 UPDATE (화이트리스트 컬럼만). tags 는 JSON 직렬화."""
        allowed = {"lyrics_id", "mr_youtube_video_id", "audio_file_id", "tags", "difficulty", "memo", "cover_image_url"}
        updates = []
        params = []
        for key, val in kwargs.items():
            if key not in allowed:
                continue
            if key == "tags":
                val = dump_json_field(val)
            updates.append(f"`{key}` = %s")
            params.append(val)

        if not updates:
            return False

        query = f"UPDATE streamer_songbooks SET {', '.join(updates)} WHERE id = %s"
        params.append(entry_id)
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, tuple(params))
                return cursor.rowcount > 0

    async def remove_entry(self, entry_id: int) -> bool:
        """수록곡 삭제"""
        query = "DELETE FROM streamer_songbooks WHERE id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (entry_id,))
                return cursor.rowcount > 0

    async def autolink_song_lyrics(self, song_id: int, lyrics_id: int) -> int:
        """이 곡(및 같은 제목+가수 형제 곡)을 노래책에 보유하고 가사가 연결되지 않은
        항목에 새 가사를 자동 연결.

        이미 가사가 연결된 항목(lyrics_id 가 NULL 이 아님)은 건드리지 않는다.
        자동 연결된 항목 수를 반환.
        """
        query = """
            UPDATE streamer_songbooks sb
            JOIN songs sbsong ON sb.song_id = sbsong.id
            JOIN songs refsong ON refsong.id = %s
                 AND sbsong.title = refsong.title AND (sbsong.artist_id <=> refsong.artist_id)
            SET sb.lyrics_id = %s
            WHERE sb.lyrics_id IS NULL
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (song_id, lyrics_id))
                return cursor.rowcount


def get_songbook_repository() -> SongbookRepository:
    return SongbookRepository()
