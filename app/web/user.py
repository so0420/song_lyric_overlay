from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user

router = APIRouter()

@router.get("/mypage", response_class=HTMLResponse)
async def mypage(
    request: Request,
    user=Depends(get_current_user)
):

    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    return templates.TemplateResponse("pages/user/mypage.html", {
        "request": request,
        "user": user
    })
