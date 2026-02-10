import secrets

def generate_user_token() -> str:
    """
    유저별 고유한 WebSocket 접속용 보안 토큰을 생성합니다.
    """
    # 32바이트 보안 랜덤 문자열 생성 (URL-safe)
    return secrets.token_urlsafe(32)
