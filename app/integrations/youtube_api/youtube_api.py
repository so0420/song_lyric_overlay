import httpx
import asyncio
import json
import re
import time
from typing import Optional, List, Dict, Any, Tuple
from app.utils.config import settings, config
from app.utils.log import logger


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _duration_str_to_iso(text: str) -> Optional[str]:
    """'3:45' / '1:23:45' 형태를 ISO 8601(PT3M45S)로 변환. 파싱 실패 시 None."""
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        m, s = nums
        h = 0
    elif len(nums) == 3:
        h, m, s = nums
    else:
        return None
    iso = "PT"
    if h:
        iso += f"{h}H"
    if m:
        iso += f"{m}M"
    if s or (not h and not m):
        iso += f"{s}S"
    return iso


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
        """
        유튜브 영상 검색. 공식 API 실패 시(쿼터 초과 등) 스크래핑 폴백.
        """
        cache_key = self._get_cache_key(query, max_results)
        if page_token is None:
            cached_result = self._get_from_cache(cache_key)
            if cached_result is not None:
                return cached_result

        if self._client is None or self._client.is_closed:
            await self.initialize()

        try:
            response_data = await self._search_videos_official(query, max_results, page_token)
        except Exception as e:
            err_str = str(e)
            if "quotaExceeded" in err_str or "403" in err_str:
                logger.warning(f"YouTube API quota exceeded, falling back to scraping for query: {query}")
                response_data = await self._search_videos_scraping(query, max_results)
            else:
                raise

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

    async def _search_videos_scraping(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """비공식 스크래핑 폴백: youtube.com/results 페이지의 ytInitialData 파싱"""
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
        url = "https://www.youtube.com/results"
        params = {"search_query": query}

        try:
            response = await self._client.get(url, params=params, headers=headers)
            if response.status_code != 200:
                logger.error(f"YouTube scraping failed: status={response.status_code}")
                return {"items": [], "nextPageToken": None, "fallback": "scraping"}
            html = response.text
        except Exception as e:
            logger.error(f"YouTube scraping request failed: {e}")
            return {"items": [], "nextPageToken": None, "fallback": "scraping"}

        match = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
        if not match:
            match = re.search(r"ytInitialData\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            logger.error("YouTube scraping: ytInitialData not found")
            return {"items": [], "nextPageToken": None, "fallback": "scraping"}

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.error(f"YouTube scraping: JSON parse error: {e}")
            return {"items": [], "nextPageToken": None, "fallback": "scraping"}

        results = []
        try:
            sections = (
                data.get("contents", {})
                    .get("twoColumnSearchResultsRenderer", {})
                    .get("primaryContents", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
            )
            for section in sections:
                items = section.get("itemSectionRenderer", {}).get("contents", [])
                for item in items:
                    video = item.get("videoRenderer")
                    if not video:
                        continue

                    video_id = video.get("videoId")
                    if not video_id:
                        continue

                    # 제목
                    title_obj = video.get("title", {})
                    title = title_obj.get("simpleText")
                    if not title:
                        runs = title_obj.get("runs", [])
                        title = "".join(r.get("text", "") for r in runs)

                    # 채널명
                    owner = video.get("ownerText", {}).get("runs", [])
                    channel_title = owner[0].get("text") if owner else None

                    # 길이 (lengthText가 없으면 LIVE이거나 알 수 없음)
                    length_text = video.get("lengthText", {}).get("simpleText")
                    duration = _duration_str_to_iso(length_text)

                    # 설명
                    desc_snippets = video.get("detailedMetadataSnippets", [])
                    description = None
                    if desc_snippets:
                        desc_runs = desc_snippets[0].get("snippetText", {}).get("runs", [])
                        description = "".join(r.get("text", "") for r in desc_runs)

                    # 썸네일
                    thumbnails_list = video.get("thumbnail", {}).get("thumbnails", [])
                    thumbnails = {}
                    if thumbnails_list:
                        thumbnails["default"] = thumbnails_list[0]
                        if len(thumbnails_list) > 1:
                            thumbnails["medium"] = thumbnails_list[len(thumbnails_list) // 2]
                        thumbnails["high"] = thumbnails_list[-1]

                    results.append({
                        "video_id": video_id,
                        "title": title,
                        "description": description,
                        "duration": duration,
                        "thumbnails": thumbnails,
                        "channel_title": channel_title,
                        "embeddable": True,  # 스크래핑에서는 확인 불가, 낙관적 기본값
                    })

                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
        except Exception as e:
            logger.error(f"YouTube scraping parse error: {e}")

        return {"items": results, "nextPageToken": None, "fallback": "scraping"}

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
        """영상 ID로 단일 영상 정보. 공식 API 실패 시 스크래핑 폴백."""
        if self._client is None or self._client.is_closed:
            await self.initialize()

        try:
            details = await self.get_video_details([video_id])
        except Exception as e:
            err_str = str(e)
            if "quotaExceeded" in err_str or "403" in err_str:
                logger.warning(f"YouTube API quota exceeded, falling back to scraping for video: {video_id}")
                return await self._get_video_by_id_scraping(video_id)
            raise

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

    async def _get_video_by_id_scraping(self, video_id: str) -> Optional[Dict[str, Any]]:
        """비공식 스크래핑으로 단일 영상 메타데이터 조회"""
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            response = await self._client.get(url, headers=headers)
            if response.status_code != 200:
                return None
            html = response.text
        except Exception as e:
            logger.error(f"YouTube scraping video_by_id failed: {e}")
            return None

        match = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        video_details = data.get("videoDetails", {})
        playability_status = data.get("playabilityStatus", {})

        length_seconds = int(video_details.get("lengthSeconds", 0))
        hours, rem = divmod(length_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        duration = "PT"
        if hours:
            duration += f"{hours}H"
        if minutes:
            duration += f"{minutes}M"
        if seconds or (not hours and not minutes):
            duration += f"{seconds}S"

        # 임베드 가능 여부: status가 OK면 가능
        status_code = playability_status.get("status", "")
        reason = playability_status.get("reason", "").lower()
        embeddable = status_code == "OK" and "embedding disabled" not in reason

        thumbnails_list = video_details.get("thumbnail", {}).get("thumbnails", [])
        thumbnails = {}
        if thumbnails_list:
            thumbnails["default"] = thumbnails_list[0]
            if len(thumbnails_list) > 1:
                thumbnails["medium"] = thumbnails_list[len(thumbnails_list) // 2]
            thumbnails["high"] = thumbnails_list[-1]

        return {
            "video_id": video_details.get("videoId", video_id),
            "title": video_details.get("title"),
            "description": video_details.get("shortDescription"),
            "duration": duration,
            "thumbnails": thumbnails,
            "channel_title": video_details.get("author"),
            "embeddable": embeddable,
        }


youtube_api = YouTubeAPI()
