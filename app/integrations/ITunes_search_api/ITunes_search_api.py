import httpx
import asyncio
import time
from typing import Optional, Dict, Tuple, List
from app.database.mariadb import db_handler
from app.utils.config import config

from app.utils.log import logger

class ITunesSearchAPI:
    def __init__(self):
        self.url = "https://itunes.apple.com/search"
        self._client: Optional[httpx.AsyncClient] = None
        # 캐시: {cache_key: (result_list, timestamp)}
        self._cache: Dict[str, Tuple[List, float]] = {}

    @property
    def _cache_ttl(self) -> int:
        """캐시 유효 시간 (초)"""
        return config.cache_options.itunes_ttl

    @property
    def _cache_max_size(self) -> int:
        """최대 캐시 항목 수"""
        return config.cache_options.itunes_max_size

    async def initialize(self):
        """클라이언트를 초기화합니다. FastAPI lifespan에서 호출 추천."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()

    async def close(self):
        """클라이언트를 종료합니다. FastAPI lifespan에서 호출 추천."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _get_cache_key(self, term: str, country: str, limit: int) -> str:
        """캐시 키 생성"""
        return f"{term.lower().strip()}:{country}:{limit}"

    def _clean_expired_cache(self):
        """만료된 캐시 항목 정리"""
        now = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if now - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            del self._cache[key]

    def _get_from_cache(self, cache_key: str) -> Optional[List]:
        """캐시에서 결과 조회"""
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            if time.time() - timestamp <= self._cache_ttl:
                logger.debug(f"iTunes cache hit: {cache_key}")
                return result
            else:
                # 만료된 항목 삭제
                del self._cache[cache_key]
        return None

    def _save_to_cache(self, cache_key: str, result: List):
        """결과를 캐시에 저장"""
        # 캐시 크기 제한 체크
        if len(self._cache) >= self._cache_max_size:
            self._clean_expired_cache()
            # 여전히 크면 가장 오래된 항목 삭제
            if len(self._cache) >= self._cache_max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]

        self._cache[cache_key] = (result, time.time())

    async def search(self, term: str, country: str = "KR", limit: int = 100) -> list:
        # 캐시 확인
        cache_key = self._get_cache_key(term, country, limit)
        cached_result = self._get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result

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

            # 캐시에 저장
            self._save_to_cache(cache_key, result_list)

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
