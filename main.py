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
from contextlib import asynccontextmanager
from app.integrations.ITunes_search_api import itunes_api
from app.integrations.youtube_api import youtube_api
from app.integrations.chzzk_api import chzzk_api
from app.database.mariadb import db_handler
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.cloudflare.r2 import r2_handler
from app.database.redis.redis import redis
from app.core.websocket import ws_manager
from app.integrations.chzzk_connection.chzzk_connection_client import chzzk_connection_client


# 리소스 관리를 위한 lifespan 정의
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시 실행
    await db_handler.initialize()
    await itunes_api.initialize()
    await youtube_api.initialize()
    await chzzk_api.initialize()
    await meilisearch_handler.initialize()
    await r2_handler.initialize()
    await redis.initialize()
    await ws_manager.start()

    # Chzzk 토큰 갱신 백그라운드 태스크 시작
    from app.services.chzzk_token_service import ChzzkTokenService
    token_service = ChzzkTokenService(db_handler)
    refresh_task = asyncio.create_task(token_service.start_background_refresh())

    # Chzzk Connection Socket 서버 연결 클라이언트 백그라운드 태스크
    connection_client_task = asyncio.create_task(chzzk_connection_client.start())

    yield
    # 종료 시 실행
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass
    connection_client_task.cancel()
    try:
        await connection_client_task
    except asyncio.CancelledError:
        pass
    
    await chzzk_connection_client.disconnect()
    await db_handler.close()
    await itunes_api.close()
    await youtube_api.close()
    await chzzk_api.close()
    await meilisearch_handler.close()
    await r2_handler.close()
    await ws_manager.stop()
    await redis.close()

# FastAPI 애플리케이션 생성
app = FastAPI(lifespan=lifespan)

# Uvicorn 로깅 설정 (워커 프로세스에서도 적용되도록 최상단에서 실행)
setup_uvicorn_logging()


# 세션 만료 시간 설정 (0이면 브라우저 종료 시 만료가 아니라 반영구 유지를 위해 None 또는 매우 큰 값 사용)
# Starlette SessionMiddleware의 max_age가 None이면 브라우저 종료 시 만료됨.
session_max_age = settings.jwt_access_token_ttl if settings.jwt_access_token_ttl > 0 else 315360000 # env 저장된 값이 0이면 약 10년

app.add_middleware(SessionMiddleware, secret_key=settings.jwt_secret_key, max_age=session_max_age)

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

@app.get('/socket_test')
async def socket_test(request: Request, user=Depends(get_current_user_api)):
    """
    현재 접속 중인 유저의 스트리머 채널에 테스트 웹소켓 메시지를 보냅니다.
    """
    # 유저의 스트리머 ID 조회
    streamer = await db_handler.fetch_one("SELECT id FROM streamers WHERE user_id = %s", (user['id'],))
    if not streamer:
        return {"success": False, "message": "Streamer profile not found for this user"}
        
    await ws_manager.publish_event(
        streamer_id=str(streamer['id']),
        event_type="TEST_EVENT",
        data={
            "message": "스트리머 채널로 보낸 테스트 메시지입니다!",
            "time": time.time()
        }
    )
    return {"success": True, "message": f"Test event published to streamer {streamer['id']}"}

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
        uvicorn.run("main:app", host=host, port=port)
    elif environment == "local":
        logger.info('Server Starting in local...')
        uvicorn.run("main:app", host=host, port=port, reload=False)

