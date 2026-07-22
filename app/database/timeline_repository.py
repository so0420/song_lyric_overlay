from app.database.mariadb import db_handler
from typing import List, Dict, Any
from datetime import datetime

# 타임라인 보관 기간 (일). 이보다 오래된 기록은 새 기록 저장 시 자동 정리한다.
RETENTION_DAYS = 31


class TimelineRepository:
    """노래 타임라인 기록 저장소 (singing_timeline_records)

    치지직 연동 유저가 방송 중 부른 곡을 방송 시작(openDate) 기준 경과 시간과 함께 기록.
    최근 1달치만 보관한다.
    """

    def __init__(self, db=db_handler):
        self.db = db

    async def add_record(
        self, user_id: int, open_date: datetime, elapsed_seconds: int, title: str
    ) -> int:
        """타임라인 기록 1건 저장. 저장 후 보관 기간이 지난 오래된 기록을 정리한다.

        open_date 는 tz-aware 여도 되며, DATETIME 컬럼에는 naive(KST) 로 저장된다.
        """
        if open_date.tzinfo is not None:
            open_date = open_date.replace(tzinfo=None)
        query = """
            INSERT INTO singing_timeline_records (user_id, open_date, elapsed_seconds, title)
            VALUES (%s, %s, %s, %s)
        """
        record_id = await self.db.execute_query(
            query, (user_id, open_date, elapsed_seconds, title)
        )
        await self._prune_old(user_id)
        return record_id

    async def _prune_old(self, user_id: int) -> None:
        """보관 기간(RETENTION_DAYS)이 지난 이 유저의 기록 삭제."""
        query = """
            DELETE FROM singing_timeline_records
            WHERE user_id = %s AND created_at < (NOW() - INTERVAL %s DAY)
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id, RETENTION_DAYS))

    async def list_records(self, user_id: int) -> List[Dict[str, Any]]:
        """유저의 최근 1달 기록을 방송(open_date)·경과시간 순으로 반환.

        방송 최신순(open_date DESC), 방송 내에서는 경과시간 오름차순(부른 순서)으로 정렬.
        """
        query = """
            SELECT id, open_date, elapsed_seconds, title, created_at
            FROM singing_timeline_records
            WHERE user_id = %s AND created_at >= (NOW() - INTERVAL %s DAY)
            ORDER BY open_date DESC, elapsed_seconds ASC, id ASC
        """
        return await self.db.fetch_all(query, (user_id, RETENTION_DAYS))

    async def delete_record(self, user_id: int, record_id: int) -> bool:
        """기록 1건 삭제 (본인 것만). 삭제되면 True."""
        query = "DELETE FROM singing_timeline_records WHERE id = %s AND user_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (record_id, user_id))
                return cursor.rowcount > 0


def get_timeline_repository() -> TimelineRepository:
    return TimelineRepository()
