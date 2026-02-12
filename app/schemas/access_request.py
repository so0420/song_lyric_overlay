from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class AccessRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class AccessRequestCreateSchema(BaseModel):
    """접근 요청 생성"""
    platform_url: str = Field(..., min_length=1, max_length=500, description="방송 플랫폼 주소")
    message: Optional[str] = Field(None, max_length=1500, description="추가 메시지")


class AccessRequestRejectSchema(BaseModel):
    """접근 요청 거절"""
    reason: str = Field(..., min_length=1, max_length=1000, description="거절 사유")


class AccessRequestResponseSchema(BaseModel):
    """접근 요청 응답"""
    id: int
    user_id: int
    platform_url: str
    message: Optional[str]
    status: AccessRequestStatus
    rejection_reason: Optional[str]
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # 사용자 정보 (관리자 조회용)
    user_name: Optional[str] = None
    user_email: Optional[str] = None

    class Config:
        from_attributes = True


class AccessStatusResponseSchema(BaseModel):
    """접근 상태 응답"""
    approved: bool
    status: Optional[AccessRequestStatus] = None  # None이면 요청 없음
    rejection_reason: Optional[str] = None
    platform_url: Optional[str] = None
    requested_at: Optional[datetime] = None
