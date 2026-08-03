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
    redirect_uri = settings.google_redirect_uri
    if not redirect_uri:
        redirect_uri = request.url_for('auth_callback')

    # 로그인 후 돌아갈 페이지 저장
    next_url = request.query_params.get('next')
    if next_url:
        request.session['oauth_redirect'] = next_url

    return await oauth.google.authorize_redirect(request, str(redirect_uri))

@router.get("/callback", name="auth_callback")
async def auth_callback(
    request: Request,
    db: MariaDBHandler = Depends(get_mariadb_handler)
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
        user = await db.fetch_one("SELECT * FROM users WHERE id = %s AND deleted_at IS NULL", (social_account['user_id'],))

        # 탈퇴한 계정의 소셜 연결이 아직 남아 있는 경우 (파기 전 30일)
        # 여기서 걸러내지 않으면 아래에서 user 가 None 이라 500 이 난다.
        if not user:
            return RedirectResponse(url='/login?error=account_withdrawn')

        # 소셜 계정 정보 갱신 (항상 최신 정보로 유지)
        await db.execute_query(
            "UPDATE social_accounts SET provider_email = %s, provider_name = %s, provider_picture = %s WHERE provider = %s AND provider_user_id = %s",
            (email, name, picture, provider, provider_user_id)
        )

        # 만약 로그인 중인데 다른 사람의 소셜 계정을 연결하려 하는 경우
        if current_user and user['id'] != current_user['id']:
            return RedirectResponse(url='/login?error=account_already_linked')

    else:
        # 2. 이메일로 중복 가입 확인
        user = await db.fetch_one("SELECT * FROM users WHERE email = %s AND deleted_at IS NULL", (email,))

        # 다른 소셜 계정에서 이미 해당 이메일을 사용 중인지 확인
        existing_social = await db.fetch_one(
            "SELECT user_id FROM social_accounts WHERE provider_email = %s",
            (email,)
        )

        # 같은 이메일의 탈퇴 계정이 아직 파기 전이면 위 조회에 잡히지 않는다.
        # 그대로 두면 아래에서 신규 가입으로 흘러 users.email UNIQUE 에 걸려 500 이 난다.
        # (로그인한 채로 소셜을 연결하는 경우는 새 행을 만들지 않으므로 해당 없다)
        if not user and not existing_social and not current_user:
            withdrawn = await db.fetch_one(
                "SELECT id FROM users WHERE email = %s AND deleted_at IS NOT NULL",
                (email,)
            )
            if withdrawn:
                return RedirectResponse(url='/login?error=account_withdrawn')

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

    # 세션에 최소 정보 저장
    request.session['user'] = {
        "id": user['id'],
        "email": user['email'],
        "name": user['name'],
        "is_admin": bool(user.get('is_admin', 0))
    }

    # 저장된 리다이렉트 URL로 이동 (없으면 홈)
    redirect_url = request.session.pop('oauth_redirect', '/')
    return RedirectResponse(url=redirect_url)
