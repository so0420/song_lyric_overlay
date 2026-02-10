from app.database.mariadb import db_handler
from typing import Optional, Dict, Any, List


class FollowRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_followed_streamers(self, user_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """사용자가 즐겨찾기한 스트리머 목록을 가져옵니다."""
        query = """
            SELECT s.streamer_id, s.slug, u.name, u.picture, f.created_at as followed_at
            FROM follows f
            JOIN streamers s ON f.streamer_id = s.id
            JOIN users u ON s.user_id = u.id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        
        return await self.db.fetch_all(query, (user_id,))

    async def is_following(self, user_id: int, streamer_id: int) -> bool:
        """특정 스트리머를 즐겨찾기 했는지 확인합니다."""
        query = "SELECT 1 FROM follows WHERE user_id = %s AND streamer_id = %s"
        result = await self.db.fetch_one(query, (user_id, streamer_id))
        return result is not None

    async def follow_streamer(self, user_id: int, streamer_id: int) -> bool:
        """스트리머를 즐겨찾기에 추가합니다."""
        query = """
            INSERT INTO follows (user_id, streamer_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE updated_at = NOW()
        """
        await self.db.execute_query(query, (user_id, streamer_id))
        return True

    async def unfollow_streamer(self, user_id: int, streamer_id: int) -> bool:
        """스트리머를 즐겨찾기에서 삭제합니다."""
        query = "DELETE FROM follows WHERE user_id = %s AND streamer_id = %s"
        await self.db.execute_query(query, (user_id, streamer_id))
        return True

    async def get_follower_count(self, streamer_id: int) -> int:
        """스트리머의 즐겨찾기 수를 가져옵니다."""
        query = "SELECT COUNT(*) as count FROM follows WHERE streamer_id = %s"
        result = await self.db.fetch_one(query, (streamer_id,))
        return result['count'] if result else 0

    async def get_streamer_internal_id(self, streamer_external_id: str) -> Optional[int]:
        """외부 streamer_id로 내부 id를 조회합니다."""
        query = "SELECT id FROM streamers WHERE streamer_id = %s"
        result = await self.db.fetch_one(query, (streamer_external_id,))
        return result['id'] if result else None


def get_follow_repository():
    return FollowRepository()
