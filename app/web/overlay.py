from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.database.mariadb import db_handler
import json

router = APIRouter()

@router.get("/overlay", response_class=HTMLResponse)
async def overlay_page(
    request: Request,
    user=Depends(get_current_user)
):
    """노래하기 페이지"""
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    return templates.TemplateResponse("pages/overlay/overlay.html", {
        "request": request,
        "user": user
    })

@router.get("/overlay/settings", response_class=HTMLResponse)
async def overlay_settings_page(
    request: Request,
    user=Depends(get_current_user)
):
    """오버레이 설정 페이지"""
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    return templates.TemplateResponse("pages/overlay/settings.html", {
        "request": request,
        "user": user
    })

@router.get("/overlay/obs", response_class=HTMLResponse)
async def obs_overlay_page(
    request: Request,
    uid: int = None
):
    """OBS용 오버레이 페이지 (로그인 불필요, uid 파라미터로 사용자 식별)"""
    if not uid:
        return HTMLResponse(content="<p style='color:white;font-family:sans-serif;padding:20px;'>오버레이 URL이 올바르지 않습니다. uid 파라미터가 필요합니다.</p>")

    # 사용자 설정 불러오기
    settings = None
    result = await db_handler.fetch_one(
        "SELECT settings_json FROM user_overlay_settings WHERE user_id = %s",
        (uid,)
    )
    if result and result['settings_json']:
        settings = json.loads(result['settings_json'])

    return templates.TemplateResponse("pages/overlay/obs_overlay.html", {
        "request": request,
        "user_id": uid,
        "settings": settings
    })
