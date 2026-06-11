"""노래책 웹 페이지 라우트

- /songbook   : 노래책 관리 페이지 (로그인 + 오버레이 사용 승인 필요)
- /@{slug}    : 공개 노래책 페이지 (비로그인 열람 가능)
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.utils.templates import templates
from app.core.auth import get_current_user
from app.database.access_request_repository import get_access_request_repository
from app.database.streamer_repository import get_streamer_repository

router = APIRouter()


async def check_songbook_access(user, request: Request):
    """노래책 관리 접근 권한 확인 - 승인되지 않은 경우 접근 요청 페이지로 리다이렉트

    (오버레이 승인 = 노래책 승인 — app/web/overlay.py 의 check_overlay_access 와 동일 정책)
    """
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    repo = get_access_request_repository()
    is_approved = await repo.is_user_approved(user['id'])

    if not is_approved:
        return RedirectResponse(url="/overlay/access-request", status_code=302)

    return None  # 접근 허용


@router.get("/songbook", response_class=HTMLResponse)
async def songbook_dashboard_page(
    request: Request,
    user=Depends(get_current_user)
):
    """노래책 관리 페이지"""
    # 접근 권한 확인
    access_check = await check_songbook_access(user, request)
    if access_check:
        return access_check

    return templates.TemplateResponse("pages/songbook/dashboard.html", {
        "request": request,
        "user": user
    })


@router.get("/@{slug}", response_class=HTMLResponse)
async def public_songbook_page(
    slug: str,
    request: Request,
    user=Depends(get_current_user)
):
    """공개 노래책 페이지 (비로그인 열람 가능, 미승인/탈퇴 스트리머는 404)"""
    repo = get_streamer_repository()
    streamer = await repo.get_public_by_slug(slug)
    if not streamer:
        raise HTTPException(status_code=404, detail="노래책을 찾을 수 없습니다.")

    # 템플릿에는 외부 UUID 만 노출 (내부 id 미노출).
    # social_links/tags 는 repository 가 이미 파싱된 list 로 반환한다.
    return templates.TemplateResponse("pages/songbook/songbook_view.html", {
        "request": request,
        "user": user,
        "streamer": {
            "id": streamer["streamer_id"],
            "slug": streamer["slug"],
            "name": streamer["name"],
            "description": streamer.get("description"),
            "social_links": streamer.get("social_links", []),
            "tags": streamer.get("tags", []),
            "picture": streamer.get("picture"),
            "request_enabled": bool(streamer.get("request_enabled")),
            "request_web_enabled": bool(streamer.get("request_web_enabled")),
        }
    })
