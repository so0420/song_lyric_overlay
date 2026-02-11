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

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


class AppConfig(BaseModel):
    """
    config.json에서 로드되는 '정적' 설정(비밀값 말고).
    """
    app_name: str
    version: str
    app_url: str

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
