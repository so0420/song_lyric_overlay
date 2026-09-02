import re

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.database.song_repository import get_song_repository
from app.database.lyrics_repository import get_lyrics_repository
from app.core.auth import get_current_user
from app.core.lyrics_access import can_view_lyrics
from app.utils.audio_sniff import ALLOWED_AUDIO
from app.utils.audio_storage import MAX_AUDIO_BYTES

router = APIRouter()

# 유튜브 영상 ID(11자). 노래하기 화면이 넘겨준 값을 그대로 믿지 않는다.
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def lyric_editor_page(
    request: Request,
    song_id: int = None,
    lyrics_id: int = None,
    external_id: str = None,
    video_id: str = None,
    user=Depends(get_current_user),
    song_repo=Depends(get_song_repository),
    lyrics_repo=Depends(get_lyrics_repository),
):

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

        # visibility 접근 권한 체크
        if lyrics_info and not await can_view_lyrics(lyrics_info, user, lyrics_repo):
            return RedirectResponse(url="/songs?error=forbidden", status_code=303)

    # 노래하기 화면의 '가사 만들기'로 들어온 경우, 부르던 MR 을 기본 영상으로 채워 준다
    # (기존 가사를 여는 경우엔 그 가사의 MR 이 우선이므로 템플릿에서 무시된다)
    default_mr_video_id = video_id if video_id and YOUTUBE_VIDEO_ID_RE.match(video_id) else None

    is_admin = bool(user and user.get('is_admin'))
    is_owner = bool(user and lyrics_info and lyrics_info.get('owner_id') == user['id'])

    return templates.TemplateResponse("pages/lyric_editor/lyric_editor.html", {
        "request": request,
        "user": user,
        "song": song_info,
        "lyrics": lyrics_info,
        "default_mr_video_id": default_mr_video_id,
        "is_admin": is_admin,
        "is_owner": is_owner,
        # 업로드 한도/허용 형식은 서버가 한 곳에서 정한다 (프론트에 상수를 중복하지 않기 위해)
        "max_audio_bytes": MAX_AUDIO_BYTES,
        "allowed_audio_exts": sorted(set(ALLOWED_AUDIO.values())),
    })
