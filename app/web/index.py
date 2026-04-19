from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_current_user, get_admin_user

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("pages/home/index.html", {"request": request, "user": user})

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url='/')
    return templates.TemplateResponse("pages/auth/login.html", {"request": request})

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url='/')
    return templates.TemplateResponse("pages/auth/register.html", {"request": request})

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, user=Depends(get_current_user)):
    if user:
        return RedirectResponse(url='/')
    return templates.TemplateResponse("pages/auth/forgot-password.html", {"request": request})

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url='/')

@router.get("/songs", response_class=HTMLResponse)
async def songs_page(request: Request, user=Depends(get_current_user), admin=Depends(get_admin_user)):
    """가사가 등록된 노래 목록 페이지"""
    return templates.TemplateResponse("pages/songs/index.html", {"request": request, "user": user, "is_admin": admin is not None})

@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request, user=Depends(get_current_user)):
    """사용법 안내 페이지"""
    return templates.TemplateResponse("pages/help/index.html", {"request": request, "user": user})

@router.get("/help/editor", response_class=HTMLResponse)
async def help_editor_page(request: Request, user=Depends(get_current_user)):
    """가사 편집기 사용법"""
    return templates.TemplateResponse("pages/help/editor.html", {"request": request, "user": user})

@router.get("/help/singing", response_class=HTMLResponse)
async def help_singing_page(request: Request, user=Depends(get_current_user)):
    """노래하기 사용법"""
    return templates.TemplateResponse("pages/help/singing.html", {"request": request, "user": user})

@router.get("/help/obs", response_class=HTMLResponse)
async def help_obs_page(request: Request, user=Depends(get_current_user)):
    """OBS 오버레이 설정 사용법"""
    return templates.TemplateResponse("pages/help/obs.html", {"request": request, "user": user})

@router.get("/help/shortcuts", response_class=HTMLResponse)
async def help_shortcuts_page(request: Request, user=Depends(get_current_user)):
    """키보드 단축키"""
    return templates.TemplateResponse("pages/help/shortcuts.html", {"request": request, "user": user})
