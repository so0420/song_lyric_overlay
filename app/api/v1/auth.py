import json

from fastapi import APIRouter, Request, HTTPException, Depends
from app.database.mariadb import db_handler
from app.database.redis.redis import redis
from app.database.account_purge import purge_account, RETENTION_DAYS
from app.utils.config import settings
from app.utils.log import logger
from app.utils.mailer import send_email
from app.utils.otp import otp_manager
from app.utils.config import config
from app.utils.rate_limit import limiter, RATE_LIMITS
from app.utils.password import hash_password, verify_password, validate_password
from app.utils.email_templates import get_verification_email, get_password_reset_email
from app.schemas.auth import (
    RegisterSchema,
    VerifyEmailSchema,
    LoginSchema,
    ResendVerificationSchema,
    ForgotPasswordSchema,
    ResetPasswordSchema
)

router = APIRouter()


@router.post("/register")
@limiter.limit(RATE_LIMITS["auth"])
async def register(request: Request, data: RegisterSchema):
    """회원가입 - 이메일 인증 코드 발송"""

    # 비밀번호 복잡성 검증
    is_valid, error_msg = validate_password(data.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # 이메일 중복 확인
    # purge_due: 보관기간이 지나 자동 파기를 기다리는 중인 계정 (파기 작업은 6시간마다 돈다)
    existing_user = await db_handler.fetch_one(
        "SELECT id, email_verified, deleted_at, "
        "       (deleted_at < NOW() - INTERVAL %s DAY) AS purge_due "
        "  FROM users WHERE email = %s",
        (RETENTION_DAYS, data.email)
    )

    if existing_user and existing_user.get('deleted_at'):
        # 탈퇴한 계정의 이메일 — 복구할지 새로 시작할지 물어본 뒤 진행한다.
        # 어느 쪽이든 실제 반영은 이메일 인증(OTP)을 통과한 뒤에 한다.
        if existing_user.get('purge_due'):
            # 보관기간이 지난 계정은 어차피 파기 대상이라 복구를 묻지 않는다.
            # (약관 제9조 ④ 3호 "30일이 지난 경우 묻지 않고 새 계정으로 가입")
            restore = False
        elif data.restore is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "withdrawn_account",
                    "message": "이 이메일로 탈퇴한 계정이 있습니다. 이전 계정을 복구할까요?",
                    "deleted_at": existing_user['deleted_at'].isoformat()
                                  if existing_user.get('deleted_at') else None,
                },
            )
        else:
            restore = data.restore

        password_hash = hash_password(data.password)

        # 이전 요청에서 고른 의사가 남아 있으면 이번 선택을 덮어써 버린다.
        # ('새 계정'을 골랐다가 되돌아와 '복구'로 바꾸면, 남은 키 때문에
        #  인증 순간 복구가 아니라 파기가 일어난다) 어느 쪽을 골랐든 먼저 지운다.
        await redis.delete(f"pending_register:{data.email}")

        if restore:
            # 복구 예정 — 인증 후 되살릴 수 있도록 새 이름·비밀번호만 미리 적어 둔다.
            # deleted_at 은 그대로 두므로 인증 전까지는 여전히 탈퇴 상태다.
            await db_handler.execute_query(
                "UPDATE users SET password_hash = %s, name = %s, email_verified = 0 WHERE id = %s",
                (password_hash, data.name, existing_user['id'])
            )
        else:
            # 새 계정으로 시작 — 기존 계정은 인증을 통과한 뒤에 파기한다.
            # 인증 전에 건드리면 이메일만 아는 사람이 남의 탈퇴 계정을 지울 수 있다.
            await redis.set(
                f"pending_register:{data.email}",
                json.dumps({"name": data.name, "password_hash": password_hash}),
                ex=settings.otp_ttl,
            )
    elif existing_user:
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
    html_content, text_content = get_verification_email(data.name, code)

    success = send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 이메일 인증 코드",
        html_content=html_content,
        text_content=text_content
    )

    if not success:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.")

    return {"success": True, "message": "인증 코드가 이메일로 발송되었습니다."}


@router.post("/verify-email")
@limiter.limit(RATE_LIMITS["otp"])
async def verify_email(request: Request, data: VerifyEmailSchema):
    """이메일 인증 확인"""

    # OTP 검증
    result = await otp_manager.verify_otp(f"register:{data.email}", data.code)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    user = await db_handler.fetch_one(
        "SELECT id, deleted_at, email_verified FROM users WHERE email = %s",
        (data.email,)
    )

    # 탈퇴 계정을 버리고 새로 시작하기로 한 경우 (register 에서 restore=False)
    pending_raw = await redis.get(f"pending_register:{data.email}")
    if pending_raw:
        pending = json.loads(pending_raw)
        if user and user.get('deleted_at'):
            # 이메일을 비워야 같은 주소로 새 행을 만들 수 있다.
            # 파기 항목·방식은 자동 파기와 동일하다.
            await purge_account(user['id'])
        await db_handler.execute_query(
            "INSERT INTO users (email, password_hash, name, email_verified) VALUES (%s, %s, %s, 1)",
            (data.email, pending['password_hash'], pending['name'])
        )
        await redis.delete(f"pending_register:{data.email}")
        logger.info(f"탈퇴 계정을 정리하고 새 계정을 생성했습니다: {data.email}")
        return {"success": True, "message": "새 계정이 만들어졌습니다. 로그인해주세요."}

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    # 탈퇴 계정 복구 (register 에서 restore=True)
    if user.get('deleted_at'):
        # 복구를 고른 경우에만 register 가 email_verified 를 0 으로 내려놓는다.
        # 1 로 남아 있다면 '새 계정으로 시작'을 골랐는데 그 의사(pending)가 만료된 것이다.
        # 여기서 막지 않으면 고르지 않은 '복구'가 대신 실행된다.
        if user.get('email_verified'):
            raise HTTPException(
                status_code=400,
                detail="가입 요청의 유효시간이 지났습니다. 회원가입을 처음부터 다시 진행해주세요."
            )
        await db_handler.execute_query(
            "UPDATE users SET deleted_at = NULL, is_active = 1, email_verified = 1 WHERE id = %s",
            (user['id'],)
        )
        logger.info(f"탈퇴 계정을 복구했습니다: {data.email}")
        return {"success": True, "message": "계정이 복구되었습니다. 로그인해주세요."}

    await db_handler.execute_query(
        "UPDATE users SET email_verified = 1 WHERE id = %s",
        (user['id'],)
    )

    return {"success": True, "message": "이메일 인증이 완료되었습니다. 로그인해주세요."}


@router.post("/resend-verification")
@limiter.limit(RATE_LIMITS["otp"])
async def resend_verification(request: Request, data: ResendVerificationSchema):
    """인증 코드 재발송"""

    user = await db_handler.fetch_one(
        "SELECT id, name, email_verified, deleted_at FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    # 탈퇴 계정으로 재가입(복구/새 계정) 중이면 기존 행의 인증 여부와 무관하게 재발송해야 한다.
    # '새 계정' 경로는 기존 행을 건드리지 않으므로 email_verified 가 1로 남아 있다.
    pending_raw = await redis.get(f"pending_register:{data.email}")
    rejoining = bool(pending_raw) or bool(user.get('deleted_at'))

    if user.get('email_verified') and not rejoining:
        raise HTTPException(status_code=400, detail="이미 인증된 계정입니다.")

    # OTP 생성 및 이메일 발송
    code = await otp_manager.create_otp(f"register:{data.email}")

    if pending_raw:
        # OTP 만 연장하면 '새 계정으로 시작' 의사가 먼저 만료되어,
        # 새로 받은 코드로 인증했을 때 고르지 않은 '복구'가 실행된다. 수명을 맞춰 준다.
        await redis.set(
            f"pending_register:{data.email}",
            pending_raw,
            ex=settings.otp_ttl,
        )

    display_name = json.loads(pending_raw)['name'] if pending_raw else user['name']
    html_content, text_content = get_verification_email(display_name, code)

    success = send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 이메일 인증 코드",
        html_content=html_content,
        text_content=text_content
    )

    if not success:
        raise HTTPException(status_code=500, detail="이메일 발송에 실패했습니다.")

    return {"success": True, "message": "인증 코드가 재발송되었습니다."}


@router.post("/login")
@limiter.limit(RATE_LIMITS["auth"])
async def login(request: Request, data: LoginSchema):
    """이메일 + 비밀번호 로그인"""

    user = await db_handler.fetch_one(
        "SELECT * FROM users WHERE email = %s AND deleted_at IS NULL",
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
@limiter.limit(RATE_LIMITS["otp"])
async def forgot_password(request: Request, data: ForgotPasswordSchema):
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
    html_content, text_content = get_password_reset_email(user['name'], code)

    send_email(
        to_email=data.email,
        subject=f"[{config.app_name}] 비밀번호 재설정 코드",
        html_content=html_content,
        text_content=text_content
    )

    return {"success": True, "message": "해당 이메일로 비밀번호 재설정 코드가 발송되었습니다."}


@router.post("/reset-password")
@limiter.limit(RATE_LIMITS["otp"])
async def reset_password(request: Request, data: ResetPasswordSchema):
    """비밀번호 재설정"""

    is_valid, error_msg = validate_password(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    # OTP 검증
    result = await otp_manager.verify_otp(f"reset:{data.email}", data.code)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    # 유저 확인
    user = await db_handler.fetch_one(
        "SELECT id, deleted_at FROM users WHERE email = %s",
        (data.email,)
    )

    if not user:
        raise HTTPException(status_code=400, detail="해당 이메일로 가입된 계정을 찾을 수 없습니다.")

    # 탈퇴한 계정은 비밀번호를 바꿔 줘도 로그인할 수 없다(login 이 deleted_at 을 거른다).
    # 안내 없이 성공시키면 "바꿨는데 로그인이 안 된다"는 막다른 길이 된다.
    # (여기서만 알리고 forgot-password 는 그대로 둔다 — 거기서 알리면 계정 존재 여부가 새어 나간다)
    if user.get('deleted_at'):
        raise HTTPException(
            status_code=400,
            detail="탈퇴한 계정입니다. 같은 이메일로 회원가입을 진행하시면 이전 계정을 복구하실 수 있습니다."
        )

    # 비밀번호 업데이트
    new_hash = hash_password(data.new_password)
    await db_handler.execute_query(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (new_hash, user['id'])
    )

    return {"success": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요."}
