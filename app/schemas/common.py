from pydantic import BaseModel
from typing import Optional, Any, List, Generic, TypeVar
from pydantic.generics import GenericModel

T = TypeVar('T')


class SuccessResponse(BaseModel):
    """표준 성공 응답"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """표준 에러 응답"""
    success: bool = False
    detail: str
    code: Optional[str] = None


class IdResponse(BaseModel):
    """ID 반환 응답"""
    id: int


class TokenResponse(BaseModel):
    """토큰 반환 응답"""
    token: str


class PaginatedResponse(BaseModel):
    """페이지네이션 응답"""
    items: List[Any]
    total: int
    offset: int
    limit: int
    has_more: bool
