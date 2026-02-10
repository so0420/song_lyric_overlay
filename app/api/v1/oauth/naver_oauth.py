from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuthError
from app.utils.oauth import oauth
from app.database.mariadb import get_mariadb_handler, MariaDBHandler
from app.utils.config import settings
from app.core.auth import get_current_user

router = APIRouter()

@router.get("/login")
async def login(request: Request):
    redirect_uri = settings.naver_redirect_uri
    if not redirect_uri:
        redirect_uri = request.url_for('naver_auth_callback')

    return await oauth.naver.authorize_redirect(request, str(redirect_uri))

@router.get("/callback", name="naver_auth_callback")
async def naver_auth_callback(
    request: Request,
    db: MariaDBHandler = Depends(get_mariadb_handler)
):
    try:
        token = await oauth.naver.authorize_access_token(request)
    except OAuthError as error:
        return JSONResponse(status_code=400, content={"error": error.error})

    resp = await oauth.naver.get('nid/me', token=token)
    profile = resp.json().get('response')

    if not profile:
        return JSONResponse(status_code=400, content={"error": "Failed to get user info from Naver"})

    provider = 'naver'
    provider_user_id = profile.get('id')
    name = profile.get('nickname')
    email = profile.get('email')
    picture = profile.get('profile_image')

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

        # 소셜 계정 정보 갱신
        await db.execute_query(
            "UPDATE social_accounts SET provider_email = %s, provider_name = %s, provider_picture = %s WHERE provider = %s AND provider_user_id = %s",
            (email, name, picture, provider, provider_user_id)
        )

        if current_user and user['id'] != current_user['id']:
            return RedirectResponse(url='/login?error=account_already_linked')

    else:
        # 2. 이메일로 중복 가입 확인
        user = await db.fetch_one("SELECT * FROM users WHERE email = %s", (email,))

        existing_social = await db.fetch_one(
            "SELECT user_id FROM social_accounts WHERE provider_email = %s",
            (email,)
        )

        if user or existing_social:
            target_user_id = user['id'] if user else existing_social['user_id']
            if not current_user:
                return RedirectResponse(url='/login?error=email_exists')

            if target_user_id != current_user['id']:
                 return RedirectResponse(url='/login?error=email_mismatch')

            user = current_user
        else:
            # 3. 신규 유저 생성
            if current_user:
                user = current_user
            else:
                user_id = await db.execute_query(
                    "INSERT INTO users (email, name, ip) VALUES (%s, %s, %s)",
                    (email, name, client_ip)
                )
                user = {"id": user_id, "email": email, "name": name}

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

    # 세션에 정보 저장
    request.session['user'] = {
        "id": user['id'],
        "email": user['email'],
        "name": user['name'],
        "is_admin": bool(user.get('is_admin', 0))
    }

    return RedirectResponse(url='/')
