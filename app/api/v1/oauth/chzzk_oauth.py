import secrets
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse

from app.utils.config import settings
from app.core.auth import get_current_user
from app.database.chzzk_repository import get_chzzk_channel_repository, ChzzkChannelRepository

router = APIRouter()

# 세션에 저장하는 state 키
_SESSION_STATE_KEY = "chzzk_oauth_state"
_SESSION_REDIRECT_KEY = "chzzk_oauth_redirect"


def _require_chzzk_config():
    """치지직 연동 설정(.env)이 채워져 있는지 확인"""
    if not settings.chzzk_client_id or not settings.chzzk_interlock_redirect_uri:
        raise HTTPException(status_code=503, detail="치지직 연동이 설정되지 않았습니다.")


@router.get("/login")
async def login(
    request: Request,
    redirect_to: Optional[str] = None,
    user=Depends(get_current_user),
):
    """치지직 계정 연동 시작 — account-interlock 으로 리다이렉트 (로그인 필요)

    OAuth 처리는 jamkubot 이 대행하고, 인증 후 사용자를 우리 콜백(CHZZK_RETURN_URL)으로
    되돌려보낸다. CSRF 방지를 위해 state 를 세션에 저장한다.
    """
    if not user:
        return RedirectResponse(url="/login")
    _require_chzzk_config()

    # state = 접두사 + 랜덤 (jamkubot 이 접두사로 우리 서비스를 식별)
    state = f"{settings.chzzk_state_prefix}{secrets.token_urlsafe(24)}"
    request.session[_SESSION_STATE_KEY] = state
    request.session[_SESSION_REDIRECT_KEY] = redirect_to or "/songbook"

    url = (
        f"https://chzzk.naver.com/account-interlock"
        f"?clientId={settings.chzzk_client_id}"
        f"&redirectUri={settings.chzzk_interlock_redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)


@router.get("/callback", name="chzzk_auth_callback")
async def auth_callback(
    request: Request,
    state: str,
    uid: Optional[str] = None,
    streamerUid: Optional[str] = None,
    channelId: Optional[str] = None,
    channelName: Optional[str] = None,
    user=Depends(get_current_user),
    channel_repo: ChzzkChannelRepository = Depends(get_chzzk_channel_repository),
):
    """jamkubot 이 인증 후 사용자를 되돌려보내는 콜백 — 채널 uid 를 저장 (로그인 필요)

    파라미터: state(우리가 발급), uid(치지직 채널 uid). uid 는 jamkubot 측 명명에 따라
    streamerUid/channelId 로 올 수도 있어 함께 허용한다.
    """
    if not user:
        return RedirectResponse(url="/login")

    # CSRF: 세션에 보관한 state 와 일치해야 함
    expected = request.session.pop(_SESSION_STATE_KEY, None)
    redirect_to = request.session.pop(_SESSION_REDIRECT_KEY, "/songbook")
    if not expected or state != expected:
        raise HTTPException(status_code=400, detail="잘못된 state 값입니다. 다시 시도해주세요.")

    channel_id = uid or streamerUid or channelId
    if not channel_id:
        raise HTTPException(status_code=400, detail="치지직 채널 정보를 받지 못했습니다.")

    await channel_repo.link(user["id"], channel_id, channelName)
    return RedirectResponse(url=redirect_to)
