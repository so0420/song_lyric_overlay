from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.core.auth import get_current_user_api
from app.database.mariadb import db_handler
from app.utils.log import logger

router = APIRouter()


class ContactRequestSchema(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str


class ContactResponseSchema(BaseModel):
    success: bool
    message: str
    inquiry_id: Optional[int] = None


@router.post("/contact", response_model=ContactResponseSchema)
async def submit_contact(
    data: ContactRequestSchema,
    user=Depends(get_current_user_api)
):
    """문의하기 API - 비로그인 사용자도 이용 가능"""
    try:
        user_id = user.get("id") if user else None
        
        query = """
            INSERT INTO contact_inquiries (user_id, name, email, subject, message)
            VALUES (%s, %s, %s, %s, %s)
        """
        
        result = await db_handler.execute_query(
            query,
            (user_id, data.name, data.email, data.subject, data.message)
        )
        
        return ContactResponseSchema(
            success=True,
            message="문의가 성공적으로 접수되었습니다.",
            inquiry_id=result
        )
    except Exception as e:
        logger.error(f"문의 접수 중 오류가 발생했습니다: {str(e)}")
        raise HTTPException(status_code=500, detail=f"문의 접수 중 오류가 발생했습니다: {str(e)}")
