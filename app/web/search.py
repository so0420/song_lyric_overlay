from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.utils.config import config

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = None,
    user=Depends(get_current_user)
):
    """스트리머 검색 결과 페이지"""
    return templates.TemplateResponse("pages/search/search.html", {
        "request": request,
        "user": user,
        "config": config,
        "query": q
    })
