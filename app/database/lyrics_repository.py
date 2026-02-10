from app.database.mariadb import db_handler
from typing import List, Dict, Any, Optional

class LyricsRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_lyrics_by_song_id(self, song_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT 
                l.id,
                l.owner_id,
                u.name as owner_name,
                l.title,
                l.mr_youtube_video_id,
                l.is_verified,
                l.likes_count,
                l.created_at
            FROM song_lyrics l
            LEFT JOIN users u ON l.owner_id = u.id
            WHERE l.song_id = %s AND l.is_public = 1
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
        """
        return await self.db.fetch_all(query, (song_id,))

    async def get_lyrics_by_external_id(self, song_external_id: str) -> List[Dict[str, Any]]:
        # First get song_id
        song = await self.db.fetch_one("SELECT id FROM songs WHERE song_external_id = %s", (song_external_id,))
        if not song:
            return []
        return await self.get_lyrics_by_song_id(song['id'])

    async def get_lyrics_by_id(self, lyrics_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT l.*, s.title as song_title, s.song_external_id, a.name as artist_name
            FROM song_lyrics l
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE l.id = %s
        """
        return await self.db.fetch_one(query, (lyrics_id,))

    async def get_my_lyrics(self, owner_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT l.*, s.title as song_title, s.song_external_id, a.name as artist_name
            FROM song_lyrics l
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE l.owner_id = %s
            ORDER BY l.updated_at DESC
        """
        return await self.db.fetch_all(query, (owner_id,))

    async def create_lyrics(self, owner_id: int, song_id: int, mr_youtube_video_id: str, lyrics_data: str, title: str = None) -> int:
        query = """
            INSERT INTO song_lyrics (owner_id, song_id, title, mr_youtube_video_id, lyrics_data)
            VALUES (%s, %s, %s, %s, %s)
        """
        return await self.db.execute_query(query, (owner_id, song_id, title, mr_youtube_video_id, lyrics_data))

    async def update_lyrics(self, lyrics_id: int, owner_id: int, mr_youtube_video_id: str, lyrics_data: str, title: str = None) -> bool:
        query = """
            UPDATE song_lyrics 
            SET title = %s, mr_youtube_video_id = %s, lyrics_data = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND owner_id = %s
        """
        await self.db.execute_query(query, (title, mr_youtube_video_id, lyrics_data, lyrics_id, owner_id))
        return True

    async def delete_lyrics(self, lyrics_id: int, owner_id: int) -> bool:
        query = "DELETE FROM song_lyrics WHERE id = %s AND owner_id = %s"
        await self.db.execute_query(query, (lyrics_id, owner_id))
        return True

    async def get_lyrics_counts(self, external_ids: List[str]) -> Dict[str, int]:
        if not external_ids:
            return {}
        
        format_strings = ','.join(['%s'] * len(external_ids))
        query = f"""
            SELECT s.song_external_id, COUNT(l.id) as count
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id
            WHERE s.song_external_id IN ({format_strings}) AND l.is_public = 1
            GROUP BY s.song_external_id
        """
        results = await self.db.fetch_all(query, tuple(external_ids))
        return {r['song_external_id']: r['count'] for r in results}

def get_lyrics_repository():
    return LyricsRepository()
