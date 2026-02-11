from pydantic import BaseModel
from typing import Generic, TypeVar, List

T = TypeVar('T')


class PaginationParams:
    """페이지네이션 파라미터"""
    def __init__(self, offset: int = 0, limit: int = 20):
        self.offset = max(0, offset)
        self.limit = min(max(1, limit), 100)  # 1~100 사이로 제한


class PaginatedResponse(BaseModel, Generic[T]):
    """페이지네이션 응답"""
    items: List[T]
    total: int
    offset: int
    limit: int
    has_more: bool

    class Config:
        from_attributes = True
