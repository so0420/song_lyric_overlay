from fastapi import Request, HTTPException, Depends
from app.utils.config import settings
from app.utils.log import logger

def get_current_user(request: Request):
    user = request.session.get('user')
    if user:
        print(f"User info: id={user['id']}, name={user['name']}")
    return user

async def get_current_user_api(user = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user

async def get_admin_user(user = Depends(get_current_user)):
    """관리자 권한 확인 - 웹 페이지용 (리다이렉트)"""
    if not user:
        return None
    if not user.get('is_admin'):
        return None
    return user

async def require_admin(user = Depends(get_current_user)):
    """관리자 권한 필수 - API용 (에러 발생)"""
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    if not user.get('is_admin'):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user
