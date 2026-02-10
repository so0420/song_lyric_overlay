from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.core.auth import require_admin
from app.database.mariadb import db_handler
from app.utils.mailer import send_email
from app.utils.email_templates import get_inquiry_reply_email
import asyncio

router = APIRouter(prefix="/admin")


class NoticeCreateSchema(BaseModel):
    title: str
    content: str
    is_pinned: bool = False
    is_published: bool = True


class NoticeUpdateSchema(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_published: Optional[bool] = None


class NoticeAdminSchema(BaseModel):
    id: int
    title: str
    is_pinned: bool
    is_published: bool
    view_count: int
    created_at: datetime


class NoticeListResponse(BaseModel):
    notices: List[NoticeAdminSchema]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/notices", response_model=NoticeListResponse)
async def admin_get_notices(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=50),
    search: Optional[str] = Query(None),
    admin=Depends(require_admin)
):
    """관리자용 공지 목록 (모든 공지 포함)"""
    offset = (page - 1) * page_size
    
    if search:
        count_query = """
            SELECT COUNT(*) as total FROM notices
            WHERE title LIKE %s OR content LIKE %s
        """
        search_param = f"%{search}%"
        count_result = await db_handler.fetch_one(count_query, (search_param, search_param))
        
        list_query = """
            SELECT id, title, is_pinned, is_published, view_count, created_at
            FROM notices
            WHERE title LIKE %s OR content LIKE %s
            ORDER BY is_pinned DESC, created_at DESC
            LIMIT %s OFFSET %s
        """
        notices = await db_handler.fetch_all(list_query, (search_param, search_param, page_size, offset))
    else:
        count_query = "SELECT COUNT(*) as total FROM notices"
        count_result = await db_handler.fetch_one(count_query)
        
        list_query = """
            SELECT id, title, is_pinned, is_published, view_count, created_at
            FROM notices
            ORDER BY is_pinned DESC, created_at DESC
            LIMIT %s OFFSET %s
        """
        notices = await db_handler.fetch_all(list_query, (page_size, offset))
    
    total = count_result["total"] if count_result else 0
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    return NoticeListResponse(
        notices=[NoticeAdminSchema(**n) for n in notices] if notices else [],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/notices")
async def admin_create_notice(
    data: NoticeCreateSchema,
    admin=Depends(require_admin)
):
    """공지 생성"""
    query = """
        INSERT INTO notices (title, content, is_pinned, is_published, author_id)
        VALUES (%s, %s, %s, %s, %s)
    """
    notice_id = await db_handler.execute_query(
        query,
        (data.title, data.content, data.is_pinned, data.is_published, admin['id'])
    )
    return {"success": True, "notice_id": notice_id}


@router.put("/notices/{notice_id}")
async def admin_update_notice(
    notice_id: int,
    data: NoticeUpdateSchema,
    admin=Depends(require_admin)
):
    """공지 수정"""
    # 기존 공지 확인
    notice = await db_handler.fetch_one("SELECT * FROM notices WHERE id = %s", (notice_id,))
    if not notice:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    
    # 업데이트할 필드 구성
    updates = []
    params = []
    if data.title is not None:
        updates.append("title = %s")
        params.append(data.title)
    if data.content is not None:
        updates.append("content = %s")
        params.append(data.content)
    if data.is_pinned is not None:
        updates.append("is_pinned = %s")
        params.append(data.is_pinned)
    if data.is_published is not None:
        updates.append("is_published = %s")
        params.append(data.is_published)
    
    if updates:
        params.append(notice_id)
        query = f"UPDATE notices SET {', '.join(updates)} WHERE id = %s"
        await db_handler.execute_query(query, tuple(params))
    
    return {"success": True}


@router.delete("/notices/{notice_id}")
async def admin_delete_notice(
    notice_id: int,
    admin=Depends(require_admin)
):
    """공지 삭제"""
    notice = await db_handler.fetch_one("SELECT * FROM notices WHERE id = %s", (notice_id,))
    if not notice:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    
    await db_handler.execute_query("DELETE FROM notices WHERE id = %s", (notice_id,))
    return {"success": True}


# =====================================================
# 문의 관리 API
# =====================================================

class InquiryAdminSchema(BaseModel):
    id: int
    name: str
    email: str
    subject: str
    status: str
    created_at: datetime


class InquiryListResponse(BaseModel):
    inquiries: List[InquiryAdminSchema]
    total: int
    page: int
    page_size: int
    total_pages: int


class InquiryReplySchema(BaseModel):
    reply: str
    status: str
    send_email: bool = False


@router.get("/inquiries", response_model=InquiryListResponse)
async def admin_get_inquiries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    status: Optional[str] = Query(None),
    admin=Depends(require_admin)
):
    """문의 목록 조회"""
    offset = (page - 1) * page_size
    
    if status:
        count_query = "SELECT COUNT(*) as total FROM contact_inquiries WHERE status = %s"
        count_result = await db_handler.fetch_one(count_query, (status,))
        
        list_query = """
            SELECT id, name, email, subject, status, created_at
            FROM contact_inquiries
            WHERE status = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        inquiries = await db_handler.fetch_all(list_query, (status, page_size, offset))
    else:
        count_query = "SELECT COUNT(*) as total FROM contact_inquiries"
        count_result = await db_handler.fetch_one(count_query)
        
        list_query = """
            SELECT id, name, email, subject, status, created_at
            FROM contact_inquiries
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        inquiries = await db_handler.fetch_all(list_query, (page_size, offset))
    
    total = count_result["total"] if count_result else 0
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    return InquiryListResponse(
        inquiries=[InquiryAdminSchema(**i) for i in inquiries] if inquiries else [],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/inquiries/{inquiry_id}/reply")
async def admin_reply_inquiry(
    inquiry_id: int,
    data: InquiryReplySchema,
    admin=Depends(require_admin)
):
    """문의 답변 저장 및 이메일 발송"""
    
    # 문의 조회
    inquiry = await db_handler.fetch_one(
        "SELECT * FROM contact_inquiries WHERE id = %s",
        (inquiry_id,)
    )
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")
    
    # 답변 저장
    await db_handler.execute_query(
        "UPDATE contact_inquiries SET admin_reply = %s, status = %s WHERE id = %s",
        (data.reply, data.status, inquiry_id)
    )
    
    # 이메일 발송 (비동기 - 백그라운드로 처리)
    email_queued = False
    if data.send_email and data.reply.strip():
        html_content, text_content = get_inquiry_reply_email(
            user_name=inquiry['name'],
            subject=inquiry['subject'],
            original_message=inquiry['message'],
            reply_content=data.reply
        )
        
        # 이메일을 백그라운드로 발송 (응답 지연 방지)
        async def send_email_async():
            await asyncio.to_thread(
                send_email,
                to_email=inquiry['email'],
                subject=f"[PlayList] 문의에 대한 답변: {inquiry['subject']}",
                html_content=html_content,
                text_content=text_content
            )
        
        asyncio.create_task(send_email_async())
        email_queued = True
    
    return {
        "success": True,
        "email_queued": email_queued
    }


