from fastapi import APIRouter

from .oauth import router as oauth_router
from .songbook import router as songbook_router
from .search import router as search_router
from .songs import router as songs_router
from .youtube import router as youtube_router
from .streamers import router as streamers_router
from .users import router as users_router
from .lyrics import router as lyrics_router
from .contact import router as contact_router
from .notices import router as notices_router
from .admin import router as admin_router
from .websocket import router as websocket_router
from .follows import router as follows_router
from .integrations import router as integrations_router
from .song_requests import router as song_requests_router

router = APIRouter()
router.include_router(oauth_router, prefix="/oauth", tags=["oauth"])
router.include_router(songbook_router, prefix="/songbook", tags=["songbook"])
router.include_router(search_router, prefix="/search", tags=["search"])
router.include_router(songs_router, prefix="/songs", tags=["songs"])
router.include_router(youtube_router, prefix="/youtube", tags=["youtube"])
router.include_router(streamers_router, prefix="/streamers", tags=["streamers"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(lyrics_router, prefix="/lyrics", tags=["lyrics"])
router.include_router(contact_router, tags=["contact"])
router.include_router(notices_router, tags=["notices"])
router.include_router(admin_router, tags=["admin"])
router.include_router(websocket_router, prefix="/ws", tags=["websocket"])
router.include_router(follows_router, prefix="/follows", tags=["follows"])
router.include_router(integrations_router, prefix="/integrations", tags=["integrations"])
router.include_router(song_requests_router, prefix="/song-requests", tags=["song-requests"])

__all__ = ["router"]

