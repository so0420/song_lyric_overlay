from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuthError
from app.utils.oauth import oauth
from app.database.mariadb import get_mariadb_handler, MariaDBHandler
from app.database.cloudflare.r2 import get_r2_handler, R2Handler
from app.utils.config import settings
from app.core.auth import get_current_user
from app.utils.profile import save_profile_image_from_url

router = APIRouter()

@router.get("/login")
async def login(request: Request):
    # Google 로그인 페이지로 리다이렉트
    redirect_uri = settings.google_redirect_uri
    if not redirect_uri:
        redirect_uri = request.url_for('auth_callback')
    
    return await oauth.google.authorize_redirect(request, str(redirect_uri))

@router.get("/callback", name="auth_callback")
async def auth_callback(
    request: Request, 
    db: MariaDBHandler = Depends(get_mariadb_handler),
    r2: R2Handler = Depends(get_r2_handler)
):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as error:
        return JSONResponse(status_code=400, content={"error": error.error})
    
    user_info = token.get('userinfo')
    if not user_info:
        return JSONResponse(status_code=400, content={"error": "Failed to get user info from Google"})

    provider = 'google'
    provider_user_id = user_info.get('sub')
    email = user_info.get('email')
    name = user_info.get('name')
    picture = user_info.get('picture')

    client_ip = request.client.host

    # 1. 기존 소셜 계정 확인
    social_account = await db.fetch_one(
        "SELECT user_id FROM social_accounts WHERE provider = %s AND provider_user_id = %s",
        (provider, provider_user_id)
    )

    current_user = get_current_user(request)

    if social_account:
        # 이미 가입된 계정이면 해당 유저 정보 가져오기
        user = await db.fetch_one("SELECT * FROM users WHERE id = %s", (social_account['user_id'],))
        
        # 소셜 계정 정보 갱신 (항상 최신 정보로 유지)
        await db.execute_query(
            "UPDATE social_accounts SET provider_email = %s, provider_name = %s, provider_picture = %s WHERE provider = %s AND provider_user_id = %s",
            (email, name, picture, provider, provider_user_id)
        )
        
        # 만약 로그인 중인데 다른 사람의 소셜 계정을 연결하려 하는 경우
        if current_user and user['id'] != current_user['id']:
            return RedirectResponse(url='/login?error=account_already_linked')
            
    else:
        # 2. 이메일로 중복 가입 확인 (users 테이블 및 social_accounts 테이블 양쪽 확인)
        user = await db.fetch_one("SELECT * FROM users WHERE email = %s", (email,))
        
        # 다른 소셜 계정에서 이미 해당 이메일을 사용 중인지 확인
        existing_social = await db.fetch_one(
            "SELECT user_id FROM social_accounts WHERE provider_email = %s",
            (email,)
        )
        
        if user or existing_social:
            target_user_id = user['id'] if user else existing_social['user_id']
            # 자동으로 연결하지 않고 안내
            if not current_user:
                return RedirectResponse(url='/login?error=email_exists')
            
            # 로그인 중인 경우 계정 연결 시도 시, 이메일이 다르면 거절
            if target_user_id != current_user['id']:
                 return RedirectResponse(url='/login?error=email_mismatch')
                 
            user = current_user
        else:
            # 3. 신규 유저 생성 (로그인 안된 상태여야 함)
            if current_user:
                 # 로그인 되어있는 현재 유저에게 이 SNS를 연결
                user = current_user
            else:
                # 첫 계정 생성 시 프로필 이미지를 R2에 저장
                r2_picture = await save_profile_image_from_url(picture, r2)
                
                user_id = await db.execute_query(
                    "INSERT INTO users (email, name, picture, ip) VALUES (%s, %s, %s, %s)",
                    (email, name, r2_picture, client_ip)
                )
                user = {"id": user_id, "email": email, "name": name, "picture": r2_picture}
        
        # 4. 소셜 계정 연결
        await db.execute_query(
            "INSERT INTO social_accounts (user_id, provider, provider_user_id, provider_email, provider_name, provider_picture) VALUES (%s, %s, %s, %s, %s, %s)",
            (user['id'], provider, provider_user_id, email, name, picture)
        )

    # 마지막 로그인 시간 및 IP 업데이트
    await db.execute_query(
        "UPDATE users SET last_login = NOW(), ip = %s WHERE id = %s",
        (client_ip, user['id'])
    )

    # 세션에 최소 정보 저장
    request.session['user'] = {
        "id": user['id'],
        "email": user['email'],
        "name": user['name'],
        "picture": user['picture'],
        "is_admin": bool(user.get('is_admin', 0))
    }
    
    return RedirectResponse(url='/')
