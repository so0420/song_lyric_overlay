import secrets
from fastapi import Request, HTTPException, Header
from typing import Optional

CSRF_TOKEN_KEY = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def get_csrf_token(request: Request) -> str:
    """세션에서 CSRF 토큰을 가져오거나 새로 생성"""
    if not hasattr(request, 'session'):
        return ""
    if CSRF_TOKEN_KEY not in request.session:
        request.session[CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)
    return request.session[CSRF_TOKEN_KEY]


def validate_csrf_token(request: Request, token: str) -> bool:
    """CSRF 토큰 검증"""
    session_token = request.session.get(CSRF_TOKEN_KEY)
    if not session_token or not token:
        return False
    return secrets.compare_digest(session_token, token)


async def verify_csrf(
    request: Request,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token")
):
    """Form/AJAX 요청의 CSRF 토큰을 검증하는 의존성

    토큰은 X-CSRF-Token 헤더로 전달해야 합니다.
    JSON 요청은 SameSite 쿠키와 CORS로 보호되므로 검증을 건너뜁니다.
    """
    # JSON API 요청은 CSRF 검증 제외 (SameSite 쿠키 + CORS로 보호)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return True

    # 헤더에서 토큰 확인
    if not validate_csrf_token(request, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다. X-CSRF-Token 헤더를 확인해주세요.")

    return True
