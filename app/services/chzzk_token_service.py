import time
import asyncio
from app.database.mariadb import MariaDBHandler
from app.integrations.chzzk_api.chzzk_api import chzzk_api
from app.utils.log import logger
from app.utils.config import settings

class ChzzkTokenService:
    def __init__(self, db: MariaDBHandler):
        self.db = db

    async def refresh_all_expired_tokens(self, buffer_seconds: int = None):
        """
        만료되었거나 만료가 임박한 모든 토큰을 갱신합니다.
        기본적으로 만료 1시간 전인 토큰들을 찾습니다.
        """
        if buffer_seconds is None:
            buffer_seconds = settings.chzzk_refresh_buffer
        now = int(time.time())
        expiry_threshold = now + buffer_seconds

        # 갱신이 필요한 토큰 목록 조회 (앱 정보와 조인)
        sql = """
        SELECT 
            t.id, t.user_id, t.app_id, t.refresh_token,
            a.client_id, a.client_secret
        FROM user_chzzk_tokens t
        JOIN chzzk_app_config a ON t.app_id = a.app_id COLLATE utf8mb4_unicode_ci
        WHERE t.expires_at <= %s
        """
        expired_tokens = await self.db.fetch_all(sql, (expiry_threshold,))

        if not expired_tokens:
            logger.info("No Chzzk tokens need refreshing at this time.")
            return

        logger.info(f"Found {len(expired_tokens)} Chzzk tokens to refresh.")

        for token_info in expired_tokens:
            try:
                logger.info(f"Refreshing token for user {token_info['user_id']} and app {token_info['app_id']}")
                
                # 토큰 요청
                new_tokens = await chzzk_api.refresh_access_token(
                    client_id=token_info['client_id'],
                    client_secret=token_info['client_secret'],
                    refresh_token=token_info['refresh_token']
                )

                if new_tokens:
                    # 토큰을 받았으면, 프로그램 종료 신호(Cancel)가 오더라도 DB 저장은 보장하도록 shield 사용
                    async def update_db():
                        update_sql = """
                        UPDATE user_chzzk_tokens
                        SET access_token = %s, refresh_token = %s, expires_at = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """
                        await self.db.execute_query(update_sql, (
                            new_tokens['access_token'],
                            new_tokens['refresh_token'],
                            new_tokens['expires_at'],
                            token_info['id']
                        ))
                        logger.info(f"Successfully refreshed and saved token for user {token_info['user_id']}")

                    try:
                        await asyncio.shield(update_db())
                    except asyncio.CancelledError:
                        # 이미 shield 내부의 update_db가 시작되었으므로, 
                        # CancelledError가 발생하더라도 배경에서 작업은 완료됩니다.
                        logger.warning(f"Token refresh for user {token_info['user_id']} was cancelled during DB save, but save persists.")
                        raise # 상위 루프에 취소 신호 전달
                else:
                    logger.error(f"Failed to refresh token for user {token_info['user_id']}. Token might be revoked.")
            except asyncio.CancelledError:
                # 전체 루프가 취소된 경우
                raise
            except Exception as e:
                logger.error(f"Error during Chzzk token refresh for user {token_info['user_id']}: {e}")

    async def get_valid_token(self, user_id: int, app_id: str) -> str | None:
        """
        특정 유저와 앱의 유효한 엑세스 토큰을 반환합니다.
        필요한 경우 즉시 갱신합니다.
        """
        sql = """
        SELECT 
            t.*, a.client_id, a.client_secret
        FROM user_chzzk_tokens t
        JOIN chzzk_app_config a ON t.app_id = a.app_id COLLATE utf8mb4_unicode_ci
        WHERE t.user_id = %s AND t.app_id = %s
        """
        token_info = await self.db.fetch_one(sql, (user_id, app_id))

        if not token_info:
            return None

        now = int(time.time())
        # 만료 5분 전이면 갱신
        if token_info['expires_at'] <= now + 300:
            new_tokens = await chzzk_api.refresh_access_token(
                client_id=token_info['client_id'],
                client_secret=token_info['client_secret'],
                refresh_token=token_info['refresh_token']
            )
            if new_tokens:
                async def update_db():
                    update_sql = """
                    UPDATE user_chzzk_tokens
                    SET access_token = %s, refresh_token = %s, expires_at = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """
                    await self.db.execute_query(update_sql, (
                        new_tokens['access_token'],
                        new_tokens['refresh_token'],
                        new_tokens['expires_at'],
                        token_info['id']
                    ))
                
                try:
                    await asyncio.shield(update_db())
                except asyncio.CancelledError:
                    logger.warning(f"On-demand token refresh for user {user_id} was cancelled during DB save, but save persists.")
                    # 취소되었어도 토큰은 이미 발급되었으므로 반환할 수도 있으나, 
                    # 호출부가 취소되었으므로 raise 하는 것이 정석입니다.
                    raise
                
                return new_tokens['access_token']
            else:
                logger.error(f"Failed to refresh token for user {user_id} during on-demand request.")
                return None
        
        return token_info['access_token']

    async def start_background_refresh(self, interval_seconds: int = None):
        if interval_seconds is None:
            interval_seconds = settings.chzzk_refresh_interval
        """치지직 토큰을 주기적으로 갱신하는 백그라운드 태스크"""
        logger.info("Chzzk token refresh background task starting...")
        while True:
            try:
                # 매 주기마다 만료 1시간 전인 토큰들을 자동 갱신
                await self.refresh_all_expired_tokens()
            except asyncio.CancelledError:
                logger.info("Chzzk token refresh background task stopping...")
                raise
            except Exception as e:
                logger.error(f"Error in Chzzk token refresh background task: {e}")
                
            await asyncio.sleep(interval_seconds)
