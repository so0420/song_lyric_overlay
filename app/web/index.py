from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_current_user

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
