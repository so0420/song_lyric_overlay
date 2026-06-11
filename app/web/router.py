from fastapi import APIRouter
from .index import router as index_router
from .user import router as user_router
from .lyric_editor import router as lyric_editor_router
from .overlay import router as overlay_router
from .admin import router as admin_router
from .songbook import router as songbook_router

router = APIRouter()
router.include_router(index_router)
router.include_router(user_router)
router.include_router(lyric_editor_router, prefix="/lyrics", tags=["web_lyrics"])
router.include_router(overlay_router)
router.include_router(admin_router, tags=["admin"])
router.include_router(songbook_router, tags=["web_songbook"])

__all__ = ["router"]
