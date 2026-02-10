from app.database.mariadb import db_handler
from typing import Optional, List, Dict, Any
import json
from app.database.cloudflare.r2 import r2_handler

class SongbookRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_songbook(self, streamer_id: int, query_str: str = None, tags: List[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        query = """
            SELECT 
                sb.id as entry_id,
                sb.difficulty,
                sb.memo,
                sb.tags as song_tags,
                sb.lyrics_id,
                sb.cover_image_url,
                s.id as song_id,
                s.song_external_id,
                s.title as music_name,
                -- s.cover_image_url as cover_art_path,
                s.length_ms,
                a.name as artist_name,
                sb.mr_youtube_video_id,
                sb.price_cheese,
                sb.price_balloon,
                u.name as owner_name
            FROM streamer_songbooks sb
            JOIN songs s ON sb.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id 
            LEFT JOIN users u ON s.owner_id = u.id
            LEFT JOIN song_lyrics l ON sb.lyrics_id = l.id
            WHERE sb.streamer_id = %s
        """
        params = [streamer_id]
        
        if query_str:
            query += " AND (s.title LIKE %s OR a.name LIKE %s)"
            params.extend([f"%{query_str}%", f"%{query_str}%"])
        
        if tags:
            for tag in tags:
                query += " AND JSON_CONTAINS(sb.tags, %s)"
                params.append(json.dumps(tag))

        query += " ORDER BY sb.sort_order ASC, sb.id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        results = await self.db.fetch_all(query, tuple(params))
        
        # Process JSON fields
        for res in results:
            if res.get('song_tags'):
                try:
                    res['tags'] = json.loads(res['song_tags'])
                except:
                    res['tags'] = []
            else:
                res['tags'] = []
        return results

    async def add_song(self, streamer_id: int, song_id: int, tags: List[str] = [], difficulty: int = 5, memo: str = None, mr_video_id: str = None, lyrics_id: int = None, user_id: int = None, cover_image_url: str = None, price_cheese: int = 0, price_balloon: int = 0):
        # 2. streamer_songbooks에 추가
        count_res = await self.db.fetch_one("SELECT MAX(sort_order) as m FROM streamer_songbooks WHERE streamer_id = %s", (streamer_id,))
        next_sort = (count_res['m'] or 0) + 1 if count_res else 1

        query = """
            INSERT INTO streamer_songbooks (streamer_id, song_id, lyrics_id, mr_youtube_video_id, tags, difficulty, memo, sort_order, cover_image_url, price_cheese, price_balloon)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                lyrics_id = VALUES(lyrics_id),
                mr_youtube_video_id = VALUES(mr_youtube_video_id),
                tags = VALUES(tags),
                difficulty = VALUES(difficulty),
                memo = VALUES(memo),
                cover_image_url = VALUES(cover_image_url),
                price_cheese = VALUES(price_cheese),
                price_balloon = VALUES(price_balloon)
        """
        return await self.db.execute_query(query, (streamer_id, song_id, lyrics_id, mr_video_id, json.dumps(tags), difficulty, memo, next_sort, cover_image_url, price_cheese, price_balloon))

    async def update_song(self, entry_id: int, **kwargs):
        # 0. 이미지 변경 시 기존 이미지 삭제 처리
        if 'cover_image_url' in kwargs:
            old_entry = await self.db.fetch_one("SELECT cover_image_url FROM streamer_songbooks WHERE id = %s", (entry_id,))
            if old_entry and old_entry['cover_image_url'] and old_entry['cover_image_url'] != kwargs['cover_image_url']:
                old_key = r2_handler.get_object_name_from_url(old_entry['cover_image_url'])
                if old_key:
                    try:
                        await r2_handler.delete_file(old_key)
                    except:
                        pass

        # 1. streamer_songbooks 업데이트
        updates = []
        params = []
        
        field_map = {
            'tags': 'tags',
            'difficulty': 'difficulty',
            'memo': 'memo',
            'lyrics_id': 'lyrics_id',
            'mr_video_id': 'mr_youtube_video_id',
            'cover_image_url': 'cover_image_url',
            'price_cheese': 'price_cheese',
            'price_balloon': 'price_balloon'
        }
        
        for key, val in kwargs.items():
            if key in field_map:
                updates.append(f"{field_map[key]} = %s")
                if key == 'tags' and val is not None:
                    params.append(json.dumps(val))
                else:
                    params.append(val)
        
        if not updates:
            return
        
        query = f"UPDATE streamer_songbooks SET {', '.join(updates)} WHERE id = %s"
        params.append(entry_id)
        return await self.db.execute_query(query, tuple(params))

    async def remove_song(self, entry_id: int):
        # 이미지 삭제 처리
        old_entry = await self.db.fetch_one("SELECT cover_image_url FROM streamer_songbooks WHERE id = %s", (entry_id,))
        if old_entry and old_entry['cover_image_url']:
            old_key = r2_handler.get_object_name_from_url(old_entry['cover_image_url'])
            if old_key:
                try:
                    await r2_handler.delete_file(old_key)
                except:
                    pass
        
        query = "DELETE FROM streamer_songbooks WHERE id = %s"
        return await self.db.execute_query(query, (entry_id,))

def get_songbook_repository():
    return SongbookRepository()
