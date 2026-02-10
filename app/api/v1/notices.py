from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.database.mariadb import db_handler

router = APIRouter()


class NoticeSchema(BaseModel):
    id: int
    title: str
    content: Optional[str] = None
    is_pinned: bool
    view_count: int
    created_at: datetime
    updated_at: datetime


class NoticeListItemSchema(BaseModel):
    id: int
    title: str
    is_pinned: bool
    view_count: int
    created_at: datetime


class NoticeListResponse(BaseModel):
    notices: List[NoticeListItemSchema]
    pinned_notices: List[NoticeListItemSchema]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/notices", response_model=NoticeListResponse)
async def get_notices(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    search: Optional[str] = Query(None, max_length=100)
):
    """공지사항 목록 조회 (페이지네이션, 검색 지원)"""
    offset = (page - 1) * page_size
    
    # 고정된 공지 조회 (항상 상단에 표시)
    pinned_query = """
        SELECT id, title, is_pinned, view_count, created_at
        FROM notices
        WHERE is_published = 1 AND is_pinned = 1
        ORDER BY created_at DESC
    """
    pinned_notices = await db_handler.fetch_all(pinned_query)
    
    # 일반 공지 목록 조회
    if search:
        # 검색어가 있는 경우
        count_query = """
            SELECT COUNT(*) as total FROM notices
            WHERE is_published = 1 AND is_pinned = 0
            AND (title LIKE %s OR content LIKE %s)
        """
        search_param = f"%{search}%"
        count_result = await db_handler.fetch_one(count_query, (search_param, search_param))
        
        list_query = """
            SELECT id, title, is_pinned, view_count, created_at
            FROM notices
            WHERE is_published = 1 AND is_pinned = 0
            AND (title LIKE %s OR content LIKE %s)
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        notices = await db_handler.fetch_all(list_query, (search_param, search_param, page_size, offset))
    else:
        # 검색어가 없는 경우
        count_query = """
            SELECT COUNT(*) as total FROM notices
            WHERE is_published = 1 AND is_pinned = 0
        """
        count_result = await db_handler.fetch_one(count_query)
        
        list_query = """
            SELECT id, title, is_pinned, view_count, created_at
            FROM notices
            WHERE is_published = 1 AND is_pinned = 0
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        notices = await db_handler.fetch_all(list_query, (page_size, offset))
    
    total = count_result["total"] if count_result else 0
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    return NoticeListResponse(
        notices=[NoticeListItemSchema(**n) for n in notices] if notices else [],
        pinned_notices=[NoticeListItemSchema(**n) for n in pinned_notices] if pinned_notices else [],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/notices/{notice_id}", response_model=NoticeSchema)
async def get_notice(notice_id: int):
    """공지사항 상세 조회"""
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
    
    return NoticeSchema(**notice)
