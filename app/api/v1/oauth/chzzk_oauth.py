import secrets
import json
import base64
import time
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from app.database.mariadb import get_mariadb_handler, MariaDBHandler
from app.utils.config import settings
from app.core.auth import get_current_user
from app.integrations.chzzk_api.chzzk_api import chzzk_api
from typing import Optional

router = APIRouter()

@router.get("/login")
async def login(
    request: Request, 
    app_id: Optional[str] = None, 
    redirect_to: Optional[str] = None,
    user=Depends(get_current_user), 
    db: MariaDBHandler = Depends(get_mariadb_handler)
):
    # Chzzk 로그인 페이지로 리다이렉트
    app_id = app_id if app_id is not None else settings.chzzk_default_app_id

    app_info = await db.fetch_one("SELECT client_id, redirect_uri FROM chzzk_app_config WHERE app_id = %s", (app_id,))

    if app_info is None:
        raise HTTPException(status_code=404, detail="Chzzk app not found")
    
    # State에 app_id와 redirect_to를 포함하여 인코딩
    state_data = {
        "csrf": secrets.token_urlsafe(32),
        "app_id": app_id,
        "redirect_to": redirect_to
    }
    state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    url = (
        f"https://chzzk.naver.com/account-interlock"
        f"?clientId={app_info['client_id']}"
        f"&redirectUri={app_info['redirect_uri']}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)

@router.get("/callback", name="auth_callback")
async def auth_callback(
    request: Request, 
    code: str, 
    state: str, 
    user=Depends(get_current_user), 
    db: MariaDBHandler = Depends(get_mariadb_handler)
):
    try:
        # State 디코딩하여 app_id와 redirect_to 추출
        state_data = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        app_id = state_data.get("app_id")
        redirect_to = state_data.get("redirect_to")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state")

    if not app_id:
        raise HTTPException(status_code=400, detail="app_id missing in state")

    # 앱 정보 조회
    app_info = await db.fetch_one("SELECT client_id, client_secret FROM chzzk_app_config WHERE app_id = %s", (app_id,))
    if not app_info:
        raise HTTPException(status_code=404, detail="Chzzk app not found")

    # 토큰 획득
    token_data = await chzzk_api.get_tokens(
        client_id=app_info['client_id'],
        client_secret=app_info['client_secret'],
        authorization_token=code,
        state=state
    )

    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to get tokens from Chzzk")

    # 채널 정보 획득
    channel_info = await chzzk_api.get_channel_info(token_data['access_token'])
    if not channel_info:
        raise HTTPException(status_code=400, detail="Failed to get channel info from Chzzk")

    channel_id = channel_info.get('channelId')
    channel_name = channel_info.get('channelName')

    # DB에 토큰 저장 또는 업데이트
    sql = """
    INSERT INTO user_chzzk_tokens (user_id, app_id, channel_id, channel_name, access_token, refresh_token, expires_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        channel_id = VALUES(channel_id),
        channel_name = VALUES(channel_name),
        access_token = VALUES(access_token),
        refresh_token = VALUES(refresh_token),
        expires_at = VALUES(expires_at)
    """
    await db.execute_query(sql, (
        user['id'], 
        app_id, 
        channel_id, 
        channel_name, 
        token_data['access_token'], 
        token_data['refresh_token'], 
        token_data['expires_at']
    ))

    # 지정된 경로가 있으면 거기로 리다이렉트, 없으면 마이페이지로
    final_url = redirect_to if redirect_to else "/mypage"
    return RedirectResponse(url=final_url)
