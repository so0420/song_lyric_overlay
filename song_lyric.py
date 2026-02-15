import os
import time
import asyncio
from dotenv import load_dotenv

# 환경변수 로드 (최상단에서 실행하여 이후 임포트되는 모듈들이 환경변수를 올바르게 참조하도록 함)
load_dotenv()

from fastapi import FastAPI, Request, Depends
from app.utils.templates import templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.utils.config import config, settings
from app.api import router as api_router
from app.web.router import router as web_router
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.utils.custom_exceptions import (
    CustomHTTPException,
    custom_http_exception_handler,
    http_exception_handler,
    global_exception_handler
)
from app.core.auth import get_current_user_api, get_current_user

from app.utils.log import logger, setup_uvicorn_logging
from app.utils.rate_limit import limiter, rate_limit_exceeded_handler
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from app.integrations.itunes_search_api import itunes_api
from app.integrations.youtube_api import youtube_api
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.redis.redis import redis


# 리소스 관리를 위한 lifespan 정의
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 실행
    await db_handler.initialize()
    await itunes_api.initialize()
    await youtube_api.initialize()
    await meilisearch_handler.initialize()
    await redis.initialize()

    yield
    # 종료 시 실행
    await db_handler.close()
    await itunes_api.close()
    await youtube_api.close()
    await meilisearch_handler.close()
    await redis.close()

# FastAPI 애플리케이션 생성
app = FastAPI(lifespan=lifespan)

# Rate Limiter 설정
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Uvicorn 로깅 설정 (워커 프로세스에서도 적용되도록 최상단에서 실행)
setup_uvicorn_logging()


# 세션 만료 시간 설정 (0이면 브라우저 종료 시 만료가 아니라 반영구 유지를 위해 None 또는 매우 큰 값 사용)
# Starlette SessionMiddleware의 max_age가 None이면 브라우저 종료 시 만료됨.
session_max_age = settings.jwt_access_token_ttl if settings.jwt_access_token_ttl > 0 else 315360000 # env 저장된 값이 0이면 약 10년

app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key, max_age=session_max_age)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """보안 헤더 추가 미들웨어"""
    response = await call_next(request)

    # 보안 헤더 추가
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # HTTPS 환경에서만 HSTS 적용
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000

    # 정적 파일 등 너무 많은 로그 방지를 위해 필터링 가능 (필요시)
    # if not request.url.path.startswith("/static"):
    #     logger.info(f"ACCESS: {request.method} {request.url.path} - {response.status_code} ({process_time:.2f}ms)")

    return response

# Static 폴더 마운트
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Exception Handlers 등록
app.add_exception_handler(CustomHTTPException, custom_http_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

@app.get("/hello-world")
def hello_world(request: Request, user=Depends(get_current_user_api)):
    return {"message": "Hello World!"}

@app.get('/me')
async def me(request: Request, user=Depends(get_current_user_api)):
    return user

@app.get('/error')
def error_500(request: Request):
    return templates.TemplateResponse("error_pages/error.html", {"request": request})

@app.get('/error-404')
def error_404(request: Request):
    return templates.TemplateResponse("error_pages/404.html", {"request": request})

@app.get('/error-500')
def error_500(request: Request):
    return templates.TemplateResponse("error_pages/500.html", {"request": request})

# 라우터 연결
app.include_router(api_router, prefix="/api")
app.include_router(web_router)

if __name__ == "__main__":
    import uvicorn
    # setup_uvicorn_logging() # 이미 위에서 호출됨

    host = settings.server_host
    port = settings.server_port

    environment = settings.environment
    if environment == "production":
        logger.info('Server Starting in production...')
        uvicorn.run("song_lyric:app", host=host, port=port)
    elif environment == "local":
        logger.info('Server Starting in local...')
        uvicorn.run("song_lyric:app", host=host, port=port, reload=False)
