from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.database.song_repository import get_song_repository
from app.database.lyrics_repository import get_lyrics_repository
from app.core.auth import get_current_user_api, get_current_user

router = APIRouter()

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def lyric_editor_page(
    request: Request,
    song_id: int = None,
    lyrics_id: int = None,
    external_id: str = None,
    user=Depends(get_current_user),
    song_repo=Depends(get_song_repository),
    lyrics_repo=Depends(get_lyrics_repository)
):
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    song_info = None
    if song_id:
        song_info = await song_repo.get_song_with_artist(song_id=song_id)
    elif external_id:
        song_info = await song_repo.get_song_with_artist(external_id=external_id)
        if song_info:
            song_id = song_info['id']

    lyrics_info = None
    if lyrics_id:
        lyrics_info = await lyrics_repo.get_lyrics_by_id(lyrics_id)
        if lyrics_info and not song_info:
            song_id = lyrics_info['song_id']
            song_info = await song_repo.get_song_with_artist(song_id=song_id)

    return templates.TemplateResponse("pages/lyric_editor/lyric_editor.html", {
        "request": request,
        "user": user,
        "song": song_info,
        "lyrics": lyrics_info,
        "default_mr_video_id": None
    })
