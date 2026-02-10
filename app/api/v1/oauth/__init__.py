from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .google_oauth import router as google_oauth_router
from .naver_oauth import router as naver_oauth_router
from .chzzk_oauth import router as chzzk_oauth_router

router = APIRouter()
router.include_router(google_oauth_router, prefix="/google", tags=["google_oauth"])
router.include_router(naver_oauth_router, prefix="/naver", tags=["naver_oauth"])
router.include_router(chzzk_oauth_router, prefix="/chzzk", tags=["chzzk_oauth"])

@router.get("/logout")
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')

__all__ = ["router"]
