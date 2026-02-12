from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.database.overlay_repository import get_overlay_repository
from app.database.access_request_repository import get_access_request_repository
from app.utils.ws_token import generate_overlay_token_async, verify_overlay_token_async

router = APIRouter()


async def check_overlay_access(user, request: Request):
    """오버레이 접근 권한 확인 - 승인되지 않은 경우 접근 요청 페이지로 리다이렉트"""
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    repo = get_access_request_repository()
    is_approved = await repo.is_user_approved(user['id'])

    if not is_approved:
        return RedirectResponse(url="/overlay/access-request", status_code=302)

    return None  # 접근 허용


@router.get("/overlay", response_class=HTMLResponse)
async def overlay_page(
    request: Request,
    user=Depends(get_current_user)
):
    """노래하기 페이지"""
    # 접근 권한 확인
    access_check = await check_overlay_access(user, request)
    if access_check:
        return access_check

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
    # 접근 권한 확인
    access_check = await check_overlay_access(user, request)
    if access_check:
        return access_check

    # OBS용 오버레이 토큰 생성
    overlay_token = await generate_overlay_token_async(user['id'])

    return templates.TemplateResponse("pages/overlay/settings.html", {
        "request": request,
        "user": user,
        "overlay_token": overlay_token
    })


@router.get("/overlay/access-request", response_class=HTMLResponse)
async def access_request_page(
    request: Request,
    user=Depends(get_current_user)
):
    """오버레이 접근 요청 페이지"""
    if not user:
        return HTMLResponse(content="<script>alert('로그인이 필요합니다.'); window.location.href='/login';</script>")

    # 이미 승인된 경우 오버레이 페이지로 리다이렉트
    repo = get_access_request_repository()
    is_approved = await repo.is_user_approved(user['id'])
    if is_approved:
        return RedirectResponse(url="/overlay", status_code=302)

    # 최근 요청 정보 가져오기
    latest_request = await repo.get_user_latest_request(user['id'])

    return templates.TemplateResponse("pages/overlay/access_request.html", {
        "request": request,
        "user": user,
        "latest_request": latest_request
    })

@router.get("/overlay/obs", response_class=HTMLResponse)
async def obs_overlay_page(
    request: Request,
    token: str = None
):
    """OBS용 오버레이 페이지 (토큰 기반 인증)"""
    user_id = None

    if token:
        user_id = await verify_overlay_token_async(token)
        if not user_id:
            return HTMLResponse(content="<p style='color:white;font-family:sans-serif;padding:20px;'>유효하지 않은 오버레이 토큰입니다. 설정 페이지에서 새 URL을 복사해주세요.</p>")

    if not user_id:
        return HTMLResponse(content="<p style='color:white;font-family:sans-serif;padding:20px;'>오버레이 URL이 올바르지 않습니다. 설정 페이지에서 URL을 복사해주세요.</p>")

    # 사용자 설정 불러오기
    overlay_repo = get_overlay_repository()
    settings = await overlay_repo.get_settings(user_id)

    return templates.TemplateResponse("pages/overlay/obs_overlay.html", {
        "request": request,
        "user_id": user_id,
        "overlay_token": token,
        "settings": settings
    })
