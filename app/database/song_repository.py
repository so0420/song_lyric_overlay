from app.database.mariadb import db_handler
from typing import Optional, Dict, Any
import uuid

class SongRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_or_create_artist(self, name: str, external_id: str) -> int:
        query = """
            INSERT INTO artists (name, artist_external_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE name = VALUES(name)
        """
        await self.db.execute_query(query, (name, external_id))
        res = await self.db.fetch_one("SELECT id FROM artists WHERE artist_external_id = %s", (external_id,))
        return res['id']

    async def get_or_create_song(self, title: str, external_id: str, artist_id: int, image_url: str = None) -> int:
        query = """
            INSERT INTO songs (title, song_external_id, artist_id, cover_image_url)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE title = VALUES(title), cover_image_url = VALUES(cover_image_url)
        """
        await self.db.execute_query(query, (title, external_id, artist_id, image_url))
        res = await self.db.fetch_one("SELECT id FROM songs WHERE song_external_id = %s", (external_id,))
        
        return res['id']

    async def create_custom_song(self, title: str, artist_name: str, image_url: str = None, owner_id: int = None) -> int:
        custom_ext_id = f"custom_{uuid.uuid4()}"
        artist_ext_id = f"custom_artist_{uuid.uuid4()}" # Simple approach for custom artists
        
        artist_id = await self.get_or_create_artist(artist_name, artist_ext_id)
        
        query = """
            INSERT INTO songs (title, song_external_id, artist_id, cover_image_url, owner_id)
            VALUES (%s, %s, %s, %s, %s)
        """
        song_id = await self.db.execute_query(query, (title, custom_ext_id, artist_id, image_url, owner_id))
        
        return song_id

    async def get_song_by_external_id(self, external_id: str):
        query = """
            SELECT s.*, a.name as artist_name, u.name as owner_name
            FROM songs s 
            LEFT JOIN artists a ON s.artist_id = a.id 
            LEFT JOIN users u ON s.owner_id = u.id
            WHERE s.song_external_id = %s
        """
        return await self.db.fetch_one(query, (external_id,))

    async def get_song_external_id(self, song_id: int) -> Optional[str]:
        res = await self.db.fetch_one("SELECT song_external_id FROM songs WHERE id = %s", (song_id,))
        return res['song_external_id'] if res else None

def get_song_repository():
    return SongRepository()
