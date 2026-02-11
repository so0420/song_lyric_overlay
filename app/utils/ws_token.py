import secrets
import hmac
import hashlib
from app.database.redis.redis import redis
from app.utils.config import settings

# WebSocket 연결 토큰 설정
WS_TOKEN_PREFIX = "ws_token:"
WS_TOKEN_TTL = 60  # 60초 (1분)


async def generate_ws_token(user_id: int) -> str:
    """WebSocket 연결용 일회용 토큰 생성 (로그인된 사용자용)"""
    token = secrets.token_urlsafe(32)
    key = f"{WS_TOKEN_PREFIX}{token}"
    await redis.set(key, str(user_id), ex=WS_TOKEN_TTL)
    return token


async def verify_ws_token(token: str) -> int | None:
    """WebSocket 토큰 검증 및 user_id 반환 (일회용 - 검증 후 삭제)"""
    if not token:
        return None

    key = f"{WS_TOKEN_PREFIX}{token}"
    user_id = await redis.get(key)

    if user_id:
        # 일회용이므로 즉시 삭제
        await redis.delete(key)
        return int(user_id)

    return None


def generate_overlay_token(user_id: int) -> str:
    """OBS 오버레이용 영구 토큰 생성 (HMAC 기반)"""
    message = f"overlay:{user_id}".encode()
    signature = hmac.new(
        settings.jwt_secret_key.encode(),
        message,
        hashlib.sha256
    ).hexdigest()[:32]
    return f"{user_id}_{signature}"


def verify_overlay_token(token: str) -> int | None:
    """OBS 오버레이 토큰 검증 및 user_id 반환"""
    if not token or "_" not in token:
        return None

    try:
        user_id_str, signature = token.split("_", 1)
        user_id = int(user_id_str)

        # 예상 토큰 생성 후 비교
        expected_token = generate_overlay_token(user_id)
        if hmac.compare_digest(token, expected_token):
            return user_id
    except (ValueError, TypeError):
        pass

    return None
