from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.database.streamer_repository import get_streamer_repository
from app.core.auth import get_current_user
from app.utils.config import config, settings

router = APIRouter()

@router.get("/mypage", response_class=HTMLResponse)
async def mypage(
    request: Request,
    user=Depends(get_current_user),
    streamer_repo=Depends(get_streamer_repository)
):

    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")
    
    # Check if user is already a streamer
    streamer = await streamer_repo.get_streamer_by_user_id(user['id'])
    
    return templates.TemplateResponse("pages/user/mypage.html", {
        "request": request,
        "user": user,
        "is_streamer": streamer is not None,
        "streamer": streamer,
        "config": config,
        "settings": settings
    })
