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

    async def get_lyrics_by_song_id_with_favorites(self, song_id: int, user_id: int) -> List[Dict[str, Any]]:
        """특정 노래의 가사 목록 조회 (즐겨찾기 정보 포함)"""
        query = """
            SELECT
                l.id,
                l.owner_id,
                u.name as owner_name,
                l.title,
                l.mr_youtube_video_id,
                l.is_verified,
                l.likes_count,
                l.created_at,
                l.updated_at,
                (SELECT COUNT(*) FROM user_lyrics_favorites WHERE lyrics_id = l.id) as favorites_count,
                CASE WHEN ulf.id IS NOT NULL THEN 1 ELSE 0 END as is_favorited
            FROM song_lyrics l
            LEFT JOIN users u ON l.owner_id = u.id
            LEFT JOIN user_lyrics_favorites ulf ON l.id = ulf.lyrics_id AND ulf.user_id = %s
            WHERE l.song_id = %s AND l.is_public = 1
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
        """
        return await self.db.fetch_all(query, (user_id, song_id))

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

    async def check_title_duplicate(self, owner_id: int, song_id: Optional[int], title: str, exclude_id: int = None) -> bool:
        """가사 제목 중복 체크 (내 가사들 중에서)"""
        if song_id:
            # 새로 생성할 때
            query = """
                SELECT id FROM song_lyrics
                WHERE owner_id = %s AND song_id = %s AND title = %s
            """
            params = (owner_id, song_id, title)
        else:
            # 수정할 때 (song_id 없이)
            query = """
                SELECT id FROM song_lyrics
                WHERE owner_id = %s AND title = %s
            """
            params = (owner_id, title)

        if exclude_id:
            query += " AND id != %s"
            params = params + (exclude_id,)

        result = await self.db.fetch_one(query, params)
        return result is not None

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

    # 즐겨찾기 관련 메서드
    async def add_favorite(self, user_id: int, lyrics_id: int) -> bool:
        """가사 즐겨찾기 추가"""
        try:
            query = "INSERT INTO user_lyrics_favorites (user_id, lyrics_id) VALUES (%s, %s)"
            await self.db.execute_query(query, (user_id, lyrics_id))
            return True
        except Exception:
            # 중복 키 오류 (이미 즐겨찾기 됨)
            return False

    async def remove_favorite(self, user_id: int, lyrics_id: int) -> bool:
        """가사 즐겨찾기 제거"""
        query = "DELETE FROM user_lyrics_favorites WHERE user_id = %s AND lyrics_id = %s"
        await self.db.execute_query(query, (user_id, lyrics_id))
        return True

    async def get_my_favorites(self, user_id: int) -> List[Dict[str, Any]]:
        """내 즐겨찾기 가사 목록 조회"""
        query = """
            SELECT
                l.id,
                l.owner_id,
                u.name as owner_name,
                l.song_id,
                s.title as song_title,
                s.song_external_id,
                a.name as artist_name,
                l.title,
                l.mr_youtube_video_id,
                l.is_verified,
                l.likes_count,
                l.updated_at,
                ulf.created_at as favorited_at,
                (SELECT COUNT(*) FROM user_lyrics_favorites WHERE lyrics_id = l.id) as favorites_count
            FROM user_lyrics_favorites ulf
            JOIN song_lyrics l ON ulf.lyrics_id = l.id
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN users u ON l.owner_id = u.id
            WHERE ulf.user_id = %s AND l.is_public = 1
            ORDER BY ulf.created_at DESC
        """
        return await self.db.fetch_all(query, (user_id,))

    async def is_favorited(self, user_id: int, lyrics_id: int) -> bool:
        """즐겨찾기 여부 확인"""
        query = "SELECT id FROM user_lyrics_favorites WHERE user_id = %s AND lyrics_id = %s"
        result = await self.db.fetch_one(query, (user_id, lyrics_id))
        return result is not None

    async def search_songs_with_lyrics(self, query_term: str, limit: int = 20) -> List[Dict[str, Any]]:
        """공개된 가사가 있는 노래 검색"""
        search_pattern = f"%{query_term}%"
        query = """
            SELECT
                s.id as song_id,
                s.title as track_name,
                s.song_external_id,
                s.cover_image_url as artwork_url,
                a.name as artist_name,
                a.artist_external_id as artist_id,
                COUNT(l.id) as lyrics_count
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.title LIKE %s OR a.name LIKE %s
            GROUP BY s.id
            ORDER BY lyrics_count DESC, s.title ASC
            LIMIT %s
        """
        return await self.db.fetch_all(query, (search_pattern, search_pattern, limit))

def get_lyrics_repository():
    return LyricsRepository()
