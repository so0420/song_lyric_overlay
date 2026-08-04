from typing import Any, Dict, List, Optional

from app.database.mariadb import db_handler


class AudioRepository:
    """업로드 음원(audio_files) 저장소.

    쓰기 권한은 이 프로젝트 관례대로 SQL 의 `WHERE ... AND owner_id = %s` 로 강제하고,
    rowcount 로 성공 여부를 판단한다 (lyrics_repository.update_lyrics 와 같은 방식).
    """

    def __init__(self, db=db_handler):
        self.db = db

    # ---------------------------------------------------------------
    # Read
    # ---------------------------------------------------------------
    async def get_by_id(self, audio_id: int) -> Optional[Dict[str, Any]]:
        """삭제 표시된 것도 그대로 돌려준다 (호출부가 deleted_at 을 보고 판단)."""
        return await self.db.fetch_one(
            "SELECT * FROM audio_files WHERE id = %s", (audio_id,)
        )

    async def find_by_owner_sha256(self, owner_id: int, sha256: str) -> Optional[Dict[str, Any]]:
        """같은 사용자가 같은 파일을 다시 올렸는지 확인 (중복 저장 방지).

        **파기 표시된 행도 함께 돌려준다.** UNIQUE(owner_id, sha256) 은 deleted_at 을
        보지 않으므로, 삭제된 행을 못 본 채 INSERT 하면 중복 키로 500 이 난다.
        호출부가 deleted_at 을 보고 되살릴지(revive) 판단한다.
        """
        return await self.db.fetch_one(
            "SELECT * FROM audio_files WHERE owner_id = %s AND sha256 = %s",
            (owner_id, sha256),
        )

    async def revive(
        self,
        audio_id: int,
        storage_path: str,
        mime_type: str,
        byte_size: int,
        original_filename: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> bool:
        """파기 표시된 행을 새로 올린 파일로 되살린다.

        옛 블롭은 리퍼가 이미 지웠을 수 있으므로 행을 그대로 재사용하지 않고
        새 storage_path 로 갈아끼운다.
        """
        query = """
            UPDATE audio_files
               SET deleted_at = NULL,
                   storage_path = %s,
                   mime_type = %s,
                   byte_size = %s,
                   original_filename = %s,
                   duration_ms = %s,
                   created_at = NOW(),
                   updated_at = NOW()
             WHERE id = %s
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    (storage_path, mime_type, byte_size, original_filename, duration_ms, audio_id),
                )
                return cursor.rowcount > 0

    async def list_by_owner(self, owner_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        query = """
            SELECT id, original_filename, mime_type, byte_size, duration_ms, created_at
            FROM audio_files
            WHERE owner_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        return await self.db.fetch_all(query, (owner_id, limit, offset))

    async def count_by_owner(self, owner_id: int) -> int:
        row = await self.db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM audio_files WHERE owner_id = %s AND deleted_at IS NULL",
            (owner_id,),
        )
        return int(row["cnt"]) if row else 0

    async def total_bytes(self, owner_id: int) -> int:
        """사용자별 총 사용량 (용량 제한을 켜게 되면 쓰는 값)."""
        row = await self.db.fetch_one(
            "SELECT COALESCE(SUM(byte_size), 0) AS total FROM audio_files "
            "WHERE owner_id = %s AND deleted_at IS NULL",
            (owner_id,),
        )
        return int(row["total"]) if row else 0

    async def find_linked_lyrics_titles(self, audio_id: int) -> List[str]:
        """이 음원을 물고 있는 살아있는 가사 제목 목록 (삭제 거부 사유 안내용)."""
        rows = await self.db.fetch_all(
            """
            SELECT COALESCE(NULLIF(l.title, ''), s.title) AS name
            FROM song_lyrics l
            JOIN songs s ON s.id = l.song_id
            WHERE l.audio_file_id = %s AND l.deleted_at IS NULL
            LIMIT 10
            """,
            (audio_id,),
        )
        return [r["name"] for r in rows if r.get("name")]

    async def is_linked(self, audio_id: int) -> bool:
        row = await self.db.fetch_one(
            """
            SELECT 1 AS x FROM song_lyrics
             WHERE audio_file_id = %s AND deleted_at IS NULL
             LIMIT 1
            """,
            (audio_id,),
        )
        if row:
            return True
        row = await self.db.fetch_one(
            "SELECT 1 AS x FROM streamer_songbooks WHERE audio_file_id = %s LIMIT 1",
            (audio_id,),
        )
        return row is not None

    # ---------------------------------------------------------------
    # Write
    # ---------------------------------------------------------------
    async def create(
        self,
        owner_id: int,
        storage_path: str,
        mime_type: str,
        byte_size: int,
        sha256: str,
        original_filename: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> int:
        query = """
            INSERT INTO audio_files
                (owner_id, storage_path, original_filename, mime_type, byte_size, sha256, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        return await self.db.execute_query(
            query,
            (owner_id, storage_path, original_filename, mime_type, byte_size, sha256, duration_ms),
        )

    async def mark_deleted(self, audio_id: int, owner_id: int) -> bool:
        """소유자 요청에 의한 삭제 표시. 실제 파일 삭제는 리퍼가 한다."""
        query = """
            UPDATE audio_files SET deleted_at = NOW()
            WHERE id = %s AND owner_id = %s AND deleted_at IS NULL
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (audio_id, owner_id))
                return cursor.rowcount > 0

    async def claim_for_purge(self, audio_id: int) -> bool:
        """즉시 파기 표시 (연결 여부는 호출부가 이미 확인한 경우에만 쓴다).

        리퍼는 이 함수가 아니라 claim_unlinked_for_purge 를 써야 한다.
        """
        query = "UPDATE audio_files SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (audio_id,))
                return cursor.rowcount > 0

    async def claim_unlinked_for_purge(self, audio_id: int, retention_days: int) -> bool:
        """리퍼 전용 선점 — 선정 조건을 **선점하는 UPDATE 안에서 다시 확인**한다.

        대상 선정(find_unlinked)과 선점은 서로 다른 트랜잭션이다. 그 사이에 사용자가
        해당 음원을 가사에 연결하면, 조건 재확인 없이 선점할 경우 방금 저장한 가사의
        음원을 그대로 지워버린다(FK SET NULL 로 조용히 연결까지 끊긴다).
        조건을 UPDATE 의 WHERE 로 밀어넣어 판정과 선점을 원자적으로 만든다.
        """
        query = """
            UPDATE audio_files af
               SET af.deleted_at = NOW()
             WHERE af.id = %s
               AND af.deleted_at IS NULL
               AND af.created_at < (NOW() - INTERVAL %s DAY)
               AND NOT EXISTS (SELECT 1 FROM song_lyrics l
                                WHERE l.audio_file_id = af.id AND l.deleted_at IS NULL)
               AND NOT EXISTS (SELECT 1 FROM streamer_songbooks sb
                                WHERE sb.audio_file_id = af.id)
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (audio_id, retention_days))
                return cursor.rowcount > 0

    async def hard_delete(self, audio_id: int) -> None:
        """행 제거. FK 의 ON DELETE SET NULL 이 남은 참조를 정리한다."""
        await self.db.execute_query("DELETE FROM audio_files WHERE id = %s", (audio_id,))

    # ---------------------------------------------------------------
    # 리퍼용 조회
    # ---------------------------------------------------------------
    async def find_unlinked(self, retention_days: int, limit: int) -> List[Dict[str, Any]]:
        """어느 살아있는 가사/수록곡에도 연결되지 않은 채 유예 기간이 지난 파일.

        소프트 삭제된 가사는 음원을 지켜주지 않는다 (파기 우선 정책).
        """
        query = """
            SELECT af.id, af.storage_path
              FROM audio_files af
             WHERE af.deleted_at IS NULL
               AND af.created_at < (NOW() - INTERVAL %s DAY)
               AND NOT EXISTS (SELECT 1 FROM song_lyrics l
                                WHERE l.audio_file_id = af.id AND l.deleted_at IS NULL)
               AND NOT EXISTS (SELECT 1 FROM streamer_songbooks sb
                                WHERE sb.audio_file_id = af.id)
             ORDER BY af.created_at
             LIMIT %s
        """
        return await self.db.fetch_all(query, (retention_days, limit))

    async def find_marked_deleted(self, limit: int) -> List[Dict[str, Any]]:
        """이미 파기 표시된 채 남아있는 행 (중간에 죽은 리퍼의 뒷정리)."""
        query = """
            SELECT id, storage_path FROM audio_files
             WHERE deleted_at IS NOT NULL
             ORDER BY deleted_at
             LIMIT %s
        """
        return await self.db.fetch_all(query, (limit,))

    async def list_paths_by_owner(self, owner_id: int) -> List[str]:
        """계정 파기 시 디스크에서 지울 경로 목록."""
        rows = await self.db.fetch_all(
            "SELECT storage_path FROM audio_files WHERE owner_id = %s", (owner_id,)
        )
        return [r["storage_path"] for r in rows]


def get_audio_repository():
    return AudioRepository()
