"""
iTunes Search API - curl_cffi 기반 (TLS 핑거프린팅 우회)
Apple CDN이 봇 차단을 하므로 Chrome TLS 위장이 필요함.
검색 실패 시 None을 반환하여 호출부에서 graceful하게 처리.

성공 결과는 in-memory 캐시(config.cache_options.itunes_ttl/itunes_max_size) 에 저장한다.
"""

import asyncio
import time
from typing import Optional, List, Dict, Tuple
from curl_cffi import requests as cffi_requests
from app.utils.config import config
from app.utils.log import logger

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

# key -> (result, stored_at)
_cache: Dict[str, Tuple[List[dict], float]] = {}


def _cache_key(term: str, country: str, limit: int) -> str:
    return f"{term.lower().strip()}:{country}:{limit}"


def _get_from_cache(key: str) -> Optional[List[dict]]:
    ttl = config.cache_options.itunes_ttl
    entry = _cache.get(key)
    if entry is None:
        return None
    result, ts = entry
    if time.time() - ts > ttl:
        _cache.pop(key, None)
        return None
    return result


def _save_to_cache(key: str, result: List[dict]) -> None:
    max_size = config.cache_options.itunes_max_size
    ttl = config.cache_options.itunes_ttl
    if len(_cache) >= max_size:
        now = time.time()
        for k in [k for k, (_, ts) in _cache.items() if now - ts > ttl]:
            _cache.pop(k, None)
        if len(_cache) >= max_size:
            oldest_key = min(_cache.keys(), key=lambda k: _cache[k][1])
            _cache.pop(oldest_key, None)
    _cache[key] = (result, time.time())


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
    """비동기 래퍼 — sync 호출을 스레드에서 실행. 성공 결과는 in-memory 캐시 사용."""
    results, _ = await search_itunes_cached(term, country, limit)
    return results


async def search_itunes_cached(
    term: str, country: str = "KR", limit: int = 100
) -> "tuple[Optional[List[dict]], bool]":
    """iTunes 검색 + 캐시 적용. (results, from_cache) 튜플 반환.

    호출자는 from_cache 가 False 일 때만 등록(register_itunes_results) 같은 부수 작업을
    수행해 라이브 호출당 한 번만 DB/Meilisearch 갱신이 일어나도록 할 수 있다.
    """
    key = _cache_key(term, country, limit)
    cached = _get_from_cache(key)
    if cached is not None:
        logger.debug(f"iTunes cache hit: {term}")
        return cached, True

    result = await asyncio.to_thread(_search_sync, term, country, limit)
    if result is not None:
        _save_to_cache(key, result)
    return result, False
