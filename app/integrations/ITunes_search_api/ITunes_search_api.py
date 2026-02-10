import httpx
import asyncio
from typing import Optional
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.utils.log import logger

class ITunesSearchAPI:
    def __init__(self):
        self.url = "https://itunes.apple.com/search"
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """클라이언트를 초기화합니다. FastAPI lifespan에서 호출 추천."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()

    async def close(self):
        """클라이언트를 종료합니다. FastAPI lifespan에서 호출 추천."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search(self, term: str, country: str = "KR", limit: int = 100) -> list:
        # 클라이언트가 초기화되지 않은 경우 (동적인 대응)
        if self._client is None or self._client.is_closed:
            await self.initialize()

        params = {
            "term": term,
            "country": country,
            "media": "music",
            "limit": limit
        }
        
        response = await self._client.get(self.url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            result_list = []
            for track in data.get('results', []):
                result_list.append({
                    "artist_name": track.get('artistName'),
                    "artist_id": str(track.get('artistId')),
                    "track_name": track.get('trackName'),
                    "track_id": str(track.get('trackId')),
                    "artwork_url": track.get('artworkUrl100')
                })

            # 백그라운드 태스크로 DB 등록 진행 (검색 결과 리턴은 즉시 수행)
            asyncio.create_task(self._register_results_to_db(result_list))
            
            return result_list
        else:
            raise Exception(f"오류 발생: {response.status_code}")

    async def _register_results_to_db(self, result_list: list):
        """검색된 아티스트와 노래를 DB에 비동기로 등록합니다."""
        if not result_list:
            return

        try:
            for item in result_list:
                artist_name = item['artist_name']
                artist_ext_id = f"it_{item['artist_id']}"
                track_name = item['track_name']
                track_ext_id = f"it_{item['track_id']}"

                # 1. 아티스트 등록 (이미 있으면 무시하고 경고도 방지)
                # schema.sql: UNIQUE KEY `unique_artist_external_id` (`artist_external_id`)
                await db_handler.execute_query(
                    """
                    INSERT INTO artists (name, artist_external_id) 
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE id=id
                    """,
                    (artist_name, artist_ext_id)
                )

                # 등록된/기존 아티스트 ID 가져오기
                artist = await db_handler.fetch_one(
                    "SELECT id FROM artists WHERE artist_external_id = %s",
                    (artist_ext_id,)
                )
                
                if artist:
                    artist_id = artist['id']
                    # 2. 노래 등록 (이미 있으면 무시하고 경고도 방지)
                    # schema.sql: UNIQUE KEY `unique_song_external_id` (`song_external_id`)
                    await db_handler.execute_query(
                        """
                        INSERT INTO songs (title, song_external_id, artist_id, cover_image_url) 
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE id=id, cover_image_url=VALUES(cover_image_url)
                        """,
                        (track_name, track_ext_id, artist_id, item.get('artwork_url'))
                    )
        except Exception as e:
            # 백그라운드 작업이므로 에러가 발생해도 메인 루프에 영향을 주지 않도록 로깅만 수행
            # (실제 환경에서는 logger를 사용하는 것이 좋음)
            logger.error(f"Background registration error: {e}")

# 싱글톤 인스턴스 생성
itunes_api = ITunesSearchAPI()
