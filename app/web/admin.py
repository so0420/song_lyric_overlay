from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_admin_user
from app.database.access_request_repository import get_access_request_repository

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, user=Depends(get_admin_user)):
    """관리자 대시보드"""
    if not user:
        return RedirectResponse(url="/login")

    # 대기 중인 요청 수 가져오기
    repo = get_access_request_repository()
    pending_count = await repo.get_pending_count()

    return templates.TemplateResponse("pages/admin/index.html", {
        "request": request,
        "user": user,
        "pending_access_requests": pending_count
    })


@router.get("/websocket", response_class=HTMLResponse)
async def websocket_monitor(request: Request, user=Depends(get_admin_user)):
    """WebSocket 연결 모니터링"""
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("pages/admin/websocket_monitor.html", {
        "request": request,
        "user": user
    })


@router.get("/access-requests", response_class=HTMLResponse)
async def access_requests_page(request: Request, user=Depends(get_admin_user)):
    """접근 요청 관리 페이지"""
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("pages/admin/access_requests.html", {
        "request": request,
        "user": user
    })


@router.get("/song-edit", response_class=HTMLResponse)
async def song_edit_page(request: Request, user=Depends(get_admin_user)):
    """곡 정보 수정 페이지 (가사 있는 곡 + 노래책 등록 곡)"""
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("pages/admin/song_edit.html", {
        "request": request,
        "user": user
    })
