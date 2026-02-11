import secrets
import hmac
import hashlib
from app.database.redis.redis import redis
from app.utils.config import settings

# WebSocket 연결 토큰 설정
WS_TOKEN_PREFIX = "ws_token:"
WS_TOKEN_TTL = 60  # 60초 (1분)

# 오버레이 토큰 버전 (Redis 저장)
OVERLAY_TOKEN_VERSION_PREFIX = "overlay_token_version:"


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


async def get_overlay_token_version(user_id: int) -> int:
    """사용자의 오버레이 토큰 버전 조회"""
    key = f"{OVERLAY_TOKEN_VERSION_PREFIX}{user_id}"
    version = await redis.get(key)
    return int(version) if version else 0


async def increment_overlay_token_version(user_id: int) -> int:
    """사용자의 오버레이 토큰 버전 증가 (기존 토큰 무효화)"""
    key = f"{OVERLAY_TOKEN_VERSION_PREFIX}{user_id}"
    current = await get_overlay_token_version(user_id)
    new_version = current + 1
    await redis.set(key, str(new_version))
    return new_version


def generate_overlay_token(user_id: int, version: int = 0) -> str:
    """OBS 오버레이용 영구 토큰 생성 (HMAC 기반, 버전 포함)"""
    message = f"overlay:{user_id}:v{version}".encode()
    signature = hmac.new(
        settings.jwt_secret_key.encode(),
        message,
        hashlib.sha256
    ).hexdigest()[:32]
    return f"{user_id}_{version}_{signature}"


async def generate_overlay_token_async(user_id: int) -> str:
    """OBS 오버레이용 토큰 생성 (현재 버전 기반)"""
    version = await get_overlay_token_version(user_id)
    return generate_overlay_token(user_id, version)


def verify_overlay_token(token: str) -> int | None:
    """OBS 오버레이 토큰 검증 및 user_id 반환 (동기 버전 - 버전 체크 없음)"""
    if not token or "_" not in token:
        return None

    try:
        parts = token.split("_")
        if len(parts) == 2:
            # 구버전 토큰 (user_id_signature) - 하위 호환
            user_id_str, signature = parts
            user_id = int(user_id_str)
            expected_token = generate_overlay_token(user_id, 0)
            if hmac.compare_digest(token, expected_token):
                return user_id
        elif len(parts) == 3:
            # 신버전 토큰 (user_id_version_signature)
            user_id_str, version_str, signature = parts
            user_id = int(user_id_str)
            version = int(version_str)
            expected_token = generate_overlay_token(user_id, version)
            if hmac.compare_digest(token, expected_token):
                return user_id
    except (ValueError, TypeError):
        pass

    return None


async def verify_overlay_token_async(token: str) -> int | None:
    """OBS 오버레이 토큰 검증 및 user_id 반환 (비동기 버전 - 버전 체크 포함)"""
    if not token or "_" not in token:
        return None

    try:
        parts = token.split("_")
        if len(parts) == 2:
            # 구버전 토큰 - 버전 0만 허용
            user_id_str, signature = parts
            user_id = int(user_id_str)
            current_version = await get_overlay_token_version(user_id)
            if current_version > 0:
                return None  # 토큰이 재발급됨
            expected_token = generate_overlay_token(user_id, 0)
            if hmac.compare_digest(token, expected_token):
                return user_id
        elif len(parts) == 3:
            # 신버전 토큰
            user_id_str, version_str, signature = parts
            user_id = int(user_id_str)
            version = int(version_str)
            current_version = await get_overlay_token_version(user_id)
            if version != current_version:
                return None  # 버전 불일치 (토큰이 재발급됨)
            expected_token = generate_overlay_token(user_id, version)
            if hmac.compare_digest(token, expected_token):
                return user_id
    except (ValueError, TypeError):
        pass

    return None
