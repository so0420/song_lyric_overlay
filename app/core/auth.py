from fastapi import Request, HTTPException, Depends
from typing import Optional, Dict, Any
from app.schemas.users import CurrentUserSchema


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """세션에서 현재 사용자 정보를 반환합니다."""
    return request.session.get('user')


async def get_current_user_api(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> CurrentUserSchema:
    """API용 현재 사용자 (미로그인 시 401 에러)"""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return CurrentUserSchema(**user)


async def get_admin_user(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Optional[CurrentUserSchema]:
    """관리자 권한 확인 - 웹 페이지용 (리다이렉트)"""
    if not user:
        return None
    if not user.get('is_admin'):
        return None
    return CurrentUserSchema(**user)


async def require_admin(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> CurrentUserSchema:
    """관리자 권한 필수 - API용 (에러 발생)"""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    if not user.get('is_admin'):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return CurrentUserSchema(**user)
