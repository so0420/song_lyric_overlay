from app.database.mariadb import db_handler
from typing import List, Dict, Any, Optional, Tuple
from app.utils.log import logger

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
            WHERE l.song_id = %s AND l.is_public = 1 AND l.deleted_at IS NULL
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
        """
        return await self.db.fetch_all(query, (song_id,))

    async def get_lyrics_by_song_id_with_favorites(self, song_id: int, user_id: int) -> List[Dict[str, Any]]:
        """특정 노래의 가사 목록 조회 (즐겨찾기 정보 포함)"""
        # N+1 쿼리 개선: 서브쿼리 대신 JOIN + GROUP BY 사용
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
                COUNT(DISTINCT fav.id) as favorites_count,
                MAX(CASE WHEN ulf.id IS NOT NULL THEN 1 ELSE 0 END) as is_favorited
            FROM song_lyrics l
            LEFT JOIN users u ON l.owner_id = u.id
            LEFT JOIN user_lyrics_favorites fav ON l.id = fav.lyrics_id
            LEFT JOIN user_lyrics_favorites ulf ON l.id = ulf.lyrics_id AND ulf.user_id = %s
            WHERE l.song_id = %s AND l.is_public = 1 AND l.deleted_at IS NULL
            GROUP BY l.id, l.owner_id, u.name, l.title, l.mr_youtube_video_id,
                     l.is_verified, l.likes_count, l.created_at, l.updated_at
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
            WHERE l.id = %s AND l.deleted_at IS NULL
        """
        return await self.db.fetch_one(query, (lyrics_id,))

    async def get_my_lyrics(self, owner_id: int, offset: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """자신이 작성한 가사 목록 조회 (페이지네이션 지원)"""
        query = """
            SELECT l.*, s.title as song_title, s.song_external_id, s.cover_image_url, a.name as artist_name
            FROM song_lyrics l
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE l.owner_id = %s AND l.deleted_at IS NULL
            ORDER BY l.updated_at DESC
            LIMIT %s OFFSET %s
        """
        items = await self.db.fetch_all(query, (owner_id, limit, offset))

        # 전체 개수 조회
        count_query = "SELECT COUNT(*) as total FROM song_lyrics WHERE owner_id = %s AND deleted_at IS NULL"
        count_result = await self.db.fetch_one(count_query, (owner_id,))
        total = count_result['total'] if count_result else 0

        return items, total

    async def check_title_duplicate(self, owner_id: int, song_id: Optional[int], title: str, exclude_id: int = None) -> bool:
        """가사 제목 중복 체크 (내 가사들 중에서)"""
        if song_id:
            # 새로 생성할 때
            query = """
                SELECT id FROM song_lyrics
                WHERE owner_id = %s AND song_id = %s AND title = %s AND deleted_at IS NULL
            """
            params = (owner_id, song_id, title)
        else:
            # 수정할 때 (song_id 없이)
            query = """
                SELECT id FROM song_lyrics
                WHERE owner_id = %s AND title = %s AND deleted_at IS NULL
            """
            params = (owner_id, title)

        if exclude_id:
            query += " AND id != %s"
            params = params + (exclude_id,)

        result = await self.db.fetch_one(query, params)
        return result is not None

    async def create_lyrics(self, owner_id, song_id: int, mr_youtube_video_id: str, lyrics_data: str, title: str = None) -> int:
        query = """
            INSERT INTO song_lyrics (owner_id, song_id, title, mr_youtube_video_id, lyrics_data)
            VALUES (%s, %s, %s, %s, %s)
        """
        return await self.db.execute_query(query, (owner_id, song_id, title, mr_youtube_video_id, lyrics_data))

    async def update_lyrics(self, lyrics_id: int, owner_id, mr_youtube_video_id: str, lyrics_data: str, title: str = None) -> bool:
        if owner_id is None:
            query = """
                UPDATE song_lyrics
                SET title = %s, mr_youtube_video_id = %s, lyrics_data = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND owner_id IS NULL
            """
            params = (title, mr_youtube_video_id, lyrics_data, lyrics_id)
        else:
            query = """
                UPDATE song_lyrics
                SET title = %s, mr_youtube_video_id = %s, lyrics_data = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND owner_id = %s
            """
            params = (title, mr_youtube_video_id, lyrics_data, lyrics_id, owner_id)

        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                if cursor.rowcount == 0:
                    return False
        return True

    async def delete_lyrics(self, lyrics_id: int, owner_id: int) -> bool:
        """소프트 삭제: deleted_at 설정"""
        query = "UPDATE song_lyrics SET deleted_at = NOW() WHERE id = %s AND owner_id = %s AND deleted_at IS NULL"
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
            WHERE s.song_external_id IN ({format_strings}) AND l.is_public = 1 AND l.deleted_at IS NULL
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
        except Exception as e:
            error_str = str(e).lower()
            if "duplicate" not in error_str and "unique" not in error_str:
                logger.error(f"Favorite add error for user {user_id}, lyrics {lyrics_id}: {e}")
            return False

    async def remove_favorite(self, user_id: int, lyrics_id: int) -> bool:
        """가사 즐겨찾기 제거"""
        query = "DELETE FROM user_lyrics_favorites WHERE user_id = %s AND lyrics_id = %s"
        await self.db.execute_query(query, (user_id, lyrics_id))
        return True

    async def get_my_favorites(self, user_id: int, offset: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """내 즐겨찾기 가사 목록 조회 (페이지네이션 지원)"""
        # N+1 쿼리 개선: 서브쿼리 대신 JOIN + GROUP BY 사용
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
                COUNT(DISTINCT fav.id) as favorites_count
            FROM user_lyrics_favorites ulf
            JOIN song_lyrics l ON ulf.lyrics_id = l.id
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN users u ON l.owner_id = u.id
            LEFT JOIN user_lyrics_favorites fav ON l.id = fav.lyrics_id
            WHERE ulf.user_id = %s AND l.is_public = 1 AND l.deleted_at IS NULL
            GROUP BY l.id, l.owner_id, u.name, l.song_id, s.title, s.song_external_id,
                     a.name, l.title, l.mr_youtube_video_id, l.is_verified,
                     l.likes_count, l.updated_at, ulf.created_at
            ORDER BY ulf.created_at DESC
            LIMIT %s OFFSET %s
        """
        items = await self.db.fetch_all(query, (user_id, limit, offset))

        # 전체 개수 조회
        count_query = """
            SELECT COUNT(*) as total
            FROM user_lyrics_favorites ulf
            JOIN song_lyrics l ON ulf.lyrics_id = l.id
            WHERE ulf.user_id = %s AND l.is_public = 1 AND l.deleted_at IS NULL
        """
        count_result = await self.db.fetch_one(count_query, (user_id,))
        total = count_result['total'] if count_result else 0

        return items, total

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
                COUNT(l.id) as lyrics_count,
                MAX(l.updated_at) as last_updated
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
            GROUP BY s.id
            ORDER BY last_updated DESC
            LIMIT %s
        """
        return await self.db.fetch_all(query, (search_pattern, search_pattern, search_pattern, limit))

    async def search_all_songs_with_lyrics(
        self, query_term: str, offset: int = 0, limit: int = 20
    ) -> Dict[str, Any]:
        """공개된 가사가 있는 노래 검색 (음원 + 커스텀 분리 반환, 페이지네이션 지원)"""
        search_pattern = f"%{query_term}%"

        # 음원 노래 검색 (song_external_id가 'it_'로 시작)
        itunes_query = """
            SELECT
                s.id as song_id,
                s.title as track_name,
                s.song_external_id,
                s.cover_image_url as artwork_url,
                a.name as artist_name,
                a.artist_external_id as artist_id,
                COUNT(l.id) as lyrics_count,
                MAX(l.updated_at) as last_updated
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.song_external_id LIKE 'it_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
            ORDER BY last_updated DESC
            LIMIT %s OFFSET %s
        """
        itunes_results = await self.db.fetch_all(itunes_query, (search_pattern, search_pattern, search_pattern, limit, offset))

        # 음원 전체 개수
        itunes_count_query = """
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.song_external_id LIKE 'it_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
        """
        itunes_count = await self.db.fetch_one(itunes_count_query, (search_pattern, search_pattern, search_pattern))

        # 커스텀 노래 검색 (song_external_id가 'custom_'로 시작)
        custom_query = """
            SELECT
                s.id as song_id,
                s.title as track_name,
                s.song_external_id,
                s.cover_image_url as artwork_url,
                a.name as artist_name,
                a.artist_external_id as artist_id,
                COUNT(l.id) as lyrics_count,
                MAX(l.updated_at) as last_updated
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.song_external_id LIKE 'custom_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
            ORDER BY last_updated DESC
            LIMIT %s OFFSET %s
        """
        custom_results = await self.db.fetch_all(custom_query, (search_pattern, search_pattern, search_pattern, limit, offset))

        # 커스텀 전체 개수
        custom_count_query = """
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.song_external_id LIKE 'custom_%%'
              AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
        """
        custom_count = await self.db.fetch_one(custom_count_query, (search_pattern, search_pattern, search_pattern))

        return {
            "itunes": {
                "items": itunes_results,
                "total": itunes_count['total'] if itunes_count else 0
            },
            "custom": {
                "items": custom_results,
                "total": custom_count['total'] if custom_count else 0
            },
            "offset": offset,
            "limit": limit
        }

    async def get_all_songs_with_lyrics(
        self, offset: int = 0, limit: int = 20, song_type: str = "all", search: str = None
    ) -> Dict[str, Any]:
        """공개된 가사가 있는 모든 노래 조회 (페이지네이션, 검색 지원)"""
        type_filter = ""
        if song_type == "itunes":
            type_filter = "AND s.song_external_id LIKE 'it_%%'"
        elif song_type == "custom":
            type_filter = "AND s.song_external_id LIKE 'custom_%%'"

        search_filter = ""
        params = []
        if search:
            search_filter = "AND (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)"
            pattern = f"%{search}%"
            params = [pattern, pattern, pattern]

        query = f"""
            SELECT
                s.id as song_id,
                s.title as track_name,
                s.song_external_id,
                s.cover_image_url as artwork_url,
                a.name as artist_name,
                a.artist_external_id as artist_id,
                COUNT(l.id) as lyrics_count,
                MAX(l.updated_at) as last_updated
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE 1=1 {type_filter} {search_filter}
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
            ORDER BY last_updated DESC
            LIMIT %s OFFSET %s
        """
        items = await self.db.fetch_all(query, (*params, limit, offset))

        count_query = f"""
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.is_public = 1 AND l.deleted_at IS NULL
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE 1=1 {type_filter} {search_filter}
        """
        count_result = await self.db.fetch_one(count_query, (*params,) if params else ())
        total = count_result['total'] if count_result else 0

        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total
        }

    async def find_songs_by_lyrics_title(self, query_term: str, song_type_prefix: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """가사 버전 제목으로 노래 검색 (공개 가사의 제목과 매칭되는 노래 반환)"""
        search_pattern = f"%{query_term}%"

        type_filter = ""
        params = [search_pattern]
        if song_type_prefix:
            type_filter = "AND s.song_external_id LIKE %s"
            params.append(f"{song_type_prefix}%")

        params.append(limit)

        query = f"""
            SELECT DISTINCT
                s.id,
                s.song_external_id,
                s.title,
                s.cover_image_url,
                a.name as artist_name
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND l.is_public = 1
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE l.title LIKE %s {type_filter}
            ORDER BY s.title ASC
            LIMIT %s
        """
        return await self.db.fetch_all(query, tuple(params))

    # 메모 관련 메서드
    async def get_memo(self, user_id: int, lyrics_id: int) -> Optional[Dict[str, Any]]:
        """가사에 대한 사용자 메모 조회"""
        query = "SELECT memo, updated_at FROM user_lyrics_memos WHERE user_id = %s AND lyrics_id = %s"
        return await self.db.fetch_one(query, (user_id, lyrics_id))

    async def save_memo(self, user_id: int, lyrics_id: int, memo: str) -> bool:
        """가사에 대한 사용자 메모 저장 (UPSERT)"""
        query = """
            INSERT INTO user_lyrics_memos (user_id, lyrics_id, memo)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE memo = VALUES(memo), updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute_query(query, (user_id, lyrics_id, memo))
        return True

    async def delete_memo(self, user_id: int, lyrics_id: int) -> bool:
        """가사에 대한 사용자 메모 삭제"""
        query = "DELETE FROM user_lyrics_memos WHERE user_id = %s AND lyrics_id = %s"
        await self.db.execute_query(query, (user_id, lyrics_id))
        return True

def get_lyrics_repository():
    return LyricsRepository()
