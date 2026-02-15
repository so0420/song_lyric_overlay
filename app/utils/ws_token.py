import secrets
from app.database.redis.redis import redis
from app.database.mariadb.mariadb import db_handler

# WebSocket 연결 토큰 설정 (Redis - 일회용)
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


# ============ 오버레이 토큰 (DB 기반 - 영구 저장) ============

async def generate_overlay_token(user_id: int) -> str:
    """OBS 오버레이용 영구 토큰 생성

    - 토큰에 user_id가 포함되지 않음 (보안 강화)
    - DB에 저장되어 영구 유지
    - 기존 토큰이 있으면 덮어씀 (재발급)
    """
    token = secrets.token_urlsafe(32)

    await db_handler.execute_query(
        "UPDATE users SET overlay_token = %s WHERE id = %s",
        (token, user_id)
    )

    return token


async def get_overlay_token(user_id: int) -> str | None:
    """사용자의 현재 오버레이 토큰 조회"""
    result = await db_handler.fetch_one(
        "SELECT overlay_token FROM users WHERE id = %s",
        (user_id,)
    )
    return result['overlay_token'] if result else None


async def get_or_create_overlay_token(user_id: int) -> str:
    """사용자의 오버레이 토큰 조회 또는 생성"""
    token = await get_overlay_token(user_id)
    if token:
        return token

    # 토큰이 없으면 새로 생성
    return await generate_overlay_token(user_id)


async def verify_overlay_token_async(token: str) -> int | None:
    """OBS 오버레이 토큰 검증 및 user_id 반환"""
    if not token:
        return None

    result = await db_handler.fetch_one(
        "SELECT id FROM users WHERE overlay_token = %s AND is_active = 1",
        (token,)
    )

    if result:
        return result['id']

    return None


async def revoke_overlay_token(user_id: int) -> bool:
    """사용자의 오버레이 토큰 무효화"""
    await db_handler.execute_query(
        "UPDATE users SET overlay_token = NULL WHERE id = %s",
        (user_id,)
    )
    return True
