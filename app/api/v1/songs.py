from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from app.core.auth import get_current_user_api
from typing import Optional
from app.services.song_service import SongService, get_song_service

router = APIRouter()

@router.post("/custom")
async def register_custom_song(
    title: str = Form(...),
    artist: str = Form(...),
    image: Optional[UploadFile] = File(None),
    service: SongService = Depends(get_song_service),
    user=Depends(get_current_user_api)
):
    return await service.create_custom_song(
        title=title, 
        artist=artist, 
        image=image, 
        owner_id=user['id']
    )

@router.get("/info")
async def get_song_info(
    external_id: str,
    service: SongService = Depends(get_song_service)
):
    """external_id로 곡 정보 조회"""
    song = await service.get_song_info(external_id)
    
    if song:
        return song

    if external_id.startswith("it_"):
        raise HTTPException(status_code=404, detail="Song not found in local DB. Please add it to songbook first or search again.")
    
    raise HTTPException(status_code=404, detail="Song not found")