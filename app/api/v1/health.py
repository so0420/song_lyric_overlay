from fastapi import APIRouter
from app.database.mariadb import db_handler
from app.database.redis.redis import redis
from app.database.meilisearch.meilisearch import meilisearch_handler

router = APIRouter()


@router.get("/health")
async def health_check():
    """기본 헬스 체크 (항상 200 반환)"""
    return {"status": "ok"}


@router.get("/health/detailed")
async def detailed_health_check():
    """상세 헬스 체크 (각 서비스 연결 상태 확인)"""
    health_status = {
        "status": "ok",
        "services": {}
    }

    # MariaDB 체크
    try:
        await db_handler.fetch_one("SELECT 1")
        health_status["services"]["database"] = {"status": "ok"}
    except Exception as e:
        health_status["services"]["database"] = {"status": "error", "message": str(e)}
        health_status["status"] = "degraded"

    # Redis 체크
    try:
        await redis.client.ping()
        health_status["services"]["redis"] = {"status": "ok"}
    except Exception as e:
        health_status["services"]["redis"] = {"status": "error", "message": str(e)}
        health_status["status"] = "degraded"

    # Meilisearch 체크
    try:
        await meilisearch_handler.client.health()
        health_status["services"]["meilisearch"] = {"status": "ok"}
    except Exception as e:
        health_status["services"]["meilisearch"] = {"status": "error", "message": str(e)}
        health_status["status"] = "degraded"

    return health_status
