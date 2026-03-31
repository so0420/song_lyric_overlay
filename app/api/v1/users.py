from fastapi import APIRouter, Request, HTTPException, Depends
from app.database.mariadb import db_handler
from app.core.auth import get_current_user_api
from app.utils.mailer import send_email
from app.utils.otp import otp_manager
from app.utils.password import hash_password, verify_password, validate_password
from app.utils.config import config
from app.schemas.users import ProfileUpdateSchema, PasswordChangeSchema, EmailOtpSchema

router = APIRouter()

@router.post("/me/email-otp")
async def send_email_otp(
    data: EmailOtpSchema,
    user=Depends(get_current_user_api)
):
    email = data.email

    # Check if duplicate email exists
    exists = await db_handler.fetch_one(
        "SELECT id FROM users WHERE email = %s AND id != %s",
        (email, user['id'])
    )
    if exists:
        raise HTTPException(status_code=400, detail="이미 사용 중인 이메일 주소입니다.")

    # Generate OTP
    code = await otp_manager.create_otp(email)

    # Send Email
    subject = f"[{config.app_name}] 이메일 변경 인증 번호"
    html_content = f"""
    <div style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; max-width: 400px; margin: 0 auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #4A90E2; margin-bottom: 20px;">이메일 변경 인증</h2>
        <p>안녕하세요, <strong>{user['name']}</strong>님!</p>
        <p>이메일 주소를 변경하기 위한 인증 번호입니다.</p>
        <div style="background: #f8f9fa; padding: 15px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; color: #333; border-radius: 5px; margin: 20px 0;">
            {code}
        </div>
        <p style="font-size: 13px; color: #888;">인증 번호는 5분 동안 유효합니다.</p>
    </div>
    """

    success = send_email(to_email=email, subject=subject, html_content=html_content)
    if not success:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다.")

    return {"success": True}

@router.patch("/me")
async def update_my_profile(
    request: Request,
    data: ProfileUpdateSchema,
    user=Depends(get_current_user_api)
):
    # Check if email is being changed
    is_email_changed = data.email != user['email']

    if is_email_changed:
        if not data.otp_code:
            raise HTTPException(status_code=400, detail="이메일 변경을 위해서는 인증 코드가 필요합니다.")

        # Verify OTP
        verify_res = await otp_manager.verify_otp(data.email, data.otp_code)
        if not verify_res.success:
            raise HTTPException(status_code=400, detail=verify_res.message)

        # Check if duplicate email exists for another user (double check)
        exists = await db_handler.fetch_one(
            "SELECT id FROM users WHERE email = %s AND id != %s",
            (data.email, user['id'])
        )
        if exists:
            raise HTTPException(status_code=400, detail="이미 사용 중인 이메일 주소입니다.")

    # Update DB
    await db_handler.execute_query(
        "UPDATE users SET name = %s, email = %s WHERE id = %s",
        (data.name, data.email, user['id'])
    )

    # Update Session
    session_user = dict(request.session.get('user', {}))
    session_user['name'] = data.name
    session_user['email'] = data.email
    request.session['user'] = session_user

    return {"success": True, "name": data.name, "email": data.email}

@router.get("/me/social-accounts")
async def get_my_social_accounts(
    user=Depends(get_current_user_api)
):
    accounts = await db_handler.fetch_all(
        "SELECT provider, provider_user_id, created_at FROM social_accounts WHERE user_id = %s",
        (user['id'],)
    )
    return accounts

@router.delete("/me/social-accounts/{provider}")
async def unlink_social_account(
    provider: str,
    user=Depends(get_current_user_api)
):
    # Check if this is the last social account
    accounts = await db_handler.fetch_all(
        "SELECT id FROM social_accounts WHERE user_id = %s",
        (user['id'],)
    )

    if len(accounts) <= 1:
        # 마지막 소셜 계정이면, 비밀번호가 설정되어 있는지 확인
        db_user = await db_handler.fetch_one(
            "SELECT password_hash FROM users WHERE id = %s",
            (user['id'],)
        )
        if not db_user or not db_user.get('password_hash'):
            raise HTTPException(status_code=400, detail="이메일 로그인이 설정되어 있지 않아 마지막 소셜 계정은 해제할 수 없습니다.")

    # Delete link
    await db_handler.execute_query(
        "DELETE FROM social_accounts WHERE user_id = %s AND provider = %s",
        (user['id'], provider)
    )

    return {"success": True}


@router.get("/me/has-password")
async def check_has_password(user=Depends(get_current_user_api)):
    """비밀번호 설정 여부 확인"""
    db_user = await db_handler.fetch_one(
        "SELECT password_hash FROM users WHERE id = %s",
        (user['id'],)
    )
    has_password = bool(db_user and db_user.get('password_hash'))
    return {"has_password": has_password}


@router.patch("/me/password")
async def change_password(
    data: PasswordChangeSchema,
    user=Depends(get_current_user_api)
):
    """비밀번호 변경 또는 설정"""
    is_valid, error_msg = validate_password(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    db_user = await db_handler.fetch_one(
        "SELECT password_hash FROM users WHERE id = %s",
        (user['id'],)
    )

    # 기존 비밀번호가 있으면 현재 비밀번호 확인 필요
    if db_user and db_user.get('password_hash'):
        if not data.current_password:
            raise HTTPException(status_code=400, detail="현재 비밀번호를 입력해주세요.")
        if not verify_password(data.current_password, db_user['password_hash']):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")

    # 새 비밀번호 저장
    new_hash = hash_password(data.new_password)
    await db_handler.execute_query(
        "UPDATE users SET password_hash = %s, email_verified = 1 WHERE id = %s",
        (new_hash, user['id'])
    )

    return {"success": True, "message": "비밀번호가 변경되었습니다."}

@router.delete("/me")
async def withdraw_user(
    request: Request,
    user=Depends(get_current_user_api)
):
    # 소프트 삭제: deleted_at 설정 및 is_active 비활성화
    await db_handler.execute_query(
        "UPDATE users SET deleted_at = NOW(), is_active = 0 WHERE id = %s",
        (user['id'],)
    )

    # 세션 초기화
    request.session.clear()

    return {"success": True}
