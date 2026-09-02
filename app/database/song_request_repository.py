from app.database.mariadb import db_handler
from app.database.songbook_repository import (
    SONGBOOK_ARTIST_EXPR,
    SONGBOOK_COVER_EXPR,
    SONGBOOK_TITLE_EXPR,
)
from typing import Optional, Dict, Any, List


# 공통 SELECT: 신청 + 참조 노래/아티스트/노래책 수록 정보/연결 가사 메타데이터
# (soft delete 된 가사는 JOIN 조건으로 걸러 ref_lyrics_id 가 NULL 로 나온다)
# 제목/가수/커버는 노래책과 같은 규칙으로 고른다 — 노래책 주인이 수록곡에 덮어쓴 값이
# 있으면 신청 목록·노래하기 재생목록에서도 그 표기로 보여야 한다.
_REQUEST_SELECT = f"""
    SELECT r.*, s.song_external_id,
           {SONGBOOK_TITLE_EXPR} AS ref_song_title,
           {SONGBOOK_ARTIST_EXPR} AS ref_artist_name,
           {SONGBOOK_COVER_EXPR} AS ref_song_cover,
           sb.mr_youtube_video_id AS sb_mr_video_id, sb.audio_file_id AS sb_audio_file_id,
           l.id AS ref_lyrics_id, l.title AS ref_lyrics_title, l.mr_youtube_video_id AS lyrics_mr_video_id,
           l.audio_file_id AS lyrics_audio_file_id,
           CASE WHEN sb.id IS NOT NULL THEN 1 ELSE 0 END AS is_in_songbook
    FROM song_requests r
    LEFT JOIN songs s ON r.song_id = s.id
    LEFT JOIN artists a ON s.artist_id = a.id
    LEFT JOIN streamer_songbooks sb ON r.song_id = sb.song_id AND r.streamer_id = sb.streamer_id
    LEFT JOIN song_lyrics l ON sb.lyrics_id = l.id AND l.deleted_at IS NULL
"""

_REQUEST_ORDER = " ORDER BY r.sort_order ASC, r.created_at ASC"


class SongRequestRepository:
    def __init__(self, db=db_handler):
        self.db = db

    # ---------------------------------------------------------------
    # 조회
    # ---------------------------------------------------------------
    async def get_requests(self, streamer_internal_id: int) -> List[Dict[str, Any]]:
        """신청 목록 조회 (노래책 수록/가사 연결 정보 포함)"""
        query = _REQUEST_SELECT + " WHERE r.streamer_id = %s" + _REQUEST_ORDER
        return await self.db.fetch_all(query, (streamer_internal_id,))

    async def get_request_push_data(self, request_id: int) -> Optional[Dict[str, Any]]:
        """WS 푸시(song_request_new) 데이터 작성용 단건 조회 (get_requests 와 동일 JOIN)"""
        query = _REQUEST_SELECT + " WHERE r.id = %s"
        return await self.db.fetch_one(query, (request_id,))

    async def has_waiting_duplicate(
        self,
        streamer_id: int,
        requester: str,
        song_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> bool:
        """동일 신청자의 대기 중(waiting) 중복 신청 여부 (song_id 있으면 song_id 기준, 없으면 title 기준)"""
        if song_id is not None:
            query = """
                SELECT 1 FROM song_requests
                WHERE streamer_id = %s AND requester = %s AND status = 'waiting' AND song_id = %s
                LIMIT 1
            """
            params = (streamer_id, requester, song_id)
        else:
            query = """
                SELECT 1 FROM song_requests
                WHERE streamer_id = %s AND requester = %s AND status = 'waiting' AND title = %s
                LIMIT 1
            """
            params = (streamer_id, requester, title)
        result = await self.db.fetch_one(query, params)
        return result is not None

    async def belongs_to(self, request_id: int, streamer_id: int) -> bool:
        """해당 신청이 이 스트리머의 것인지 확인 (no-op 수정과 미존재를 구분하기 위함)"""
        query = "SELECT 1 FROM song_requests WHERE id = %s AND streamer_id = %s LIMIT 1"
        return await self.db.fetch_one(query, (request_id, streamer_id)) is not None

    async def count_waiting(self, streamer_id: int) -> int:
        """대기 중(waiting) 신청 건수 — 폭주 방지 상한 검사용"""
        query = "SELECT COUNT(*) AS cnt FROM song_requests WHERE streamer_id = %s AND status = 'waiting'"
        result = await self.db.fetch_one(query, (streamer_id,))
        return (result or {}).get("cnt", 0)

    async def get_playlist_pending(self, streamer_id: int) -> List[Dict[str, Any]]:
        """노래하기 재생목록 자동 추가 미전달분 조회 (대기중 + delivered_at IS NULL)"""
        query = (
            _REQUEST_SELECT
            + " WHERE r.streamer_id = %s AND r.status = 'waiting' AND r.delivered_at IS NULL"
            + _REQUEST_ORDER
        )
        return await self.db.fetch_all(query, (streamer_id,))

    # ---------------------------------------------------------------
    # 생성 / 수정 / 삭제
    # ---------------------------------------------------------------
    async def add_request(
        self,
        streamer_id: int,
        requester: str,
        requester_type: str,
        requester_platform: Optional[str] = None,
        song_id: Optional[int] = None,
        title: Optional[str] = None,
        artist: Optional[str] = None,
    ) -> int:
        """신청 추가 (sort_order = MAX+1). 신규 신청 id(lastrowid) 반환.

        곡이 특정된 신청(song_id NOT NULL)은 통계용 영구 로그(song_request_logs)에도 적재한다.
        (song_requests 는 큐 정리로 삭제되지만, 신청 횟수 통계는 삭제와 무관해야 하므로 별도 로그)
        """
        async with self.db.transaction() as tx:
            count_res = await tx.fetch_one(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort FROM song_requests WHERE streamer_id = %s",
                (streamer_id,),
            )
            next_sort = count_res["next_sort"] if count_res else 1

            query = """
                INSERT INTO song_requests
                    (streamer_id, requester, requester_type, requester_platform, sort_order, song_id, title, artist)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            request_id = await tx.execute_query(
                query,
                (streamer_id, requester, requester_type, requester_platform, next_sort, song_id, title, artist),
            )

            if song_id is not None:
                await tx.execute_query(
                    "INSERT INTO song_request_logs (streamer_id, song_id) VALUES (%s, %s)",
                    (streamer_id, song_id),
                )
        return request_id

    async def update_request(self, request_id: int, streamer_id: int, **fields) -> int:
        """신청 동적 UPDATE (화이트리스트 컬럼만, streamer_id 로 소유권 검증). 영향 행 수 반환."""
        allowed = {"status", "sort_order", "title", "artist"}
        updates = []
        params = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            updates.append(f"`{key}` = %s")
            params.append(val)

        if not updates:
            return 0

        query = f"UPDATE song_requests SET {', '.join(updates)} WHERE id = %s AND streamer_id = %s"
        params.extend([request_id, streamer_id])
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, tuple(params))
                return cursor.rowcount

    async def delete_request(self, request_id: int, streamer_id: int) -> int:
        """신청 개별 삭제 (소유권 검증 포함). 삭제 행 수 반환."""
        query = "DELETE FROM song_requests WHERE id = %s AND streamer_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (request_id, streamer_id))
                return cursor.rowcount

    async def delete_done(self, streamer_id: int) -> int:
        """이미 부른(done) 신청 일괄 삭제. 삭제 행 수 반환."""
        query = "DELETE FROM song_requests WHERE streamer_id = %s AND status = 'done'"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (streamer_id,))
                return cursor.rowcount

    async def delete_all(self, streamer_id: int) -> int:
        """신청 전체 삭제. 삭제 행 수 반환."""
        query = "DELETE FROM song_requests WHERE streamer_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (streamer_id,))
                return cursor.rowcount

    # ---------------------------------------------------------------
    # 정렬 / 상태머신
    # ---------------------------------------------------------------
    async def reorder(self, streamer_id: int, ordered_ids: List[int]) -> None:
        """신청 순서 재정렬 (트랜잭션). ordered_ids 순서대로 sort_order 1부터 부여."""
        if not ordered_ids:
            return
        async with self.db.transaction() as tx:
            for idx, request_id in enumerate(ordered_ids):
                await tx.execute_query(
                    "UPDATE song_requests SET sort_order = %s WHERE id = %s AND streamer_id = %s",
                    (idx + 1, request_id, streamer_id),
                )

    async def next_request(self, streamer_id: int) -> Optional[int]:
        """다음 곡: 부르는 중(playing) → 이미 부름(done), 첫 대기(waiting) → 부르는 중(playing).

        Returns:
            새로 playing 이 된 신청 id (대기 곡이 없으면 None)
        """
        async with self.db.transaction() as tx:
            await tx.execute_query(
                "UPDATE song_requests SET status = 'done' WHERE streamer_id = %s AND status = 'playing'",
                (streamer_id,),
            )
            next_req = await tx.fetch_one(
                """SELECT id FROM song_requests
                   WHERE streamer_id = %s AND status = 'waiting'
                   ORDER BY sort_order ASC, created_at ASC LIMIT 1""",
                (streamer_id,),
            )
            if next_req:
                await tx.execute_query(
                    "UPDATE song_requests SET status = 'playing' WHERE id = %s",
                    (next_req["id"],),
                )
                return next_req["id"]
        return None

    async def prev_request(self, streamer_id: int) -> Optional[int]:
        """이전 곡: 부르는 중(playing) → 대기(waiting), 마지막 done → 부르는 중(playing).

        Returns:
            새로 playing 이 된 신청 id (done 곡이 없으면 None)
        """
        async with self.db.transaction() as tx:
            await tx.execute_query(
                "UPDATE song_requests SET status = 'waiting' WHERE streamer_id = %s AND status = 'playing'",
                (streamer_id,),
            )
            prev_req = await tx.fetch_one(
                """SELECT id FROM song_requests
                   WHERE streamer_id = %s AND status = 'done'
                   ORDER BY sort_order DESC, created_at DESC LIMIT 1""",
                (streamer_id,),
            )
            if prev_req:
                await tx.execute_query(
                    "UPDATE song_requests SET status = 'playing' WHERE id = %s",
                    (prev_req["id"],),
                )
                return prev_req["id"]
        return None

    async def reset_status(self, streamer_id: int) -> int:
        """전체 상태 초기화: 모두 waiting (delivered_at 은 유지 — 재생목록 재전달 방지)"""
        query = "UPDATE song_requests SET status = 'waiting' WHERE streamer_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (streamer_id,))
                return cursor.rowcount

    async def mark_delivered(self, streamer_id: int, ids: List[int]) -> int:
        """노래하기 재생목록 전달 완료 마킹 (delivered_at = NOW())"""
        if not ids:
            return 0
        placeholders = ", ".join(["%s"] * len(ids))
        query = f"UPDATE song_requests SET delivered_at = NOW() WHERE streamer_id = %s AND id IN ({placeholders})"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (streamer_id, *ids))
                return cursor.rowcount


def get_song_request_repository() -> SongRequestRepository:
    return SongRequestRepository()
