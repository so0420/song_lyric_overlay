from fastapi import APIRouter

from .oauth import router as oauth_router
from .songs import router as songs_router
from .youtube import router as youtube_router
from .users import router as users_router
from .lyrics import router as lyrics_router
from .overlay import router as overlay_router
from .auth import router as auth_router
from .health import router as health_router
from .admin import router as admin_router
from .admin_lyrics import router as admin_lyrics_router
from .access import router as access_router
from .streamers import router as streamers_router
from .songbook import router as songbook_router
from .song_requests import router as song_requests_router
from .integrations import router as integrations_router
from .auto_lyrics import router as auto_lyrics_router
from .admin_auto_lyrics import router as admin_auto_lyrics_router

router = APIRouter()
router.include_router(oauth_router, prefix="/oauth", tags=["oauth"])
router.include_router(songs_router, prefix="/songs", tags=["songs"])
router.include_router(youtube_router, prefix="/youtube", tags=["youtube"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(lyrics_router, prefix="/lyrics", tags=["lyrics"])
router.include_router(overlay_router, prefix="/overlay", tags=["overlay"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(health_router, tags=["health"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(admin_lyrics_router, prefix="/admin", tags=["admin-lyrics"])
router.include_router(access_router, prefix="/access", tags=["access"])
router.include_router(streamers_router, prefix="/streamers", tags=["streamers"])
router.include_router(songbook_router, prefix="/songbook", tags=["songbook"])
router.include_router(song_requests_router, prefix="/song-requests", tags=["song-requests"])
router.include_router(integrations_router, prefix="/integrations", tags=["integrations"])
router.include_router(auto_lyrics_router, prefix="/auto-lyrics", tags=["auto-lyrics"])
router.include_router(admin_auto_lyrics_router, prefix="/admin", tags=["admin-auto-lyrics"])

__all__ = ["router"]
