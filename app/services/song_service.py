from typing import Optional
from fastapi import UploadFile, Depends
from app.database.song_repository import SongRepository, get_song_repository
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.utils.log import logger

class SongService:
    def __init__(self, repo: SongRepository):
        self.repo = repo

    async def create_custom_song(self, title: str, artist: str, image: Optional[UploadFile], owner_id: int) -> dict:
        # 이미지 업로드 기능 제거 - image_url은 None으로 설정
        image_url = None

        # DB Creation
        song_id = await self.repo.create_custom_song(
            title=title,
            artist_name=artist,
            image_url=image_url,
            owner_id=owner_id
        )

        # Get External ID (generated in Repo/DB)
        song_external_id = await self.repo.get_song_external_id(song_id)

        # Meilisearch에도 추가
        try:
            await meilisearch_handler.add_documents([{
                "id": song_external_id,
                "title": title,
                "singer": artist,
                "image_url": image_url,
                "owner_id": owner_id
            }])
        except Exception as e:
            # Meilisearch 실패해도 DB 저장은 성공으로 처리
            logger.warning(f"Meilisearch add failed for song {song_external_id}: {e}")

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
        return None

def get_song_service(repo: SongRepository = Depends(get_song_repository)):
    return SongService(repo)
