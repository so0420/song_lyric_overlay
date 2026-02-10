from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.utils.templates import templates
from app.core.auth import get_current_user
from app.database.mariadb import db_handler

router = APIRouter(tags=["web_notices"])


@router.get("/notices", response_class=HTMLResponse)
async def notices_list_page(request: Request, user=Depends(get_current_user)):
    """공지사항 목록 페이지"""
    search = request.query_params.get("search", "")
    return templates.TemplateResponse(
        "pages/notices/list.html",
        {"request": request, "user": user, "search": search}
    )


@router.get("/notices/{notice_id}", response_class=HTMLResponse)
async def notice_detail_page(request: Request, notice_id: int, user=Depends(get_current_user)):
    """공지사항 상세 페이지"""
    # 공지 조회
    query = """
        SELECT id, title, content, is_pinned, view_count, created_at, updated_at
        FROM notices
        WHERE id = %s AND is_published = 1
    """
    notice = await db_handler.fetch_one(query, (notice_id,))
    
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    
    # 조회수 증가
    update_query = "UPDATE notices SET view_count = view_count + 1 WHERE id = %s"
    await db_handler.execute_query(update_query, (notice_id,))
    
    return templates.TemplateResponse(
        "pages/notices/detail.html",
        {"request": request, "user": user, "notice": notice}
    )
