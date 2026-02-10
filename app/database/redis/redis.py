from redis import asyncio as aioredis
from app.utils.config import settings

class RedisHandler:
    def __init__(self):
        # 모듈 로드 시점의 설력을 일단 저장
        self.host = settings.redis_host
        self.port = settings.redis_port
        self.password = settings.redis_password
        self.db = settings.redis_database
        self._redis = None

    async def initialize(self):
        """Redis 클라이언트를 초기화합니다. FastAPI lifespan에서 호출 추천."""
        if self._redis is None:
            # 최신 설정을 다시 읽어옵니다. (load_dotenv 이후의 값 보장)
            host = settings.redis_host
            if host == "localhost":
                host = "127.0.0.1" # Windows 호환성
                
            self._redis = aioredis.Redis(
                host=host,
                port=settings.redis_port,
                password=settings.redis_password if settings.redis_password else None,
                db=settings.redis_database,
                decode_responses=True # 기본적으로 문자열로 디코딩
            )

    async def close(self):
        """Redis 클라이언트를 종료합니다. FastAPI lifespan에서 호출 추천."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def client(self) -> aioredis.Redis:
        """연결된 Redis 클라이언트를 반환합니다."""
        if self._redis is None:
            raise ConnectionError("Redis client is not initialized. Call initialize() first.")
        return self._redis

    # 편의를 위한 래퍼 메서드들
    async def get(self, key: str):
        return await self.client.get(key)

    async def set(self, key: str, value: str, ex: int = None):
        return await self.client.set(key, value, ex=ex)

    async def delete(self, key: str):
        return await self.client.delete(key)

    async def exists(self, key: str):
        return await self.client.exists(key)

redis = RedisHandler()

def get_redis_handler():
    return redis

__all__ = ["redis", "get_redis_handler"]