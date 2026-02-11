from fastapi import APIRouter

from .oauth import router as oauth_router
from .songs import router as songs_router
from .youtube import router as youtube_router
from .users import router as users_router
from .lyrics import router as lyrics_router
from .overlay import router as overlay_router
from .auth import router as auth_router

router = APIRouter()
router.include_router(oauth_router, prefix="/oauth", tags=["oauth"])
router.include_router(songs_router, prefix="/songs", tags=["songs"])
router.include_router(youtube_router, prefix="/youtube", tags=["youtube"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(lyrics_router, prefix="/lyrics", tags=["lyrics"])
router.include_router(overlay_router, prefix="/overlay", tags=["overlay"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])

__all__ = ["router"]
