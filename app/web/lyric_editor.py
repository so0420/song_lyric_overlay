from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.database.song_repository import get_song_repository
from app.database.lyrics_repository import get_lyrics_repository
from app.core.auth import get_current_user_api, get_current_user

router = APIRouter()

@router.get("", response_class=HTMLResponse)
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
        song_info = await song_repo.db.fetch_one("SELECT s.*, a.name as artist_name FROM songs s LEFT JOIN artists a ON s.artist_id = a.id WHERE s.id = %s", (song_id,))
    elif external_id:
        song_info = await song_repo.db.fetch_one("SELECT s.*, a.name as artist_name FROM songs s LEFT JOIN artists a ON s.artist_id = a.id WHERE s.song_external_id = %s", (external_id,))
        if song_info:
            song_id = song_info['id']
    
    lyrics_info = None
    if lyrics_id:
        lyrics_info = await lyrics_repo.get_lyrics_by_id(lyrics_id)
        if lyrics_info and not song_info:
            song_id = lyrics_info['song_id']
            song_info = await song_repo.db.fetch_one("SELECT s.*, a.name as artist_name FROM songs s LEFT JOIN artists a ON s.artist_id = a.id WHERE s.id = %s", (song_id,))

    # Find default MR video if in songbook
    default_mr_video_id = None
    if song_id:
        res = await song_repo.db.fetch_one("""
            SELECT l.mr_youtube_video_id FROM streamer_songbooks sb 
            JOIN streamers str ON sb.streamer_id = str.id 
            JOIN song_lyrics l ON sb.lyrics_id = l.id
            WHERE str.user_id = %s AND sb.song_id = %s
        """, (user['id'], song_id))
        if res:
            default_mr_video_id = res['mr_youtube_video_id']

    return templates.TemplateResponse("pages/lyric_editor/lyric_editor.html", {
        "request": request,
        "user": user,
        "song": song_info,
        "lyrics": lyrics_info,
        "default_mr_video_id": default_mr_video_id
    })
