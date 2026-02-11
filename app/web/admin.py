from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_admin_user

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, user=Depends(get_admin_user)):
    """관리자 대시보드"""
    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("pages/admin/index.html", {
        "request": request,
        "user": user
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
