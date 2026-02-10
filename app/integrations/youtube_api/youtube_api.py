import httpx
import asyncio
from typing import Optional, List, Dict, Any
from app.utils.config import settings

class YouTubeAPI:
    def __init__(self):
        self.api_key = settings.youtube_api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """클라이언트를 초기화합니다. FastAPI lifespan에서 호출 권장."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        """클라이언트를 종료합니다. FastAPI lifespan에서 호출 권장."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search_videos(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        유튜브 영상을 검색하고 상세 정보(길이, 재생가능여부 등)를 포함하여 반환합니다.
        """
        if self._client is None or self._client.is_closed:
            await self.initialize()

        # 1. 먼저 검색 API로 비디오 ID 목록을 가져옵니다.
        search_params = {
            "part": "snippet",
            "q": query,
            "maxResults": max_results,
            "type": "video",
            "key": self.api_key
        }

        search_response = await self._client.get(f"{self.base_url}/search", params=search_params)
        
        if search_response.status_code != 200:
            raise Exception(f"YouTube Search Error: {search_response.status_code} - {search_response.text}")

        search_data = search_response.json()
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]

        if not video_ids:
            return []

        # 2. 가져온 ID들로 상세 정보(contentDetails, status)를 조회합니다.
        details_list = await self.get_video_details(video_ids)
        
        # 3. 데이터 결합
        results = []
        for item in details_list:
            snippet = item.get("snippet", {})
            content_details = item.get("contentDetails", {})
            status = item.get("status", {})
            
            results.append({
                "video_id": item.get("id"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "duration": content_details.get("duration"), # ISO 8601 포맷 (예: PT3M45S)
                "thumbnails": snippet.get("thumbnails"),
                "channel_title": snippet.get("channelTitle"),
                "embeddable": status.get("embeddable", False) # 외부 재생 가능 여부
            })
            
        return results

    async def get_video_details(self, video_ids: List[str]) -> List[Dict[str, Any]]:
        """
        영상 ID 리스트로 상세 정보를 가져옵니다.
        """
        if self._client is None or self._client.is_closed:
            await self.initialize()

        params = {
            "part": "snippet,contentDetails,status,statistics",
            "id": ",".join(video_ids),
            "key": self.api_key
        }

        response = await self._client.get(f"{self.base_url}/videos", params=params)
        
        if response.status_code == 200:
            return response.json().get("items", [])
        else:
            raise Exception(f"YouTube Video Details Error: {response.status_code} - {response.text}")

    async def get_video_by_id(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        영상 ID로 단일 영상 정보를 가져옵니다.
        """
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
            "embeddable": status.get("embeddable", False)
        }

# 싱글톤 인스턴스 생성
youtube_api = YouTubeAPI()
