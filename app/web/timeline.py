from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user

router = APIRouter()


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_page(
    request: Request,
    user=Depends(get_current_user)
):
    """노래 타임라인 조회 페이지"""
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    return templates.TemplateResponse("pages/timeline/timeline.html", {
        "request": request,
        "user": user
    })
