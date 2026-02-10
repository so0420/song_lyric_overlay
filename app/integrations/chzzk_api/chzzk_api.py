import httpx
import asyncio
import time
import json
from typing import Optional, List, Dict, Any
from app.utils.config import settings
from app.utils.log import logger
from app.database.mariadb import db_handler

class ChzzkAPI:
    def __init__(self):
        self.api_key = settings.youtube_api_key
        self.base_url = "https://openapi.chzzk.naver.com"
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """클라이언트를 초기화합니다. FastAPI lifespan에서 호출 권장."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        """클라이언트를 종료합니다. FastAPI lifespan에서 호출 권장."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_tokens(self, client_id: str, client_secret: str, authorization_token: str, state: str) -> dict | None:
        """
        엑세스 토큰을 획득합니다.
        """
        url = 'https://chzzk.naver.com/auth/v1/token'

        send_data = {
            'grantType': 'authorization_code',
            'clientId': client_id,
            'clientSecret': client_secret,
            'code': authorization_token,
            'state': state
        }
        
        if self._client is None:
            await self.initialize()

        response = await self._client.post(url, json=send_data)
        try:
            response_json = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response as JSON: {e}")
            return None

        if response.status_code == 200:
            return {
                'access_token': response_json['content']['accessToken'],
                'refresh_token': response_json['content']['refreshToken'],
                'expires_at': int(response_json['content']['expiresIn'] + time.time())
            }
        else:
            logger.error(f'엑세스 토큰 발급 실패 {response.status_code}: {response_json}')
            return None

    async def refresh_access_token(self, client_id: str, client_secret: str, refresh_token: str) -> dict | None:
        """
        리프레시 토큰을 사용하여 엑세스 토큰을 갱신합니다.
        """
        url = 'https://chzzk.naver.com/auth/v1/token'

        send_data = {
            'grantType': 'refresh_token',
            'clientId': client_id,
            'clientSecret': client_secret,
            'refreshToken': refresh_token
        }

        if self._client is None:
            await self.initialize()

        response = await self._client.post(url, json=send_data)
        try:
            response_json = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response as JSON: {e}")
            return None

        if response.status_code == 200:
            return {
                'access_token': response_json['content']['accessToken'],
                'refresh_token': response_json['content']['refreshToken'],
                'expires_at': int(response_json['content']['expiresIn'] + time.time())
            }
        else:
            logger.error(f'토큰 갱신 실패 {response.status_code}: {response_json}')
            return None
    
    async def get_channel_info(self, access_token: str) -> dict | None:
        """
        유저의 정보를 획득합니다.
        """
        url = f'{self.base_url}/open/v1/users/me'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        if self._client is None:
            await self.initialize()

        response = await self._client.get(url, headers=headers)
        try:
            response_json = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response as JSON: {e}")
            return None

        if response.status_code == 200:
            return response_json['content'] if 'content' in response_json else response_json
        else:
            logger.error(f'채널 정보 조회 실패 {response.status_code}: {response_json}')
            return None

# 싱글톤 인스턴스 생성
chzzk_api = ChzzkAPI()
