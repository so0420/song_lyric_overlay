"""
Pytest 설정 및 공통 fixtures
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture(scope="session")
def event_loop():
    """이벤트 루프 fixture (세션 스코프)"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client():
    """동기 테스트 클라이언트"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def async_client():
    """비동기 테스트 클라이언트"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_db():
    """DB 핸들러 모킹"""
    with patch("app.database.mariadb.db_handler") as mock:
        mock.fetch_one = AsyncMock(return_value=None)
        mock.fetch_all = AsyncMock(return_value=[])
        mock.execute_query = AsyncMock(return_value=1)
        yield mock


@pytest.fixture
def mock_redis():
    """Redis 핸들러 모킹"""
    with patch("app.database.redis.redis") as mock:
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=True)
        mock.exists = AsyncMock(return_value=False)
        yield mock


@pytest.fixture
def mock_session():
    """세션 모킹 (로그인된 사용자)"""
    return {
        "user": {
            "id": 1,
            "email": "test@example.com",
            "name": "테스트유저",
            "is_admin": False
        }
    }


@pytest.fixture
def mock_admin_session():
    """관리자 세션 모킹"""
    return {
        "user": {
            "id": 1,
            "email": "admin@example.com",
            "name": "관리자",
            "is_admin": True
        }
    }


@pytest.fixture
def mock_otp_manager():
    """OTP 매니저 모킹"""
    with patch("app.utils.otp.otp_manager") as mock:
        mock.create_otp = AsyncMock(return_value="123456")
        mock.verify_otp = AsyncMock(return_value=MagicMock(success=True, message="OK"))
        yield mock


@pytest.fixture
def mock_mailer():
    """이메일 발송 모킹"""
    with patch("app.utils.mailer.send_email") as mock:
        mock.return_value = True
        yield mock
