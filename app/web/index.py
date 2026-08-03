from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_current_user, get_admin_user

router = APIRouter()

# 개인정보 처리방침·이용약관의 시행일자. 문서 내용을 고칠 때 함께 갱신한다.
LEGAL_EFFECTIVE_DATE = "2026년 8월 3일"

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

@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, user=Depends(get_current_user)):
    """개인정보 처리방침 (로그인 없이 열람 가능해야 한다)"""
    return templates.TemplateResponse("pages/legal/privacy.html", {
        "request": request, "user": user, "effective_date": LEGAL_EFFECTIVE_DATE
    })


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, user=Depends(get_current_user)):
    """이용약관 (로그인 없이 열람 가능해야 한다)"""
    return templates.TemplateResponse("pages/legal/terms.html", {
        "request": request, "user": user, "effective_date": LEGAL_EFFECTIVE_DATE
    })


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
