from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse


def get_rate_limit_key(request: Request) -> str:
    """
    Rate limit 키 생성 함수
    - 로그인한 사용자: user:{user_id}
    - 비로그인: IP 주소
    """
    # 세션에서 사용자 정보 확인
    if hasattr(request, 'session') and request.session:
        user = request.session.get('user')
        if user and user.get('id'):
            return f"user:{user['id']}"

    # 비로그인 시 IP 기반
    return get_remote_address(request)


# Rate Limiter 인스턴스 생성 (사용자/IP 기반)
limiter = Limiter(key_func=get_rate_limit_key)


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
    "song_request": "10/minute",  # 노래 신청 (비로그인 시청자 포함)
    "upload_minute": "3/minute",  # 음원 업로드 (연타 방지)
    "upload_hour": "20/hour",     # 음원 업로드 (하루치 폭주 방지)
    # 커버 이미지 업로드 — 곡을 여러 개 등록하며 연달아 올리는 흐름이 정상이라
    # 음원보다 넉넉하다. 대신 파일이 작고(브라우저가 640px 로 줄여 보낸다) 서버 한도가 있다.
    "cover_upload_minute": "20/minute",
    "cover_upload_hour": "300/hour",
}
