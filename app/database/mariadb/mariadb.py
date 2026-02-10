import aiomysql
import asyncio
from contextlib import asynccontextmanager
from app.utils.config import settings

class MariaDBHandler:
    def __init__(self):
        # 모듈 로드 시점의 설정을 일단 저장
        self.host = settings.db_host
        self.port = settings.db_port
        self.user = settings.db_user
        self.password = settings.db_password
        self.db_name = settings.db_name
        self._pool = None

    async def initialize(self):
        """커넥션 풀을 초기화합니다. FastAPI lifespan에서 호출 추천."""
        if self._pool is None:
            # 최신 설정을 다시 읽어옵니다. (load_dotenv 이후의 값 보장)
            host = settings.db_host
            if host == "localhost":
                host = "127.0.0.1" # Windows에서 localhost는 가끔 문제를 일으키므로 127.0.0.1 추천
                
            port = settings.db_port
            user = settings.db_user
            password = settings.db_password
            db = settings.db_name
            
            self._pool = await aiomysql.create_pool(
                host=host,
                port=port,
                user=user,
                password=password if password else "",
                db=db,
                autocommit=False,
                charset='utf8mb4',
                cursorclass=aiomysql.DictCursor
            )

    async def close(self):
        """커넥션 풀을 종료합니다. FastAPI lifespan에서 호출 추천."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    @asynccontextmanager
    async def session(self):
        """커넥션을 빌려오고 자동으로 commit/close를 수행하는 컨텍스트 매니저"""
        if self._pool is None:
            await self.initialize()
            
        async with self._pool.acquire() as conn:
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def execute_query(self, query, params=None):
        async with self.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return cursor.lastrowid

    async def execute_many(self, query, params_list):
        if not params_list:
            return 0
        async with self.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.executemany(query, params_list)
                return cursor.rowcount

    async def fetch_one(self, query, params=None):
        async with self.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchone()

    async def fetch_all(self, query, params=None):
        async with self.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                return await cursor.fetchall()

db_handler = MariaDBHandler()

def get_mariadb_handler():
    return db_handler
