from app.database.mariadb import db_handler
from typing import List, Dict, Any, Optional, Tuple
from app.utils.log import logger

class LyricsRepository:
    def __init__(self, db=db_handler):
        self.db = db

    # ---------------------------------------------------------------
    # Visibility helper
    # ---------------------------------------------------------------
    @staticmethod
    def visibility_where(user_id: Optional[int], is_admin: bool, alias: str = "l") -> Tuple[str, list]:
        """
        리스트 쿼리용 WHERE 조각을 돌려준다.

        Args:
            user_id: 로그인 사용자 ID (익명이면 None)
            is_admin: 관리자 여부
            alias: song_lyrics 테이블의 alias (없으면 "" 전달)

        Returns:
            (sql_fragment, params) — params 는 기존 쿼리 params 에 splice
        """
        prefix = f"{alias}." if alias else ""
        if is_admin:
            return "1=1", []
        if user_id is None:
            return f"{prefix}visibility='public'", []
        sql = (
            f"({prefix}visibility='public' "
            f" OR ({prefix}visibility IN ('private','whitelist') AND {prefix}owner_id=%s) "
            f" OR ({prefix}visibility='whitelist' "
            f"     AND EXISTS (SELECT 1 FROM lyrics_whitelist w "
            f"                 WHERE w.lyrics_id={prefix}id AND w.user_id=%s)))"
        )
        return sql, [user_id, user_id]

    # ---------------------------------------------------------------
    # Read
    # ---------------------------------------------------------------
    async def get_lyrics_by_song_id(
        self, song_id: int, user_id: Optional[int] = None, is_admin: bool = False
    ) -> List[Dict[str, Any]]:
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        # 같은 제목+가수인 형제 곡(앨범아트만 다른 중복 레코드)의 가사까지 함께 조회
        query = f"""
            SELECT
                l.id,
                l.owner_id,
                u.name as owner_name,
                l.title,
                l.mr_youtube_video_id,
                l.audio_file_id,
                l.is_verified,
                l.visibility,
                l.likes_count,
                l.created_at
            FROM song_lyrics l
            JOIN songs sx ON l.song_id = sx.id
            JOIN songs sref ON sref.id = %s AND sx.title = sref.title AND (sx.artist_id <=> sref.artist_id)
            LEFT JOIN users u ON l.owner_id = u.id
            WHERE l.deleted_at IS NULL AND {vis_where}
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
        """
        return await self.db.fetch_all(query, (song_id, *vis_params))

    async def get_lyrics_by_song_id_with_favorites(
        self, song_id: int, user_id: int, is_admin: bool = False
    ) -> List[Dict[str, Any]]:
        """특정 노래의 가사 목록 조회 (즐겨찾기 정보 포함)"""
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        query = f"""
            SELECT
                l.id,
                l.owner_id,
                u.name as owner_name,
                l.title,
                l.mr_youtube_video_id,
                l.audio_file_id,
                l.is_verified,
                l.visibility,
                l.likes_count,
                l.created_at,
                l.updated_at,
                COUNT(DISTINCT fav.id) as favorites_count,
                MAX(CASE WHEN ulf.id IS NOT NULL THEN 1 ELSE 0 END) as is_favorited
            FROM song_lyrics l
            JOIN songs sx ON l.song_id = sx.id
            JOIN songs sref ON sref.id = %s AND sx.title = sref.title AND (sx.artist_id <=> sref.artist_id)
            LEFT JOIN users u ON l.owner_id = u.id
            LEFT JOIN user_lyrics_favorites fav ON l.id = fav.lyrics_id
            LEFT JOIN user_lyrics_favorites ulf ON l.id = ulf.lyrics_id AND ulf.user_id = %s
            WHERE l.deleted_at IS NULL AND {vis_where}
            GROUP BY l.id, l.owner_id, u.name, l.title, l.mr_youtube_video_id, l.audio_file_id,
                     l.is_verified, l.visibility, l.likes_count, l.created_at, l.updated_at
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
        """
        return await self.db.fetch_all(query, (song_id, user_id, *vis_params))

    async def get_lyrics_by_external_id(
        self, song_external_id: str, user_id: Optional[int] = None, is_admin: bool = False
    ) -> List[Dict[str, Any]]:
        song = await self.db.fetch_one("SELECT id FROM songs WHERE song_external_id = %s", (song_external_id,))
        if not song:
            return []
        return await self.get_lyrics_by_song_id(song['id'], user_id=user_id, is_admin=is_admin)

    async def is_canonical_sibling(self, song_id_a: int, song_id_b: int) -> bool:
        """두 곡이 같은 제목+가수(형제 곡)인지 (같은 곡이면 True)"""
        if song_id_a == song_id_b:
            return True
        query = """
            SELECT 1 FROM songs a
            JOIN songs b ON a.title = b.title AND (a.artist_id <=> b.artist_id)
            WHERE a.id = %s AND b.id = %s LIMIT 1
        """
        return await self.db.fetch_one(query, (song_id_a, song_id_b)) is not None

    async def get_best_public_lyrics_id_for_song(self, song_id: int) -> Optional[int]:
        """해당 곡(및 같은 제목+가수 형제 곡)의 가장 적합한 공개 가사 id (없으면 None).

        노래책에 곡을 추가할 때 기존 가사를 자동 연결하는 데 사용.
        """
        query = """
            SELECT l.id
            FROM song_lyrics l
            JOIN songs sx ON l.song_id = sx.id
            JOIN songs sref ON sref.id = %s AND sx.title = sref.title AND (sx.artist_id <=> sref.artist_id)
            WHERE l.deleted_at IS NULL AND l.visibility = 'public'
            ORDER BY l.is_verified DESC, l.likes_count DESC, l.created_at DESC
            LIMIT 1
        """
        row = await self.db.fetch_one(query, (song_id,))
        return row["id"] if row else None

    async def get_lyrics_by_id(self, lyrics_id: int) -> Optional[Dict[str, Any]]:
        """단일 가사 조회 (visibility 필터 없음 — 호출 측에서 can_view_lyrics 로 검사).
        반환 row 에 visibility, owner_id 포함되므로 접근 판정 가능.
        """
        query = """
            SELECT l.*, s.title as song_title, s.song_external_id, s.cover_image_url,
                   a.name as artist_name,
                   af.mime_type as audio_mime_type,
                   af.byte_size as audio_byte_size,
                   af.duration_ms as audio_duration_ms,
                   af.original_filename as audio_original_filename
            FROM song_lyrics l
            JOIN songs s ON l.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN audio_files af ON af.id = l.audio_file_id AND af.deleted_at IS NULL
            WHERE l.id = %s AND l.deleted_at IS NULL
        """
        return await self.db.fetch_one(query, (lyrics_id,))

    async def get_my_lyrics(self, owner_id: int, offset: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """자신이 작성한 가사 목록 조회 (visibility 무관, 본인 것 전부)"""
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

        count_query = "SELECT COUNT(*) as total FROM song_lyrics WHERE owner_id = %s AND deleted_at IS NULL"
        count_result = await self.db.fetch_one(count_query, (owner_id,))
        total = count_result['total'] if count_result else 0

        return items, total

    async def check_title_duplicate(self, owner_id: int, song_id: Optional[int], title: str, exclude_id: int = None) -> bool:
        """가사 제목 중복 체크 (내 가사들 중에서)"""
        if song_id:
            query = """
                SELECT id FROM song_lyrics
                WHERE owner_id = %s AND song_id = %s AND title = %s AND deleted_at IS NULL
            """
            params = (owner_id, song_id, title)
        else:
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

    # ---------------------------------------------------------------
    # Write
    # ---------------------------------------------------------------
    async def create_lyrics(
        self,
        owner_id,
        song_id: int,
        mr_youtube_video_id: Optional[str],
        lyrics_data: str,
        title: str = None,
        visibility: str = "public",
        audio_file_id: Optional[int] = None,
    ) -> int:
        query = """
            INSERT INTO song_lyrics
                (owner_id, song_id, title, mr_youtube_video_id, audio_file_id, lyrics_data, visibility)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        return await self.db.execute_query(
            query,
            (owner_id, song_id, title, mr_youtube_video_id, audio_file_id, lyrics_data, visibility),
        )

    async def update_lyrics(
        self,
        lyrics_id: int,
        owner_id,
        mr_youtube_video_id: Optional[str],
        lyrics_data: str,
        title: str = None,
        audio_file_id: Optional[int] = None,
    ) -> bool:
        # 두 소스 컬럼을 항상 함께 쓴다 — 그래야 유튜브 → 음원으로 바꿀 때 옛 값이 지워진다
        if owner_id is None:
            query = """
                UPDATE song_lyrics
                SET title = %s, mr_youtube_video_id = %s, audio_file_id = %s,
                    lyrics_data = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND owner_id IS NULL
            """
            params = (title, mr_youtube_video_id, audio_file_id, lyrics_data, lyrics_id)
        else:
            query = """
                UPDATE song_lyrics
                SET title = %s, mr_youtube_video_id = %s, audio_file_id = %s,
                    lyrics_data = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND owner_id = %s
            """
            params = (title, mr_youtube_video_id, audio_file_id, lyrics_data, lyrics_id, owner_id)

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

    async def set_verified(self, lyrics_id: int, verified: bool = True) -> bool:
        """관리자 전용: 가사 검증(is_verified) 플래그 설정"""
        query = """
            UPDATE song_lyrics
            SET is_verified = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (1 if verified else 0, lyrics_id))
                return cursor.rowcount > 0

    async def update_visibility_owned(self, lyrics_id: int, owner_id: int, visibility: str) -> bool:
        """소유자 본인의 가사 visibility 변경 (다른 사람 가사는 rowcount 0 → False).

        음원을 연결한 가사는 기본이 private 이므로, 소유자가 다시 공개로 되돌릴
        수단이 필요하다. 관리자 경로(update_visibility)와 달리 소유권을 SQL 에서 강제한다.
        """
        if visibility not in ("public", "private", "whitelist"):
            raise ValueError(f"invalid visibility: {visibility}")
        query = """
            UPDATE song_lyrics
            SET visibility = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND owner_id = %s AND deleted_at IS NULL
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (visibility, lyrics_id, owner_id))
                return cursor.rowcount > 0

    async def update_visibility(self, lyrics_id: int, visibility: str) -> bool:
        """관리자 전용: 가사 visibility 변경"""
        if visibility not in ("public", "private", "whitelist"):
            raise ValueError(f"invalid visibility: {visibility}")
        query = """
            UPDATE song_lyrics
            SET visibility = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND deleted_at IS NULL
        """
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (visibility, lyrics_id))
                return cursor.rowcount > 0

    # ---------------------------------------------------------------
    # Song list / search (visibility-aware)
    # ---------------------------------------------------------------
    async def get_lyrics_counts(
        self, external_ids: List[str], user_id: Optional[int] = None, is_admin: bool = False
    ) -> Dict[str, int]:
        if not external_ids:
            return {}

        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        format_strings = ','.join(['%s'] * len(external_ids))
        # 각 external_id 의 가사 개수를 같은 제목+가수 형제 곡까지 합산
        query = f"""
            SELECT sref.song_external_id, COUNT(l.id) as count
            FROM songs sref
            JOIN songs sx ON sx.title = sref.title AND (sx.artist_id <=> sref.artist_id)
            JOIN song_lyrics l ON l.song_id = sx.id AND l.deleted_at IS NULL AND {vis_where}
            WHERE sref.song_external_id IN ({format_strings})
            GROUP BY sref.song_external_id
        """
        results = await self.db.fetch_all(query, (*vis_params, *external_ids))
        return {r['song_external_id']: r['count'] for r in results}

    async def get_songs_meta_by_external_ids(
        self, external_ids: List[str], user_id: Optional[int] = None, is_admin: bool = False
    ) -> List[Dict[str, Any]]:
        """주어진 song_external_id 들 중 visibility 적용한 가사를 가진 노래의 메타데이터를 반환.

        반환 형식은 search_all_songs_with_lyrics 와 동일.
        가사가 없는(또는 접근 불가한) 노래는 결과에서 제외된다.
        """
        if not external_ids:
            return []
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        placeholders = ','.join(['%s'] * len(external_ids))
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
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE s.song_external_id IN ({placeholders})
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
        """
        return await self.db.fetch_all(query, (*vis_params, *external_ids))

    async def search_songs_with_lyrics(
        self, query_term: str, user_id: Optional[int] = None, is_admin: bool = False, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """공개 가능한 가사가 있는 노래 검색"""
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        search_pattern = f"%{query_term}%"
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
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s)
            GROUP BY s.id
            ORDER BY last_updated DESC
            LIMIT %s
        """
        return await self.db.fetch_all(query, (*vis_params, search_pattern, search_pattern, search_pattern, limit))

    async def search_all_songs_with_lyrics(
        self, query_term: str, user_id: Optional[int] = None, is_admin: bool = False,
        offset: int = 0, limit: int = 20
    ) -> Dict[str, Any]:
        """공개 가능한 가사가 있는 노래 검색 (페이지네이션). 공백 무시 매칭."""
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        search_pattern = f"%{query_term}%"
        nospace_pattern = f"%{query_term.replace(' ', '')}%"

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
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s
                   OR REPLACE(s.title, ' ', '') LIKE %s
                   OR REPLACE(a.name, ' ', '') LIKE %s
                   OR REPLACE(l.title, ' ', '') LIKE %s)
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
            ORDER BY last_updated DESC
            LIMIT %s OFFSET %s
        """
        params = (
            *vis_params,
            search_pattern, search_pattern, search_pattern,
            nospace_pattern, nospace_pattern, nospace_pattern,
            limit, offset,
        )
        results = await self.db.fetch_all(query, params)

        count_query = f"""
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE (s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s
                   OR REPLACE(s.title, ' ', '') LIKE %s
                   OR REPLACE(a.name, ' ', '') LIKE %s
                   OR REPLACE(l.title, ' ', '') LIKE %s)
        """
        count_params = (
            *vis_params,
            search_pattern, search_pattern, search_pattern,
            nospace_pattern, nospace_pattern, nospace_pattern,
        )
        count_result = await self.db.fetch_one(count_query, count_params)

        return {
            "items": results,
            "total": count_result['total'] if count_result else 0,
            "offset": offset,
            "limit": limit
        }

    async def get_all_songs_with_lyrics(
        self, user_id: Optional[int] = None, is_admin: bool = False,
        offset: int = 0, limit: int = 20, song_type: str = "all", search: str = None,
        sort: str = "recent",
        extra_external_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """공개 가능한 가사가 있는 모든 노래 조회 (페이지네이션, 검색, 정렬 지원).

        extra_external_ids 가 주어지면 LIKE 매칭과 별개로 해당 song_external_id 들도 결과에 포함한다.
        (iTunes/Meilisearch 외부 검색이 발견한 후보를 DB LIKE 검색에 추가하기 위함)
        """
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        type_filter = ""

        search_filter = ""
        params: list = []
        if search:
            like_clause = """(s.title LIKE %s OR a.name LIKE %s OR l.title LIKE %s
                              OR REPLACE(s.title, ' ', '') LIKE %s
                              OR REPLACE(a.name, ' ', '') LIKE %s
                              OR REPLACE(l.title, ' ', '') LIKE %s)"""
            pattern = f"%{search}%"
            nospace_pattern = f"%{search.replace(' ', '')}%"
            like_params = [pattern, pattern, pattern, nospace_pattern, nospace_pattern, nospace_pattern]
            if extra_external_ids:
                placeholders = ','.join(['%s'] * len(extra_external_ids))
                search_filter = f"AND ({like_clause} OR s.song_external_id IN ({placeholders}))"
                params = like_params + list(extra_external_ids)
            else:
                search_filter = f"AND {like_clause}"
                params = like_params
        elif extra_external_ids:
            placeholders = ','.join(['%s'] * len(extra_external_ids))
            search_filter = f"AND s.song_external_id IN ({placeholders})"
            params = list(extra_external_ids)

        order_by_map = {
            "recent": "last_updated DESC",
            "title_asc": "s.title ASC",
            "title_desc": "s.title DESC",
            "artist_asc": "a.name ASC, s.title ASC",
            "artist_desc": "a.name DESC, s.title ASC",
        }
        order_by = order_by_map.get(sort, "last_updated DESC")

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
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE 1=1 {type_filter} {search_filter}
            GROUP BY s.id, s.title, s.song_external_id, s.cover_image_url, a.name, a.artist_external_id
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """
        items = await self.db.fetch_all(query, (*vis_params, *params, limit, offset))

        count_query = f"""
            SELECT COUNT(DISTINCT s.id) as total
            FROM songs s
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE 1=1 {type_filter} {search_filter}
        """
        count_result = await self.db.fetch_one(count_query, (*vis_params, *params))
        total = count_result['total'] if count_result else 0

        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total
        }

    async def find_songs_by_lyrics_title(
        self, query_term: str, user_id: Optional[int] = None, is_admin: bool = False,
        song_type_prefix: str = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """가사 버전 제목으로 노래 검색"""
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        search_pattern = f"%{query_term}%"
        nospace_pattern = f"%{query_term.replace(' ', '')}%"

        type_filter = ""
        params = [*vis_params, search_pattern, nospace_pattern]
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
            JOIN song_lyrics l ON s.id = l.song_id AND l.deleted_at IS NULL AND {vis_where}
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE (l.title LIKE %s OR REPLACE(l.title, ' ', '') LIKE %s) {type_filter}
            ORDER BY s.title ASC
            LIMIT %s
        """
        return await self.db.fetch_all(query, tuple(params))

    # ---------------------------------------------------------------
    # Favorites
    # ---------------------------------------------------------------
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

    async def get_my_favorites(
        self, user_id: int, is_admin: bool = False, offset: int = 0, limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """내 즐겨찾기 가사 목록 조회 (현재 접근 가능한 가사만)"""
        vis_where, vis_params = self.visibility_where(user_id, is_admin)
        query = f"""
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
                l.visibility,
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
            WHERE ulf.user_id = %s AND l.deleted_at IS NULL AND {vis_where}
            GROUP BY l.id, l.owner_id, u.name, l.song_id, s.title, s.song_external_id,
                     a.name, l.title, l.mr_youtube_video_id, l.is_verified, l.visibility,
                     l.likes_count, l.updated_at, ulf.created_at
            ORDER BY ulf.created_at DESC
            LIMIT %s OFFSET %s
        """
        items = await self.db.fetch_all(query, (user_id, *vis_params, limit, offset))

        count_query = f"""
            SELECT COUNT(*) as total
            FROM user_lyrics_favorites ulf
            JOIN song_lyrics l ON ulf.lyrics_id = l.id
            WHERE ulf.user_id = %s AND l.deleted_at IS NULL AND {vis_where}
        """
        count_result = await self.db.fetch_one(count_query, (user_id, *vis_params))
        total = count_result['total'] if count_result else 0

        return items, total

    async def is_favorited(self, user_id: int, lyrics_id: int) -> bool:
        """즐겨찾기 여부 확인"""
        query = "SELECT id FROM user_lyrics_favorites WHERE user_id = %s AND lyrics_id = %s"
        result = await self.db.fetch_one(query, (user_id, lyrics_id))
        return result is not None

    # ---------------------------------------------------------------
    # Memo
    # ---------------------------------------------------------------
    async def get_memo(self, user_id: int, lyrics_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT memo, updated_at FROM user_lyrics_memos WHERE user_id = %s AND lyrics_id = %s"
        return await self.db.fetch_one(query, (user_id, lyrics_id))

    async def save_memo(self, user_id: int, lyrics_id: int, memo: str) -> bool:
        query = """
            INSERT INTO user_lyrics_memos (user_id, lyrics_id, memo)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE memo = VALUES(memo), updated_at = CURRENT_TIMESTAMP
        """
        await self.db.execute_query(query, (user_id, lyrics_id, memo))
        return True

    async def delete_memo(self, user_id: int, lyrics_id: int) -> bool:
        query = "DELETE FROM user_lyrics_memos WHERE user_id = %s AND lyrics_id = %s"
        await self.db.execute_query(query, (user_id, lyrics_id))
        return True

    # ---------------------------------------------------------------
    # Whitelist
    # ---------------------------------------------------------------
    async def is_whitelisted(self, lyrics_id: int, user_id: int) -> bool:
        query = "SELECT 1 FROM lyrics_whitelist WHERE lyrics_id = %s AND user_id = %s LIMIT 1"
        result = await self.db.fetch_one(query, (lyrics_id, user_id))
        return result is not None

    async def get_whitelist(self, lyrics_id: int) -> List[Dict[str, Any]]:
        """가사의 화이트리스트 유저 목록 (관리자 화면용)"""
        query = """
            SELECT u.id, u.name, u.email, w.granted_at
            FROM lyrics_whitelist w
            JOIN users u ON w.user_id = u.id
            WHERE w.lyrics_id = %s
            ORDER BY w.granted_at DESC
        """
        return await self.db.fetch_all(query, (lyrics_id,))

    async def replace_whitelist(
        self, lyrics_id: int, user_ids: List[int], granted_by: int
    ) -> Dict[str, List[int]]:
        """화이트리스트 전체 교체 (트랜잭션). 변경 diff 반환."""
        # 현재 목록 조회
        existing_rows = await self.db.fetch_all(
            "SELECT user_id FROM lyrics_whitelist WHERE lyrics_id = %s", (lyrics_id,)
        )
        existing = {r['user_id'] for r in existing_rows}
        requested = set(user_ids)

        added = sorted(requested - existing)
        removed = sorted(existing - requested)

        if not added and not removed:
            return {"added": [], "removed": []}

        async with self.db.transaction() as tx:
            if removed:
                placeholders = ",".join(["%s"] * len(removed))
                await tx.execute_query(
                    f"DELETE FROM lyrics_whitelist WHERE lyrics_id = %s AND user_id IN ({placeholders})",
                    (lyrics_id, *removed),
                )
            if added:
                values_sql = ",".join(["(%s, %s, %s)"] * len(added))
                params: list = []
                for uid in added:
                    params.extend([lyrics_id, uid, granted_by])
                await tx.execute_query(
                    f"INSERT INTO lyrics_whitelist (lyrics_id, user_id, granted_by) VALUES {values_sql}",
                    tuple(params),
                )

        return {"added": added, "removed": removed}

    # ---------------------------------------------------------------
    # Admin user search (for whitelist picker autocomplete)
    # ---------------------------------------------------------------
    async def search_users(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        """이름/이메일 LIKE 검색. 활성 사용자만. 관리자 UI 자동완성용."""
        pattern = f"%{q}%"
        query = """
            SELECT id, name, email
            FROM users
            WHERE deleted_at IS NULL AND is_active = 1
              AND (name LIKE %s OR email LIKE %s)
            ORDER BY name ASC
            LIMIT %s
        """
        return await self.db.fetch_all(query, (pattern, pattern, limit))


def get_lyrics_repository():
    return LyricsRepository()
