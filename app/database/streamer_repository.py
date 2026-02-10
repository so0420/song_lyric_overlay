from app.database.mariadb import db_handler
from typing import Optional, Dict, Any, List
import uuid

class StreamerRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_streamer_by_user_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*, u.name, u.picture 
            FROM streamers s
            JOIN users u ON s.user_id = u.id
            WHERE s.user_id = %s
        """
        return await self.db.fetch_one(query, (user_id,))

    async def get_streamer_by_id(self, id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*, u.name, u.picture 
            FROM streamers s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = %s
        """
        return await self.db.fetch_one(query, (id,))

    async def get_streamer_by_streamer_id(self, streamer_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*, u.name, u.picture 
            FROM streamers s
            JOIN users u ON s.user_id = u.id
            WHERE s.streamer_id = %s
        """
        return await self.db.fetch_one(query, (streamer_id,))

    async def get_streamer_by_chzzk_channel_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*, u.name, u.picture 
            FROM streamers s
            JOIN users u ON s.user_id = u.id
            JOIN user_chzzk_tokens t ON s.user_id = t.user_id
            WHERE t.channel_id = %s
        """
        return await self.db.fetch_one(query, (channel_id,))

    async def get_streamer_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT s.*, u.name, u.picture 
            FROM streamers s
            JOIN users u ON s.user_id = u.id
            WHERE s.slug = %s
        """
        return await self.db.fetch_one(query, (slug,))

    async def is_slug_taken(self, slug: str, exclude_user_id: Optional[int] = None) -> bool:
        query = "SELECT 1 FROM streamers WHERE slug = %s"
        params = [slug]
        if exclude_user_id:
            query += " AND user_id != %s"
            params.append(exclude_user_id)
        
        result = await self.db.fetch_one(query, tuple(params))
        return result is not None

    async def create_streamer_profile(self, user_id: int, slug: str):
        from app.utils.token import generate_user_token
        token = generate_user_token()
        streamer_id = str(uuid.uuid4())
        
        query = """
            INSERT INTO streamers (user_id, streamer_id, slug, token)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE updated_at = NOW()
        """
        return await self.db.execute_query(query, (user_id, streamer_id, slug, token))

def get_streamer_repository():
    return StreamerRepository()
