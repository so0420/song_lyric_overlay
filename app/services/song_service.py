from typing import Optional
from fastapi import UploadFile
import uuid
from app.database.song_repository import SongRepository, get_song_repository
from app.database.cloudflare.r2 import r2_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.utils.config import settings
from fastapi import Depends

class SongService:
    def __init__(self, repo: SongRepository):
        self.repo = repo

    async def create_custom_song(self, title: str, artist: str, image: Optional[UploadFile], owner_id: int) -> dict:
        image_url = None

        # 1. Image Upload
        if image:
            content = await image.read()
            extension = image.filename.split('.')[-1] if '.' in image.filename else 'png'
            object_name = f"songs/covers/{uuid.uuid4()}.{extension}"
            await r2_handler.upload_file(content, object_name, image.content_type)
            public_url = settings.cloudflare_public_url.rstrip('/')
            if not public_url.startswith(('http://', 'https://')):
                public_url = f"https://{public_url}"
            image_url = f"{public_url}/{object_name}"
        
        # 2. DB Creation
        song_id = await self.repo.create_custom_song(
            title=title,
            artist_name=artist,
            image_url=image_url,
            owner_id=owner_id
        )
        
        # 3. Get External ID (generated in Repo/DB)
        song_external_id = await self.repo.get_song_external_id(song_id)
        
        # 4. Sync to Meilisearch
        if song_external_id:
            # Fetch owner name
            owner_data = await self.repo.db.fetch_one("SELECT name FROM users WHERE id = %s", (owner_id,))
            owner_name = owner_data['name'] if owner_data else None

            await meilisearch_handler.add_documents([{
                "id": song_id,
                "title": title,
                "singer": artist,
                "image_url": image_url,
                "song_external_id": song_external_id,
                "owner_name": owner_name
            }])
        
        return {
            "song_id": song_id,
            "song_external_id": song_external_id,
            "title": title,
            "artist": artist,
            "image_url": image_url
        }

    async def get_song_info(self, external_id: str):
        song = await self.repo.get_song_by_external_id(external_id)
        if song:
            return song
        
        # Future: If itunes ID, fetch and create?
        return None

def get_song_service(repo: SongRepository = Depends(get_song_repository)):
    return SongService(repo)
