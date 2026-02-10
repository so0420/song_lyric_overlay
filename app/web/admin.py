from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from app.utils.templates import templates
from app.core.auth import get_admin_user
from app.database.mariadb import db_handler

router = APIRouter(prefix="/admin", tags=["admin"])


def admin_required(admin_user):
    """관리자 권한 확인 - 없으면 리다이렉트"""
    if not admin_user:
        return RedirectResponse(url="/login?error=admin_required", status_code=302)
    return None


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "user": admin_user, "active_menu": "dashboard"}
    )


@router.get("/notices", response_class=HTMLResponse)
async def admin_notices_list(request: Request, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "admin/notices/list.html",
        {"request": request, "user": admin_user, "active_menu": "notices"}
    )


@router.get("/notices/new", response_class=HTMLResponse)
async def admin_notices_new(request: Request, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "admin/notices/form.html",
        {"request": request, "user": admin_user, "active_menu": "notices", "notice": None}
    )


@router.get("/notices/{notice_id}/edit", response_class=HTMLResponse)
async def admin_notices_edit(request: Request, notice_id: int, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    
    notice = await db_handler.fetch_one(
        "SELECT * FROM notices WHERE id = %s",
        (notice_id,)
    )
    
    if not notice:
        return RedirectResponse(url="/admin/notices", status_code=302)
    
    return templates.TemplateResponse(
        "admin/notices/form.html",
        {"request": request, "user": admin_user, "active_menu": "notices", "notice": notice}
    )


@router.get("/inquiries", response_class=HTMLResponse)
async def admin_inquiries_list(request: Request, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "admin/inquiries/list.html",
        {"request": request, "user": admin_user, "active_menu": "inquiries"}
    )


@router.get("/inquiries/{inquiry_id}", response_class=HTMLResponse)
async def admin_inquiry_detail(request: Request, inquiry_id: int, admin_user=Depends(get_admin_user)):
    redirect = admin_required(admin_user)
    if redirect:
        return redirect
    
    inquiry = await db_handler.fetch_one(
        "SELECT * FROM contact_inquiries WHERE id = %s",
        (inquiry_id,)
    )
    
    if not inquiry:
        return RedirectResponse(url="/admin/inquiries", status_code=302)
    
    return templates.TemplateResponse(
        "admin/inquiries/detail.html",
        {"request": request, "user": admin_user, "active_menu": "inquiries", "inquiry": inquiry}
    )

