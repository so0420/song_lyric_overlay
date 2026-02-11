"""
인증 관련 API 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRegister:
    """회원가입 테스트"""

    @pytest.mark.asyncio
    async def test_register_success(self, async_client, mock_db, mock_otp_manager, mock_mailer):
        """회원가입 성공"""
        mock_db.fetch_one.return_value = None  # 중복 이메일 없음

        response = await async_client.post("/api/v1/auth/register", json={
            "email": "newuser@example.com",
            "password": "password123",
            "name": "새사용자"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "인증 코드" in data["message"]

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, async_client, mock_db):
        """중복 이메일로 회원가입 시도"""
        mock_db.fetch_one.return_value = {
            "id": 1,
            "email_verified": True
        }

        response = await async_client.post("/api/v1/auth/register", json={
            "email": "existing@example.com",
            "password": "password123",
            "name": "사용자"
        })

        assert response.status_code == 400
        assert "이미 가입된" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_short_password(self, async_client):
        """짧은 비밀번호로 회원가입 시도"""
        response = await async_client.post("/api/v1/auth/register", json={
            "email": "test@example.com",
            "password": "short",
            "name": "사용자"
        })

        assert response.status_code == 400
        assert "8자" in response.json()["detail"]


class TestVerifyEmail:
    """이메일 인증 테스트"""

    @pytest.mark.asyncio
    async def test_verify_email_success(self, async_client, mock_db, mock_otp_manager):
        """이메일 인증 성공"""
        mock_otp_manager.verify_otp.return_value = MagicMock(success=True, message="OK")
        mock_db.fetch_one.return_value = {"id": 1}

        response = await async_client.post("/api/v1/auth/verify-email", json={
            "email": "test@example.com",
            "code": "123456"
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_verify_email_invalid_code(self, async_client, mock_otp_manager):
        """잘못된 인증 코드"""
        mock_otp_manager.verify_otp.return_value = MagicMock(
            success=False,
            message="인증 코드가 올바르지 않습니다."
        )

        response = await async_client.post("/api/v1/auth/verify-email", json={
            "email": "test@example.com",
            "code": "000000"
        })

        assert response.status_code == 400


class TestLogin:
    """로그인 테스트"""

    @pytest.mark.asyncio
    async def test_login_success(self, async_client, mock_db):
        """로그인 성공"""
        from app.utils.password import hash_password
        password_hash = hash_password("password123")

        mock_db.fetch_one.return_value = {
            "id": 1,
            "email": "test@example.com",
            "name": "테스트유저",
            "password_hash": password_hash,
            "email_verified": True,
            "is_admin": False
        }

        response = await async_client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "password123"
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, async_client, mock_db):
        """잘못된 비밀번호"""
        from app.utils.password import hash_password

        mock_db.fetch_one.return_value = {
            "id": 1,
            "email": "test@example.com",
            "password_hash": hash_password("correctpassword"),
            "email_verified": True
        }

        response = await async_client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "wrongpassword"
        })

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unverified_email(self, async_client, mock_db):
        """미인증 이메일로 로그인"""
        from app.utils.password import hash_password

        mock_db.fetch_one.return_value = {
            "id": 1,
            "email": "test@example.com",
            "password_hash": hash_password("password123"),
            "email_verified": False
        }

        response = await async_client.post("/api/v1/auth/login", json={
            "email": "test@example.com",
            "password": "password123"
        })

        assert response.status_code == 403
        assert "이메일 인증" in response.json()["detail"]


class TestForgotPassword:
    """비밀번호 재설정 테스트"""

    @pytest.mark.asyncio
    async def test_forgot_password_success(self, async_client, mock_db, mock_otp_manager, mock_mailer):
        """비밀번호 재설정 요청 성공"""
        mock_db.fetch_one.return_value = {
            "id": 1,
            "name": "테스트유저",
            "password_hash": "somehash"
        }

        response = await async_client.post("/api/v1/auth/forgot-password", json={
            "email": "test@example.com"
        })

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_email(self, async_client, mock_db):
        """존재하지 않는 이메일"""
        mock_db.fetch_one.return_value = None

        response = await async_client.post("/api/v1/auth/forgot-password", json={
            "email": "nonexistent@example.com"
        })

        # 보안상 이유로 성공 응답 반환
        assert response.status_code == 200
        assert response.json()["success"] is True
