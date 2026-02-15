from fastapi import Request, HTTPException, Depends
from typing import Optional, Dict, Any
from app.schemas.users import CurrentUserSchema
from app.database.mariadb.mariadb import db_handler


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """세션에서 현재 사용자 정보를 반환합니다."""
    return request.session.get('user')


async def get_current_user_api(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> CurrentUserSchema:
    """API용 현재 사용자 (미로그인 시 401 에러)"""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return CurrentUserSchema(**user)


async def get_admin_user(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> Optional[CurrentUserSchema]:
    """관리자 권한 확인 - 웹 페이지용 (리다이렉트)

    DB에서 실시간으로 관리자 권한을 확인하여 세션 위변조 및 권한 박탈 후에도
    즉시 반영되도록 합니다.
    """
    if not user:
        return None

    # DB에서 실시간 관리자 권한 확인
    db_user = await db_handler.fetch_one(
        "SELECT is_admin FROM users WHERE id = %s",
        (user['id'],)
    )

    if not db_user or not db_user.get('is_admin'):
        return None

    return CurrentUserSchema(**user)


async def require_admin(user: Optional[Dict[str, Any]] = Depends(get_current_user)) -> CurrentUserSchema:
    """관리자 권한 필수 - API용 (에러 발생)

    DB에서 실시간으로 관리자 권한을 확인하여 세션 위변조 및 권한 박탈 후에도
    즉시 반영되도록 합니다.
    """
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    # DB에서 실시간 관리자 권한 확인
    db_user = await db_handler.fetch_one(
        "SELECT is_admin FROM users WHERE id = %s",
        (user['id'],)
    )

    if not db_user or not db_user.get('is_admin'):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")

    return CurrentUserSchema(**user)
