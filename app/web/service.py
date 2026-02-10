from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user

router = APIRouter(tags=["web_service"])


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, user=Depends(get_current_user)):
    """개인정보처리방침 페이지"""
    return templates.TemplateResponse(
        "pages/service/privacy.html", 
        {"request": request, "user": user}
    )


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, user=Depends(get_current_user)):
    """이용약관 페이지"""
    return templates.TemplateResponse(
        "pages/service/terms.html", 
        {"request": request, "user": user}
    )


@router.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request, user=Depends(get_current_user)):
    """문의하기 페이지"""
    return templates.TemplateResponse(
        "pages/service/contact.html", 
        {"request": request, "user": user}
    )
