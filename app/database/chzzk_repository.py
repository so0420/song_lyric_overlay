from app.database.mariadb import db_handler
from typing import Optional, Dict, Any, List


class ChzzkChannelRepository:
    """유저 ↔ 치지직 채널(uid) 매핑 저장소 (user_chzzk_channels)

    OAuth/토큰 관리는 jamkubot 이 대행하므로 우리는 채널 uid 만 보관한다.
    """

    def __init__(self, db=db_handler):
        self.db = db

    async def link(self, user_id: int, channel_id: str, channel_name: Optional[str] = None) -> None:
        """유저-채널 연동 저장/갱신 (user_id 기준 UPSERT)"""
        query = """
            INSERT INTO user_chzzk_channels (user_id, channel_id, channel_name)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                channel_id = VALUES(channel_id),
                channel_name = VALUES(channel_name)
        """
        await self.db.execute_query(query, (user_id, channel_id, channel_name))

    async def get(self, user_id: int) -> Optional[Dict[str, Any]]:
        """유저의 연동 채널 조회"""
        query = "SELECT * FROM user_chzzk_channels WHERE user_id = %s"
        return await self.db.fetch_one(query, (user_id,))

    async def delete(self, user_id: int) -> int:
        """연동 해제. 삭제된 행 수 반환."""
        query = "DELETE FROM user_chzzk_channels WHERE user_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id,))
                return cursor.rowcount

    async def get_all_channel_ids(self) -> List[str]:
        """연동된 모든 채널 uid 목록 (릴레이 구독 대상)"""
        rows = await self.db.fetch_all("SELECT channel_id FROM user_chzzk_channels", ())
        return [r["channel_id"] for r in rows]


def get_chzzk_channel_repository() -> ChzzkChannelRepository:
    return ChzzkChannelRepository()
