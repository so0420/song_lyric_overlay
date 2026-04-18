"""
iTunes Search API - curl_cffi 기반 (TLS 핑거프린팅 우회)
Apple CDN이 봇 차단을 하므로 Chrome TLS 위장이 필요함.
검색 실패 시 None을 반환하여 호출부에서 graceful하게 처리.
"""

import asyncio
from typing import Optional, List
from curl_cffi import requests as cffi_requests
from app.utils.log import logger

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def _search_sync(term: str, country: str = "KR", limit: int = 100) -> Optional[List[dict]]:
    """동기 iTunes 검색 (curl_cffi는 async에서 404가 나므로 sync 사용)"""
    try:
        response = cffi_requests.get(
            ITUNES_SEARCH_URL,
            params={"term": term, "country": country, "media": "music", "limit": limit},
            impersonate="chrome",
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning(f"iTunes search failed: status={response.status_code}, term={term}")
            return None

        data = response.json()
        results = []
        for track in data.get("results", []):
            results.append({
                "track_id": str(track.get("trackId")),
                "track_name": track.get("trackName"),
                "artist_id": str(track.get("artistId")),
                "artist_name": track.get("artistName"),
                "artwork_url": track.get("artworkUrl100"),
            })
        return results
    except Exception as e:
        logger.warning(f"iTunes search error: {e}")
        return None


async def search_itunes(term: str, country: str = "KR", limit: int = 100) -> Optional[List[dict]]:
    """비동기 래퍼 — sync 호출을 스레드에서 실행"""
    return await asyncio.to_thread(_search_sync, term, country, limit)
