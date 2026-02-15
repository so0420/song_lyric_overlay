import secrets
from urllib.parse import urlparse
from fastapi import Request, HTTPException, Header
from typing import Optional
from app.utils.config import config

CSRF_TOKEN_KEY = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# 허용된 Origin 목록 (config에서 app_url 기반)
def get_allowed_origins() -> set:
    """허용된 Origin 목록 반환"""
    origins = set()
    if config.app_url:
        parsed = urlparse(config.app_url)
        origins.add(f"{parsed.scheme}://{parsed.netloc}")
    # 로컬 개발 환경 추가
    origins.add("http://localhost:8080")
    origins.add("http://127.0.0.1:8080")
    return origins


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


def validate_origin(request: Request) -> bool:
    """Origin/Referer 헤더 검증 (JSON 요청용)"""
    allowed_origins = get_allowed_origins()

    # Origin 헤더 확인
    origin = request.headers.get("origin")
    if origin:
        return origin in allowed_origins

    # Referer 헤더 확인 (Origin이 없는 경우)
    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        referer_origin = f"{parsed.scheme}://{parsed.netloc}"
        return referer_origin in allowed_origins

    # Same-origin 요청은 Origin/Referer가 없을 수 있음 (일부 브라우저)
    # 이 경우 허용하되, 명시적 CSRF 토큰이 있으면 더 안전
    return True


async def verify_csrf(
    request: Request,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token")
):
    """Form/AJAX 요청의 CSRF 토큰을 검증하는 의존성

    토큰은 X-CSRF-Token 헤더로 전달해야 합니다.
    JSON/AJAX 요청은 Origin 검증 + SameSite 쿠키로 보호됩니다.
    """
    # sec-fetch-site: same-origin 은 브라우저가 보장하는 same-origin 요청
    # 이 헤더는 위조 불가능하므로 신뢰함
    if request.headers.get("sec-fetch-site") == "same-origin":
        return True

    content_type = request.headers.get("content-type", "")

    # JSON API 요청 또는 AJAX 요청 (body 없는 POST 등): Origin/Referer 검증
    is_ajax = (
        "application/json" in content_type or
        request.headers.get("x-requested-with") == "XMLHttpRequest" or
        request.headers.get("sec-fetch-mode") == "cors"
    )

    if is_ajax:
        if not validate_origin(request):
            raise HTTPException(status_code=403, detail="잘못된 요청 출처입니다.")
        return True

    # CSRF 토큰이 제공된 경우 검증
    if x_csrf_token:
        if not validate_csrf_token(request, x_csrf_token):
            raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다.")
        return True

    # 토큰이 없으면 Origin/Referer 검증으로 대체
    if not validate_origin(request):
        raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다. X-CSRF-Token 헤더를 확인해주세요.")

    return True
