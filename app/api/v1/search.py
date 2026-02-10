from fastapi import APIRouter, Query, Depends
from app.core.auth import get_current_user_api
from app.integrations.ITunes_search_api import itunes_api
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.lyrics_repository import LyricsRepository, get_lyrics_repository
from app.database.streamer_repository import StreamerRepository, get_streamer_repository
from app.database.songbook_repository import SongbookRepository, get_songbook_repository
from app.utils.log import logger
from typing import List, Dict, Any
import asyncio

router = APIRouter()

@router.get("/")
async def unified_search(
    q: str = Query(..., min_length=1),
    user=Depends(get_current_user_api),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository)
):
    """iTunes와 Meilisearch(로컬 DB) 통합 검색"""
    
    # 1. 스트리머 정보 및 노래책 목록 가져오기
    streamer = await streamer_repo.get_streamer_by_user_id(user['id'])
    songbook_external_ids = set()
    if streamer:
        songbook = await songbook_repo.get_songbook(streamer['id'])
        songbook_external_ids = {s['song_external_id'] for s in songbook}

    # 2. iTunes 검색
    itunes_results = await itunes_api.search(q)
    
    # 3. Meilisearch 검색 (로컬 곡 및 커스텀 곡)
    meili_results = await meilisearch_handler.search(q, attributes_to_search_on=["title", "singer"])

    # 결과 가공
    user_picture = user.get('picture', '/static/default_avatar.png')
    
    songbook_list = []
    itunes_list = []
    local_list = []
    
    seen_external_ids = set()

    # 1. iTunes API 결과 처리
    for it in itunes_results:
        ext_id = f"it_{it['track_id']}"
        item = {
            "title": it['track_name'],
            "artist": it['artist_name'],
            "image_url": user_picture,
            "song_external_id": ext_id,
            "source": "it"
        }
        
        seen_external_ids.add(ext_id)
        
        if ext_id in songbook_external_ids:
            songbook_list.append(item)
        else:
            itunes_list.append(item)

    # 2. Meilisearch 결과 처리 (iTunes API 결과에 없는 것만)
    for m in meili_results:
        ext_id = m.get('song_external_id')
        if not ext_id or ext_id in seen_external_ids:
            continue
            
        item = {
            "title": m['title'],
            "artist": m['singer'],
            "image_url": m.get('image_url') or user_picture,
            "song_external_id": ext_id,
            "source": "local" if ext_id.startswith("custom_") else "it",
            "owner_name": m.get('owner_name')
        }
        
        seen_external_ids.add(ext_id)
        
        if ext_id in songbook_external_ids:
            songbook_list.append(item)
        else:
            local_list.append(item)

    # 4. 가사 개수 정보 추가
    all_combined = songbook_list + itunes_list + local_list
    external_ids = [c['song_external_id'] for c in all_combined]
    
    if external_ids:
        lyrics_counts = await lyrics_repo.get_lyrics_counts(external_ids)
        for item in all_combined:
            item['lyrics_count'] = lyrics_counts.get(item['song_external_id'], 0)

    return {
        "songbook": songbook_list,
        "itunes": itunes_list,
        "local": local_list
    }
