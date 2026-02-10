from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.utils.config import config

router = APIRouter()


@router.get("/favorites", response_class=HTMLResponse)
async def favorites_page(
    request: Request,
    user=Depends(get_current_user)
):
    """즐겨찾기한 스트리머 목록 페이지"""
    return templates.TemplateResponse("pages/favorites/favorites.html", {
        "request": request,
        "user": user,
        "config": config
    })
