from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.database.mariadb import db_handler

router = APIRouter()

@router.get("/mypage", response_class=HTMLResponse)
async def mypage(
    request: Request,
    user=Depends(get_current_user)
):

    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    # 프로필 사진은 세션이 아니라 DB 에서 읽는다. 세션에 넣어두면 다른 기기/탭에서
    # 바꾼 사진이 반영되지 않고, 사진을 지운 뒤에도 옛 URL 이 남는다.
    db_user = await db_handler.fetch_one(
        "SELECT picture FROM users WHERE id = %s",
        (user['id'],)
    )

    return templates.TemplateResponse("pages/user/mypage.html", {
        "request": request,
        "user": user,
        "picture": db_user.get("picture") if db_user else None
    })
