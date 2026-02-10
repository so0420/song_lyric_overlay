from fastapi import APIRouter, Request, Query, Depends, HTTPException, Form, File, UploadFile
from app.core.auth import get_current_user_api
from app.database.songbook_repository import get_songbook_repository
from app.database.streamer_repository import get_streamer_repository
from app.database.song_repository import get_song_repository
from app.database.cloudflare.r2 import r2_handler
from app.utils.config import settings
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class SongAddSchema(BaseModel):
    song_external_id: str
    title: str
    artist: str
    image_url: Optional[str] = None
    tag: List[str] = []
    difficulty: int = 5
    description: Optional[str] = None
    mr_video_id: Optional[str] = None
    lyrics_id: Optional[int] = None
    price_cheese: int = 0
    price_balloon: int = 0

class SongUpdateSchema(BaseModel):
    tag: Optional[List[str]] = None
    difficulty: Optional[int] = None
    description: Optional[str] = None
    mr_video_id: Optional[str] = None
    lyrics_id: Optional[int] = None
    price_cheese: Optional[int] = None
    price_balloon: Optional[int] = None

@router.get("/{streamer_id}")
async def get_streamer_songbook(
    streamer_id: str,
    q: str = Query(None),
    tags: str = Query(None), # comma separated
    limit: int = 100,
    offset: int = 0,
    repo=Depends(get_songbook_repository),
    streamer_repo=Depends(get_streamer_repository)
):
    """스트리머의 노래책 조회 (Public)"""
    # 외부 streamer_id로 스트리머 조회 후 내부 id 사용
    streamer = await streamer_repo.get_streamer_by_streamer_id(streamer_id)
    if not streamer:
        return []
    
    tag_list = tags.split(',') if tags else None
    return await repo.get_songbook(streamer['id'], query_str=q, tags=tag_list, limit=limit, offset=offset)

@router.post("/")
async def add_song_to_my_songbook(
    request: Request,
    song_external_id: str = Form(...),
    title: str = Form(...),
    artist: str = Form(...),
    image_url: Optional[str] = Form(None),
    tag: str = Form("[]"), # JSON string of tags
    difficulty: int = Form(5),
    description: Optional[str] = Form(None),
    mr_video_id: Optional[str] = Form(None),
    lyrics_id: Optional[int] = Form(None),
    price_cheese: int = Form(0),
    price_balloon: int = Form(0),
    cover_image: Optional[UploadFile] = File(None),
    songbook_repo=Depends(get_songbook_repository),
    streamer_repo=Depends(get_streamer_repository),
    song_repo=Depends(get_song_repository),
    user=Depends(get_current_user_api)
):
    """자신의 노래책에 노래 추가"""
    import json
    tags_list = json.loads(tag)
    
    streamer = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not streamer:
        raise HTTPException(status_code=403, detail="Streamer profile required")
    
    cover_image_url = None
    if cover_image:
        # Check size (1MB limit)
        content = await cover_image.read()
        if len(content) > 1 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image size exceeds 1MB target (Note: Should be resized by frontend)")
        
        # Upload to R2
        import time
        file_ext = cover_image.filename.split(".")[-1] if "." in cover_image.filename else "jpg"
        object_name = f"covers/{streamer['id']}_{int(time.time())}.{file_ext}"
        await r2_handler.upload_file(content, object_name, cover_image.content_type)
        cover_image_url = f"{settings.cloudflare_public_url.rstrip('/')}/{object_name}"
    
    # 1. Ensure song exists in local DB
    if song_external_id.startswith("it_"):
        artist_id = await song_repo.get_or_create_artist(artist, f"it_artist_{artist}")
        song_id = await song_repo.get_or_create_song(title, song_external_id, artist_id, image_url)
    else:
        res = await song_repo.db.fetch_one("SELECT id FROM songs WHERE song_external_id = %s", (song_external_id,))
        if not res:
            song_id = await song_repo.create_custom_song(title, artist, image_url, user['id'])
        else:
            song_id = res['id']

    # 2. Add to songbook
    entry_id = await songbook_repo.add_song(
        streamer_id=streamer['id'],
        song_id=song_id,
        tags=tags_list,
        difficulty=difficulty,
        memo=description,
        mr_video_id=mr_video_id,
        lyrics_id=lyrics_id,
        user_id=user['id'],
        cover_image_url=cover_image_url,
        price_cheese=price_cheese,
        price_balloon=price_balloon
    )
    return {"id": entry_id}

@router.patch("/{entry_id}")
async def update_song_in_my_songbook(
    entry_id: int,
    tag: Optional[str] = Form(None),
    difficulty: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    mr_video_id: Optional[str] = Form(None),
    lyrics_id: Optional[int] = Form(None),
    price_cheese: Optional[int] = Form(None),
    price_balloon: Optional[int] = Form(None),
    cover_image: Optional[UploadFile] = File(None),
    songbook_repo=Depends(get_songbook_repository),
    streamer_repo=Depends(get_streamer_repository),
    user=Depends(get_current_user_api)
):
    """자신의 노래책 노래 정보 수정"""
    import json
    
    update_data = {}
    if tag is not None:
        update_data['tags'] = json.loads(tag)
    if difficulty is not None:
        update_data['difficulty'] = difficulty
    if description is not None:
        update_data['memo'] = description
    if mr_video_id is not None:
        update_data['mr_video_id'] = mr_video_id
    if lyrics_id is not None:
        update_data['lyrics_id'] = lyrics_id
    if price_cheese is not None:
        update_data['price_cheese'] = price_cheese
    if price_balloon is not None:
        update_data['price_balloon'] = price_balloon

    if cover_image:
        content = await cover_image.read()
        if len(content) > 1 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image size exceeds 1MB")
        
        # Upload to R2
        import time
        streamer = await streamer_repo.get_streamer_by_user_id(user['id'])
        file_ext = cover_image.filename.split(".")[-1] if "." in cover_image.filename else "jpg"
        object_name = f"covers/{streamer['id']}_{int(time.time())}.{file_ext}"
        await r2_handler.upload_file(content, object_name, cover_image.content_type)
        update_data['cover_image_url'] = f"{settings.cloudflare_public_url.rstrip('/')}/{object_name}"
    
    await songbook_repo.update_song(
        entry_id=entry_id,
        **update_data
    )
    return {"success": True}

@router.delete("/{entry_id}")
async def remove_song_from_my_songbook(
    request: Request,
    entry_id: int,
    song_repo=Depends(get_songbook_repository),
    streamer_repo=Depends(get_streamer_repository),
    user=Depends(get_current_user_api)
):
    """자신의 노래책에서 노래 삭제"""
    # 소유권 확인 (간단하게)
    # 실제로는 entry_id가 이 유저의 streamer_id에 속하는지 확인해야 함.
    await song_repo.remove_song(entry_id)
    return {"success": True}
