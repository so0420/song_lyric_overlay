from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import List, Optional
from app.database.song_request_repository import get_song_request_repository
from app.database.streamer_repository import get_streamer_repository
from app.database.songbook_repository import get_songbook_repository
from app.core.auth import get_current_user_api, get_current_user
import random

router = APIRouter()

class SongRequestAddSchema(BaseModel):
    requester: str
    requester_type: str = "MANUAL"
    requester_platform: Optional[str] = None
    song_id: Optional[int] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    streamer_id: Optional[int] = None

class SongRequestUpdateSchema(BaseModel):
    status: Optional[str] = None
    sort_order: Optional[int] = None
    title: Optional[str] = None
    artist: Optional[str] = None

@router.get("/")
async def get_my_song_requests(user=Depends(get_current_user_api), 
                               repo=Depends(get_song_request_repository),
                               streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    requests = await repo.get_requests(profile['id'])
    return requests

@router.post("/")
async def add_song_request(data: SongRequestAddSchema, 
                           repo=Depends(get_song_request_repository),
                           streamer_repo=Depends(get_streamer_repository),
                           user=Depends(get_current_user)):
    # 1. Determine target streamer ID
    target_streamer_id = data.streamer_id
    
    if user:
        # If logged in as a streamer, default to own profile if not specified
        profile = await streamer_repo.get_streamer_by_user_id(user['id'])
        if profile and target_streamer_id is None:
            target_streamer_id = profile['id']
            
    if target_streamer_id is None:
        raise HTTPException(status_code=400, detail="Target streamer ID is required")

    # 2. Check if streamer exists and requests are enabled
    target_profile = await streamer_repo.get_streamer_by_id(target_streamer_id)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Streamer not found")
        
    # If it's a public request (WEB), check if it's enabled
    if data.requester_type == "WEB":
        if not target_profile['request_enabled'] or not target_profile['request_web_enabled']:
            raise HTTPException(status_code=403, detail="Song requests are currently disabled for this streamer.")

    await repo.add_request(
        streamer_id=target_streamer_id,
        requester=data.requester,
        requester_type=data.requester_type,
        requester_platform=data.requester_platform,
        song_id=data.song_id,
        title=data.title,
        artist=data.artist
    )
    return {"success": True}

@router.patch("/{request_id}")
async def update_song_request(request_id: int, 
                              data: SongRequestUpdateSchema, 
                              user=Depends(get_current_user_api), 
                              repo=Depends(get_song_request_repository),
                              streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.update_request(request_id, profile['id'], **data.model_dump(exclude_unset=True))
    return {"success": True}

@router.delete("/{request_id}")
async def delete_song_request(request_id: int, 
                              user=Depends(get_current_user_api), 
                              repo=Depends(get_song_request_repository),
                              streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.delete_request(request_id, profile['id'])
    return {"success": True}

@router.put("/reorder")
async def reorder_song_requests(order_list: List[int] = Body(...), 
                                user=Depends(get_current_user_api), 
                                repo=Depends(get_song_request_repository),
                                streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.reorder_requests(profile['id'], order_list)
    return {"success": True}

@router.delete("/batch/done")
async def delete_done_requests(user=Depends(get_current_user_api), 
                               repo=Depends(get_song_request_repository),
                               streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.delete_done_requests(profile['id'])
    return {"success": True}

@router.delete("/batch/all")
async def delete_all_requests(user=Depends(get_current_user_api), 
                              repo=Depends(get_song_request_repository),
                              streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.delete_all_requests(profile['id'])
    return {"success": True}

@router.post("/batch/random")
async def add_random_requests(n: int = Body(..., embed=True), 
                               user=Depends(get_current_user_api), 
                               repo=Depends(get_song_request_repository),
                               streamer_repo=Depends(get_streamer_repository),
                               songbook_repo=Depends(get_songbook_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    # Get all songs from songbook
    songbook = await songbook_repo.get_songbook(profile['id'], limit=1000)
    if not songbook:
        return {"success": True, "added": 0}
        
    # Pick n random songs
    n = min(n, len(songbook))
    random_songs = random.sample(songbook, n)
    
    for s in random_songs:
        await repo.add_request(
            streamer_id=profile['id'],
            requester="시스템 랜덤",
            requester_type="MANUAL",
            requester_platform="Web",
            song_id=s['song_id']
        )
        
    return {"success": True, "added": len(random_songs)}

@router.post("/next")
async def next_song_request(user=Depends(get_current_user_api), 
                            repo=Depends(get_song_request_repository),
                            streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    next_id = await repo.next_request(profile['id'])
    return {"success": True, "next_id": next_id}

@router.post("/prev")
async def prev_song_request(user=Depends(get_current_user_api), 
                            repo=Depends(get_song_request_repository),
                            streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    prev_id = await repo.prev_request(profile['id'])
    return {"success": True, "prev_id": prev_id}

@router.post("/reset-status")
async def reset_song_requests(user=Depends(get_current_user_api), 
                               repo=Depends(get_song_request_repository),
                               streamer_repo=Depends(get_streamer_repository)):
    profile = await streamer_repo.get_streamer_by_user_id(user['id'])
    if not profile:
        raise HTTPException(status_code=404, detail="Streamer profile not found")
        
    await repo.reset_requests(profile['id'])
    return {"success": True}
