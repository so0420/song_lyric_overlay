from authlib.integrations.starlette_client import OAuth
from app.utils.config import settings

oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

oauth.register(
    name='naver',
    client_id=settings.naver_client_id,
    client_secret=settings.naver_client_secret,
    access_token_url='https://nid.naver.com/oauth2.0/token',
    authorize_url='https://nid.naver.com/oauth2.0/authorize',
    api_base_url='https://openapi.naver.com/v1/',
    client_kwargs=None
)
