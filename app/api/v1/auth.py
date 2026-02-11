from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from app.database.mariadb import db_handler
from app.utils.mailer import send_email
from app.utils.otp import otp_manager
from app.utils.config import config
import bcrypt

router = APIRouter()


class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    name: str


class VerifyEmailSchema(BaseModel):
    email: EmailStr
    code: str


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class ResendVerificationSchema(BaseModel):
    email: EmailStr


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class ResetPasswordSchema(BaseModel):
    email: EmailStr
    code: str
    new_password: str


def hash_password(password: str) -> str:
    """비밀번호를 bcrypt로 해시"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """비밀번호 검증"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


@router.post("/register")
async def register(data: RegisterSchema):
    """회원가입 - 이메일 인증 코드 발송"""

    # 비밀번호 길이 검증
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    # 이메일 중복 확인
    existing_user = await db_handler.fetch_one(
        "SELECT id, email_verified FROM users WHERE email = %s",
        (data.email,)
    )

    if existing_user:
        if existing_user.get('email_verified'):
            raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
        else:
            # 미인증 상태면 기존 정보 업데이트
            password_hash = hash_password(data.password)
            await db_handler.execute_query(
                "UPDATE users SET password_hash = %s, name = %s WHERE id = %s",
                (password_hash, data.name, existing_user['id'])
            )
    else:
        # 신규 유저 생성 (미인증 상태)
        password_hash = hash_password(data.password)
        await db_handler.execute_query(
            "INSERT INTO users (email, password_hash, name, email_verified) VALUES (%s, %s, %s, 0)",
            (data.email, password_hash, data.name)
        )

    # OTP 생성 및 이메일 발송
    code = await otp_manager.create_otp(f"register:{data.email}")

    html_content = f"""
    <div style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #2563eb; margin: 0; font-size: 24px;">이메일 인증</h1>
        </div>
        <p style="color: #374151; font-size: 16px; margin-bottom: 24px;">
            안녕하세요, <strong>{data.name}</strong>님!<br>
            아래 인증 코드를 입력하여 회원가입을 완료해주세요.
        </p>
        <div style="background: #f3f4f6; padding: 24px; text-align: center; border-radius: 12px; margin: 24px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1f2937;">{code}</span>
        </div>
        <p style="color: #6b7280; font-size: 14px; text-align: center;">
            이 인증 코드는 5분 동안 유효합니다.
        </p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            본 메일은 {config.app_name} 회원가입 요청에 의해 발송되었습니다.<br>
            요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
        </p>
    </div>
    """

    success = send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 이메일 인증 코드",
        html_content=html_content,
        text_content=f"인증 코드: {code} (5분 동안 유효)"
    )

    if not success:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.")

    return {"success": True, "message": "인증 코드가 이메일로 발송되었습니다."}


@router.post("/verify-email")
async def verify_email(data: VerifyEmailSchema):
    """이메일 인증 확인"""

    # OTP 검증
    result = await otp_manager.verify_otp(f"register:{data.email}", data.code)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    # 유저 이메일 인증 완료 처리
    user = await db_handler.fetch_one(
        "SELECT id FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    await db_handler.execute_query(
        "UPDATE users SET email_verified = 1 WHERE id = %s",
        (user['id'],)
    )

    return {"success": True, "message": "이메일 인증이 완료되었습니다. 로그인해주세요."}


@router.post("/resend-verification")
async def resend_verification(data: ResendVerificationSchema):
    """인증 코드 재발송"""

    user = await db_handler.fetch_one(
        "SELECT id, name, email_verified FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    if user.get('email_verified'):
        raise HTTPException(status_code=400, detail="이미 인증된 계정입니다.")

    # OTP 생성 및 이메일 발송
    code = await otp_manager.create_otp(f"register:{data.email}")

    html_content = f"""
    <div style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #2563eb; margin: 0; font-size: 24px;">이메일 인증</h1>
        </div>
        <p style="color: #374151; font-size: 16px; margin-bottom: 24px;">
            안녕하세요, <strong>{user['name']}</strong>님!<br>
            아래 인증 코드를 입력하여 회원가입을 완료해주세요.
        </p>
        <div style="background: #f3f4f6; padding: 24px; text-align: center; border-radius: 12px; margin: 24px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1f2937;">{code}</span>
        </div>
        <p style="color: #6b7280; font-size: 14px; text-align: center;">
            이 인증 코드는 5분 동안 유효합니다.
        </p>
    </div>
    """

    success = send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 이메일 인증 코드",
        html_content=html_content,
        text_content=f"인증 코드: {code} (5분 동안 유효)"
    )

    if not success:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다.")

    return {"success": True, "message": "인증 코드가 재발송되었습니다."}


@router.post("/login")
async def login(request: Request, data: LoginSchema):
    """이메일 + 비밀번호 로그인"""

    user = await db_handler.fetch_one(
        "SELECT * FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    # 비밀번호 확인
    if not user.get('password_hash'):
        raise HTTPException(status_code=401, detail="소셜 로그인으로 가입된 계정입니다. 소셜 로그인을 이용해주세요.")

    if not verify_password(data.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    # 이메일 인증 확인
    if not user.get('email_verified'):
        raise HTTPException(status_code=403, detail="이메일 인증이 필요합니다.")

    # 마지막 로그인 시간 업데이트
    client_ip = request.client.host
    await db_handler.execute_query(
        "UPDATE users SET last_login = NOW(), ip = %s WHERE id = %s",
        (client_ip, user['id'])
    )

    # 세션에 유저 정보 저장
    request.session['user'] = {
        "id": user['id'],
        "email": user['email'],
        "name": user['name'],
        "is_admin": bool(user.get('is_admin', 0))
    }

    return {"success": True, "message": "로그인 성공"}


@router.post("/logout")
async def logout(request: Request):
    """로그아웃"""
    request.session.clear()
    return {"success": True, "message": "로그아웃 되었습니다."}


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordSchema):
    """비밀번호 재설정 코드 발송"""

    user = await db_handler.fetch_one(
        "SELECT id, name, password_hash FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        # 보안상 계정 존재 여부를 노출하지 않음
        return {"success": True, "message": "해당 이메일로 비밀번호 재설정 코드가 발송되었습니다."}

    if not user.get('password_hash'):
        # 소셜 로그인 전용 계정
        return {"success": True, "message": "해당 이메일로 비밀번호 재설정 코드가 발송되었습니다."}

    # OTP 생성 및 이메일 발송
    code = await otp_manager.create_otp(f"reset:{data.email}")

    html_content = f"""
    <div style="font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
        <div style="text-align: center; margin-bottom: 32px;">
            <h1 style="color: #2563eb; margin: 0; font-size: 24px;">비밀번호 재설정</h1>
        </div>
        <p style="color: #374151; font-size: 16px; margin-bottom: 24px;">
            안녕하세요, <strong>{user['name']}</strong>님!<br>
            비밀번호 재설정을 위한 인증 코드입니다.
        </p>
        <div style="background: #f3f4f6; padding: 24px; text-align: center; border-radius: 12px; margin: 24px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1f2937;">{code}</span>
        </div>
        <p style="color: #6b7280; font-size: 14px; text-align: center;">
            이 인증 코드는 5분 동안 유효합니다.
        </p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
        <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            본인이 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.<br>
            비밀번호는 변경되지 않습니다.
        </p>
    </div>
    """

    send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 비밀번호 재설정 코드",
        html_content=html_content,
        text_content=f"비밀번호 재설정 코드: {code} (5분 동안 유효)"
    )

    return {"success": True, "message": "해당 이메일로 비밀번호 재설정 코드가 발송되었습니다."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordSchema):
    """비밀번호 재설정"""

    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    # OTP 검증
    result = await otp_manager.verify_otp(f"reset:{data.email}", data.code)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    # 유저 확인
    user = await db_handler.fetch_one(
        "SELECT id FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    # 비밀번호 업데이트
    new_hash = hash_password(data.new_password)
    await db_handler.execute_query(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (new_hash, user['id'])
    )

    return {"success": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요."}
