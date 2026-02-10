from app.database.mariadb import db_handler
from typing import Optional, List, Dict, Any
import json

class SongRequestRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_requests(self, streamer_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT 
                r.*,
                s.title as ref_song_title,
                a.name as ref_artist_name,
                sb.cover_image_url as ref_song_cover,
                CASE WHEN sb.id IS NOT NULL THEN 1 ELSE 0 END as is_in_songbook
            FROM song_requests r
            LEFT JOIN songs s ON r.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN streamer_songbooks sb ON r.song_id = sb.song_id AND r.streamer_id = sb.streamer_id
            WHERE r.streamer_id = %s
            ORDER BY r.sort_order ASC, r.created_at ASC
        """
        return await self.db.fetch_all(query, (streamer_id,))

    async def add_request(self, streamer_id: int, requester: str, requester_type: str, requester_platform: str = None, 
                          song_id: int = None, title: str = None, artist: str = None, sort_order: int = None):
        if sort_order is None:
            count_res = await self.db.fetch_one("SELECT MAX(sort_order) as m FROM song_requests WHERE streamer_id = %s", (streamer_id,))
            sort_order = (count_res['m'] or 0) + 1 if count_res else 1

        query = """
            INSERT INTO song_requests (streamer_id, requester, requester_type, requester_platform, song_id, title, artist, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        return await self.db.execute_query(query, (streamer_id, requester, requester_type, requester_platform, song_id, title, artist, sort_order))

    async def update_request(self, request_id: int, streamer_id: int, **kwargs):
        updates = []
        params = []
        
        valid_fields = ['status', 'sort_order', 'song_id', 'title', 'artist']
        for key, val in kwargs.items():
            if key in valid_fields:
                updates.append(f"`{key}` = %s")
                params.append(val)
        
        if not updates:
            return
            
        query = f"UPDATE song_requests SET {', '.join(updates)} WHERE id = %s AND streamer_id = %s"
        params.extend([request_id, streamer_id])
        return await self.db.execute_query(query, tuple(params))

    async def delete_request(self, request_id: int, streamer_id: int):
        return await self.db.execute_query("DELETE FROM song_requests WHERE id = %s AND streamer_id = %s", (request_id, streamer_id))

    async def delete_done_requests(self, streamer_id: int):
        return await self.db.execute_query("DELETE FROM song_requests WHERE streamer_id = %s AND status = 'done'", (streamer_id,))

    async def delete_all_requests(self, streamer_id: int):
        return await self.db.execute_query("DELETE FROM song_requests WHERE streamer_id = %s", (streamer_id,))

    async def reorder_requests(self, streamer_id: int, order_list: List[int]):
        for idx, request_id in enumerate(order_list):
            await self.db.execute_query("UPDATE song_requests SET sort_order = %s WHERE id = %s AND streamer_id = %s", (idx + 1, request_id, streamer_id))

    async def next_request(self, streamer_id: int):
        # 1. Any currently 'playing' becomes 'done'
        await self.db.execute_query(
            "UPDATE song_requests SET status = 'done' WHERE streamer_id = %s AND status = 'playing'",
            (streamer_id,)
        )
        # 2. First 'waiting' becomes 'playing'
        next_req = await self.db.fetch_one(
            "SELECT id FROM song_requests WHERE streamer_id = %s AND status = 'waiting' ORDER BY sort_order ASC, created_at ASC LIMIT 1",
            (streamer_id,)
        )
        if next_req:
            await self.db.execute_query(
                "UPDATE song_requests SET status = 'playing' WHERE id = %s",
                (next_req['id'],)
            )
            return next_req['id']
        return None

    async def prev_request(self, streamer_id: int):
        # 1. Any currently 'playing' becomes 'waiting' (it goes back to queue)
        await self.db.execute_query(
            "UPDATE song_requests SET status = 'waiting' WHERE streamer_id = %s AND status = 'playing'",
            (streamer_id,)
        )
        # 2. Last 'done' becomes 'playing'
        prev_req = await self.db.fetch_one(
            "SELECT id FROM song_requests WHERE streamer_id = %s AND status = 'done' ORDER BY sort_order DESC, created_at DESC LIMIT 1",
            (streamer_id,)
        )
        if prev_req:
            await self.db.execute_query(
                "UPDATE song_requests SET status = 'playing' WHERE id = %s",
                (prev_req['id'],)
            )
            return prev_req['id']
        return None

    async def reset_requests(self, streamer_id: int):
        await self.db.execute_query(
            "UPDATE song_requests SET status = 'waiting' WHERE streamer_id = %s",
            (streamer_id,)
        )

def get_song_request_repository():
    return SongRequestRepository()
