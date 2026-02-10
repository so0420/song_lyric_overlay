from fastapi import APIRouter
from .index import router as index_router
from .streamer import router as streamer_router
from .user import router as user_router
from .lyric_editor import router as lyric_editor_router
from .service import router as service_router
from .notices import router as notices_router
from .admin import router as admin_router
from .favorites import router as favorites_router
from .search import router as search_router

router = APIRouter()
router.include_router(index_router)
router.include_router(user_router)
router.include_router(lyric_editor_router, prefix="/lyrics", tags=["web_lyrics"])
router.include_router(service_router)
router.include_router(notices_router)
router.include_router(admin_router)
router.include_router(favorites_router)
router.include_router(search_router)
router.include_router(streamer_router)

__all__ = ["router"]



