from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

# Rate Limiter 인스턴스 생성 (IP 기반)
limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Rate limit 초과 시 응답 핸들러"""
    # API 요청인 경우 JSON 응답
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=429,
            content={
                "detail": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
                "retry_after": exc.detail
            }
        )
    # 웹 페이지 요청인 경우
    return JSONResponse(
        status_code=429,
        content={"detail": "Too Many Requests"}
    )


# Rate limit 설정값들
RATE_LIMITS = {
    "auth": "5/minute",        # 로그인, 회원가입 등
    "otp": "3/minute",         # OTP 요청
    "search": "30/minute",     # 검색 요청
    "api": "60/minute",        # 일반 API 요청
}
