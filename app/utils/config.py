from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """
    .env 파일의 환경 변수를 읽어들여서 설정합니다.
    """
    # Dev
    environment: str

    # Server
    server_host: str
    server_port: int

    # Google Oauth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    # Naver Oauth
    naver_client_id: str
    naver_client_secret: str
    naver_redirect_uri: str
    naver_withdraw_url: str

    # YouTube API
    youtube_api_key: str

    # Log
    log_file_path: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_access_token_ttl: int
    jwt_refresh_token_ttl: int

    # DB
    db_type: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    # Redis
    redis_host: str
    redis_port: int
    redis_password: str
    redis_database: int

    # OTP
    otp_ttl: int
    otp_max_attempts: int

    # Email
    email_sender: str
    email_smtp_address: str
    google_app_key: str

    # Meilisearch
    meilisearch_host: str
    meilisearch_api_key: str
    meilisearch_index_name: str

    # Chzzk 연동 (OAuth 는 jamkubot 에 위임) — 미설정 시 연동 기능 비활성화
    chzzk_client_id: str = ""                 # account-interlock clientId
    chzzk_interlock_redirect_uri: str = ""    # account-interlock redirectUri (jamkubot)
    chzzk_state_prefix: str = "jamkusong_"    # state 접두사
    chzzk_return_url: str = ""                # jamkubot 이 사용자를 되돌려보낼 우리 콜백

    # Chzzk 채팅 릴레이 (jamkubot)
    chzzk_relay_url: str = "https://relay.jamkubot.com"
    chzzk_relay_token: str = ""               # 비어있으면 릴레이 연결 안 함

    # 오버레이 사용 요청 알림용 디스코드 웹훅 — 비어있으면 알림을 보내지 않는다
    discord_webhook_url: str = ""

    # 업로드 음원 저장 루트 — 비어있으면 <리포지토리 루트>/storage/audio
    audio_storage_root: str = ""

    # 업로드 프로필 사진 저장 루트 — 비어있으면 <리포지토리 루트>/storage/profile
    profile_image_root: str = ""

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore"
    }


class CacheOptions(BaseModel):
    """캐시 관련 설정"""
    # YouTube 캐시
    youtube_ttl: int = 300
    youtube_max_size: int = 100
    # iTunes 캐시
    itunes_ttl: int = 300
    itunes_max_size: int = 100


class AppConfig(BaseModel):
    """
    config.json에서 로드되는 '정적' 설정(비밀값 말고).
    """
    app_name: str
    version: str
    app_url: str
    cache_options: CacheOptions = CacheOptions()

    model_config = ConfigDict(extra="ignore")


def reload():
    """
    config.json / .env 를 다시 읽어 전역 객체를 갱신한다
    """
    global config, settings

    with open("config.json", encoding="utf-8") as f:
        config = AppConfig.model_validate_json(f.read())

    settings = Settings()

with open("config.json", encoding="utf-8") as f:
    config: AppConfig = AppConfig.model_validate_json(f.read())
settings: Settings = Settings()

__all__ = ['config', 'settings', 'reload']
