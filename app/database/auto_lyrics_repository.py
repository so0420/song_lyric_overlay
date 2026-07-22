"""자동 가사(LRCLIB) 적용 기록 / 관리자 정식 등록 대기 큐 레포지토리."""
from app.database.mariadb import db_handler
from typing import List, Dict, Any, Optional, Tuple


class AutoLyricsRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def resolve_song_id(self, external_id: str) -> Optional[int]:
        """song_external_id → 숫자 songs.id (없으면 None)."""
        row = await self.db.fetch_one(
            "SELECT id FROM songs WHERE song_external_id = %s", (external_id,)
        )
        return row["id"] if row else None

    # ---------------------------------------------------------------
    # 쓰기
    # ---------------------------------------------------------------
    async def upsert_import(
        self,
        user_id: Optional[int],
        song_id: int,
        lyrics_data: str,
        source: str = "lrclib",
        source_id: Optional[str] = None,
        track_name: Optional[str] = None,
        artist_name: Optional[str] = None,
        album_name: Optional[str] = None,
        duration: Optional[int] = None,
        synced_lyrics: Optional[str] = None,
        mr_youtube_video_id: Optional[str] = None,
        offset_ms: int = 0,
    ) -> Optional[int]:
        """자동 가사 적용 기록 upsert. (user_id, song_id, source_id) 조합이 같으면 갱신.

        관리자가 이미 처리/진행한 기록('registered' 확정, 'ignored' 무시, 'editing' 편집중)은
        내용(가사/오프셋 등)과 상태를 덮어쓰지 않는다. 'pending' 인 경우에만 최신 값으로 갱신한다.
        (그렇지 않으면 사용자가 같은 후보를 다시 적용할 때 관리자의 무시/편집 결정이 되돌려짐)
        Returns: 기록 id (재조회로 반환)
        """
        # 관리자가 손댄 상태는 보존, 'pending' 만 갱신
        query = """
            INSERT INTO auto_lyrics_imports
                (user_id, song_id, source, source_id, track_name, artist_name, album_name,
                 duration, synced_lyrics, lyrics_data, mr_youtube_video_id, offset_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            ON DUPLICATE KEY UPDATE
                track_name = IF(status <> 'pending', track_name, VALUES(track_name)),
                artist_name = IF(status <> 'pending', artist_name, VALUES(artist_name)),
                album_name = IF(status <> 'pending', album_name, VALUES(album_name)),
                duration = IF(status <> 'pending', duration, VALUES(duration)),
                synced_lyrics = IF(status <> 'pending', synced_lyrics, VALUES(synced_lyrics)),
                lyrics_data = IF(status <> 'pending', lyrics_data, VALUES(lyrics_data)),
                mr_youtube_video_id = IF(status <> 'pending', mr_youtube_video_id, VALUES(mr_youtube_video_id)),
                offset_ms = IF(status <> 'pending', offset_ms, VALUES(offset_ms)),
                status = status
        """
        await self.db.execute_query(
            query,
            (
                user_id, song_id, source, source_id, track_name, artist_name, album_name,
                duration, synced_lyrics, lyrics_data, mr_youtube_video_id, offset_ms,
            ),
        )
        # ON DUPLICATE 시 lastrowid 를 신뢰할 수 없어 재조회
        row = await self.db.fetch_one(
            """SELECT id FROM auto_lyrics_imports
               WHERE (user_id <=> %s) AND song_id = %s AND (source_id <=> %s)""",
            (user_id, song_id, source_id),
        )
        return row["id"] if row else None

    async def update_offset(self, import_id: int, user_id: Optional[int], offset_ms: int) -> bool:
        """본인 소유 기록의 '이 곡만 오프셋' 갱신 (등록 완료된 기록은 제외).

        값이 이미 같아 실제 변경이 없어도(=rowcount 0) 대상 행이 존재하면 성공으로 본다
        (aiomysql 은 CHANGED 행 기준 rowcount 라 no-op UPDATE 가 0 이 됨).
        """
        update_q = """
            UPDATE auto_lyrics_imports
            SET offset_ms = %s
            WHERE id = %s AND (user_id <=> %s) AND status <> 'registered'
        """
        exists_q = """
            SELECT 1 FROM auto_lyrics_imports
            WHERE id = %s AND (user_id <=> %s) AND status <> 'registered'
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(update_q, (offset_ms, import_id, user_id))
                if cursor.rowcount == 1:
                    return True
                # 변경이 없었던 경우: 값이 이미 동일한지(행 존재) 확인
                await cursor.execute(exists_q, (import_id, user_id))
                return await cursor.fetchone() is not None

    async def mark_editing(self, import_id: int, reviewed_by: int) -> bool:
        """'편집기에서 보기' 시 pending 리스트에서 빼되(중복 처리 방지) 잃지 않게 editing 으로.

        pending 또는 editing 에서만 전환(이미 registered/ignored 면 무시). 멱등적으로 재열람 가능.
        """
        query = """
            UPDATE auto_lyrics_imports
            SET status = 'editing', reviewed_by = %s
            WHERE id = %s AND status IN ('pending', 'editing')
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (reviewed_by, import_id))
                return cursor.rowcount == 1

    async def get_import_with_song(self, import_id: int) -> Optional[Dict[str, Any]]:
        """편집기 로드용: 기록 + 곡/아티스트 메타 조인."""
        return await self.db.fetch_one(
            """
            SELECT ali.*, s.title AS song_title, s.song_external_id,
                   s.cover_image_url AS song_cover, a.name AS song_artist
            FROM auto_lyrics_imports ali
            JOIN songs s ON ali.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE ali.id = %s
            """,
            (import_id,),
        )

    async def claim_for_register(self, import_id: int, reviewed_by: int) -> bool:
        """등록을 위해 기록을 원자적으로 선점(status→registered). 이미 registered 면 False.

        가사 생성 '전에' 이 UPDATE 로 선점해, 동시 요청이 중복 정식 가사를 만드는 것을 막는다.
        (rowcount==1 인 요청만 실제 등록을 진행한다)
        """
        query = """
            UPDATE auto_lyrics_imports
            SET status = 'registered', reviewed_by = %s
            WHERE id = %s AND status <> 'registered'
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (reviewed_by, import_id))
                return cursor.rowcount == 1

    async def set_registered_lyrics(self, import_id: int, lyrics_id: int) -> None:
        """선점(claim) 후 생성된 정식 가사 id 를 기록에 연결."""
        await self.db.execute_query(
            "UPDATE auto_lyrics_imports SET registered_lyrics_id = %s WHERE id = %s",
            (lyrics_id, import_id),
        )

    async def mark_ignored(self, import_id: int, reviewed_by: int) -> bool:
        query = """
            UPDATE auto_lyrics_imports
            SET status = 'ignored', reviewed_by = %s
            WHERE id = %s AND status <> 'registered'
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (reviewed_by, import_id))
                return cursor.rowcount > 0

    # ---------------------------------------------------------------
    # 읽기
    # ---------------------------------------------------------------
    async def get_import(self, import_id: int) -> Optional[Dict[str, Any]]:
        return await self.db.fetch_one(
            "SELECT * FROM auto_lyrics_imports WHERE id = %s", (import_id,)
        )

    async def list_imports(
        self, status: Optional[str] = None, offset: int = 0, limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """관리자 목록 조회 (곡/아티스트/적용자 조인). (items, total) 반환."""
        where = ""
        params: list = []
        if status:
            where = "WHERE ali.status = %s"
            params.append(status)

        rows = await self.db.fetch_all(
            f"""
            SELECT ali.id, ali.song_id, ali.source, ali.source_id,
                   ali.track_name, ali.artist_name, ali.album_name, ali.duration,
                   ali.lyrics_data, ali.offset_ms, ali.mr_youtube_video_id,
                   ali.status, ali.registered_lyrics_id, ali.created_at, ali.updated_at,
                   s.title AS song_title, s.song_external_id, a.name AS song_artist,
                   u.name AS applied_by_name, u.email AS applied_by_email
            FROM auto_lyrics_imports ali
            JOIN songs s ON ali.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN users u ON ali.user_id = u.id
            {where}
            ORDER BY ali.updated_at DESC, ali.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        count_row = await self.db.fetch_one(
            f"SELECT COUNT(*) AS total FROM auto_lyrics_imports ali {where}",
            tuple(params) if params else None,
        )
        total = count_row["total"] if count_row else 0
        return rows, total


def get_auto_lyrics_repository() -> AutoLyricsRepository:
    return AutoLyricsRepository()
