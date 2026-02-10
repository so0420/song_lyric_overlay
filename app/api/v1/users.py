from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.database.mariadb import db_handler
from app.core.auth import get_current_user_api
from app.utils.mailer import send_email
from app.utils.otp import otp_manager

router = APIRouter()

class ProfileUpdateSchema(BaseModel):
    name: str
    email: str
    otp_code: Optional[str] = None

@router.post("/me/email-otp")
async def send_email_otp(
    data: dict,
    user=Depends(get_current_user_api)
):
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="이메일 주소가 필요합니다.")

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
    subject = "[Jamku Song] 이메일 변경 인증 번호"
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
    user['name'] = data.name
    user['email'] = data.email
    request.session['user'] = user

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
        raise HTTPException(status_code=400, detail="최소 하나 이상의 소셜 계정이 연결되어 있어야 합니다.")

    # Delete link
    await db_handler.execute_query(
        "DELETE FROM social_accounts WHERE user_id = %s AND provider = %s",
        (user['id'], provider)
    )

    return {"success": True}

@router.delete("/me")
async def withdraw_user(
    request: Request,
    user=Depends(get_current_user_api)
):
    # DB에서 유저 삭제 (Cascading deletes)
    await db_handler.execute_query(
        "DELETE FROM users WHERE id = %s",
        (user['id'],)
    )

    # 세션 초기화
    request.session.clear()

    return {"success": True}
