import httpx
import time
from typing import Optional, List, Dict, Any, Tuple
from app.utils.config import settings, config
from app.utils.log import logger


class YouTubeAPI:
    def __init__(self):
        self.api_key = settings.youtube_api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: Dict[str, Tuple[List, float]] = {}

    @property
    def _cache_ttl(self) -> int:
        return config.cache_options.youtube_ttl

    @property
    def _cache_max_size(self) -> int:
        return config.cache_options.youtube_max_size

    def _get_cache_key(self, query: str, max_results: int) -> str:
        return f"{query.lower().strip()}:{max_results}"

    def _clean_expired_cache(self):
        now = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if now - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            del self._cache[key]

    def _get_from_cache(self, cache_key: str) -> Optional[List]:
        if cache_key in self._cache:
            result, timestamp = self._cache[cache_key]
            if time.time() - timestamp <= self._cache_ttl:
                logger.debug(f"YouTube cache hit: {cache_key}")
                return result
            else:
                del self._cache[cache_key]
        return None

    def _save_to_cache(self, cache_key: str, result: List):
        if len(self._cache) >= self._cache_max_size:
            self._clean_expired_cache()
            if len(self._cache) >= self._cache_max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
        self._cache[cache_key] = (result, time.time())

    async def initialize(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search_videos(self, query: str, max_results: int = 10, page_token: str = None) -> Dict[str, Any]:
        """유튜브 영상 검색 (공식 YouTube Data API v3)."""
        cache_key = self._get_cache_key(query, max_results)
        if page_token is None:
            cached_result = self._get_from_cache(cache_key)
            if cached_result is not None:
                return cached_result

        if self._client is None or self._client.is_closed:
            await self.initialize()

        response_data = await self._search_videos_official(query, max_results, page_token)

        if page_token is None:
            self._save_to_cache(cache_key, response_data)

        return response_data

    async def _search_videos_official(self, query: str, max_results: int, page_token: str = None) -> Dict[str, Any]:
        """공식 YouTube Data API v3 검색"""
        search_params = {
            "part": "snippet",
            "q": query,
            "maxResults": max_results,
            "type": "video",
            "key": self.api_key,
        }
        if page_token:
            search_params["pageToken"] = page_token

        search_response = await self._client.get(f"{self.base_url}/search", params=search_params)

        if search_response.status_code != 200:
            raise Exception(f"YouTube Search Error: {search_response.status_code} - {search_response.text}")

        search_data = search_response.json()
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        next_page_token = search_data.get("nextPageToken")

        if not video_ids:
            return {"items": [], "nextPageToken": None}

        details_list = await self.get_video_details(video_ids)

        results = []
        for item in details_list:
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            status = item.get("status", {})

            results.append({
                "video_id": item.get("id"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "duration": content_details.get("duration"),
                "thumbnails": snippet.get("thumbnails"),
                "channel_title": snippet.get("channelTitle"),
                "embeddable": status.get("embeddable", False),
            })

        return {"items": results, "nextPageToken": next_page_token}

    async def get_video_details(self, video_ids: List[str]) -> List[Dict[str, Any]]:
        if self._client is None or self._client.is_closed:
            await self.initialize()

        params = {
            "part": "snippet,contentDetails,status,statistics",
            "id": ",".join(video_ids),
            "key": self.api_key,
        }

        response = await self._client.get(f"{self.base_url}/videos", params=params)

        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            raise Exception(f"YouTube Video Details Error: {response.status_code} - {response.text}")

    async def get_video_by_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """영상 ID로 단일 영상 정보 (공식 YouTube Data API v3)."""
        if self._client is None or self._client.is_closed:
            await self.initialize()

        details = await self.get_video_details([video_id])

        if not details:
            return None

        item = details[0]
        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})
        status = item.get("status", {})

        return {
            "video_id": item.get("id"),
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "duration": content_details.get("duration"),
            "thumbnails": snippet.get("thumbnails"),
            "channel_title": snippet.get("channelTitle"),
            "embeddable": status.get("embeddable", False),
        }



youtube_api = YouTubeAPI()
