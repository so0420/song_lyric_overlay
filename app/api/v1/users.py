from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import FileResponse
from app.database.mariadb import db_handler
from app.core.auth import get_current_user_api
from app.utils.csrf import verify_csrf
from app.utils.image_sniff import ALLOWED_IMAGE
from app.utils.image_storage import (
    MAX_PROFILE_IMAGE_BYTES,
    new_temp_path,
    resolve_profile_image_path,
)
from app.utils.image_upload import receive_image, unlink_image
from app.utils.log import logger
from app.utils.mailer import send_email
from app.utils.otp import otp_manager
from app.utils.password import hash_password, verify_password, validate_password
from app.utils.rate_limit import RATE_LIMITS, limiter
from app.utils.config import config
from app.schemas.users import ProfileUpdateSchema, PasswordChangeSchema, EmailOtpSchema

router = APIRouter()

# 프로필 사진 서빙 URL 접두사. users.picture 에는 이 접두사가 붙은 값이 저장된다.
PROFILE_IMAGE_URL_PREFIX = "/api/v1/users/profile-image/"

# 서빙할 때 붙일 Content-Type. 확장자는 우리가 매직바이트로 판별해서 붙인 것뿐이라
# 여기서 되짚어도 클라이언트 신고값을 신뢰하는 게 아니다.
_MIME_BY_EXTENSION = {ext: mime for mime, ext in ALLOWED_IMAGE.items()}


async def _unlink_profile_image(storage_path: str | None) -> None:
    """옛 프로필 사진 파일을 지운다. 실패해도 요청을 실패시키지는 않는다."""
    await unlink_image(storage_path, resolve_profile_image_path, "profile-image")


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


# ---------------------------------------------------------------------
# 프로필 사진
# ---------------------------------------------------------------------

@router.post("/me/picture", dependencies=[Depends(verify_csrf)])
@limiter.limit(RATE_LIMITS["upload_hour"])
@limiter.limit(RATE_LIMITS["upload_minute"])
async def upload_my_picture(
    request: Request,
    user=Depends(get_current_user_api),
):
    """프로필 사진 업로드. **요청 본문 = 이미지 바이트 원본** (멀티파트 아님).

    본문 수신·검증·배치는 app/utils/image_upload.py 의 receive_image 가 맡는다
    (멀티파트를 쓰지 않는 이유도 그 모듈 주석 참고).

    브라우저는 올리기 전에 512px 정사각형 JPEG 으로 줄여서 보내지만
    (app/static/js/profile_image.js), 서버는 그 전제를 믿지 않고 크기와
    매직바이트를 다시 확인한다.
    """
    stored = await receive_image(
        request,
        max_bytes=MAX_PROFILE_IMAGE_BYTES,
        temp_factory=new_temp_path,
        resolver=resolve_profile_image_path,
        oversize_detail="프로필 사진은 5MB 를 넘을 수 없습니다.",
    )

    picture_url = PROFILE_IMAGE_URL_PREFIX + stored.storage_path

    # 옛 사진 경로를 먼저 확보한 뒤 갈아끼운다 (갱신 후에는 알 수 없다)
    previous = await db_handler.fetch_one(
        "SELECT picture_path FROM users WHERE id = %s", (user['id'],)
    )
    try:
        await db_handler.execute_query(
            "UPDATE users SET picture = %s, picture_path = %s WHERE id = %s",
            (picture_url, stored.storage_path, user['id']),
        )
    except Exception:
        # DB 기록 실패 — 아무도 참조하지 못하는 고아 파일을 남기지 않는다
        stored.path.unlink(missing_ok=True)
        raise

    await _unlink_profile_image(previous.get("picture_path") if previous else None)

    logger.info(f"[profile-image] 업로드 완료 user={user['id']} {stored.mime} {stored.byte_size}B")
    return {"success": True, "picture": picture_url}


@router.delete("/me/picture", dependencies=[Depends(verify_csrf)])
async def delete_my_picture(user=Depends(get_current_user_api)):
    """프로필 사진 삭제 — 기본 이니셜 배지로 돌아간다."""
    previous = await db_handler.fetch_one(
        "SELECT picture_path FROM users WHERE id = %s", (user['id'],)
    )
    await db_handler.execute_query(
        "UPDATE users SET picture = NULL, picture_path = NULL WHERE id = %s",
        (user['id'],),
    )
    await _unlink_profile_image(previous.get("picture_path") if previous else None)
    return {"success": True}


@router.get("/profile-image/{storage_path:path}")
async def get_profile_image(storage_path: str):
    """프로필 사진 서빙 (비로그인 열람 가능).

    공개 노래책 페이지에 그대로 노출되는 자산이라 인증을 걸지 않는다.
    경로는 uuid4 기반이고 사진을 바꿀 때마다 새 경로가 되므로,
    옛 URL 은 파일과 함께 사라진다 (그래서 immutable 로 캐시해도 안전하다).
    """
    try:
        path = resolve_profile_image_path(storage_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    if not path.is_file():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    mime = _MIME_BY_EXTENSION.get(path.suffix.lower().lstrip("."))
    if mime is None:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    # filename= 을 넘기면 Content-Disposition 이 attachment 가 되어 표시 대신
    # 다운로드가 되므로 넘기지 않는다.
    return FileResponse(
        path,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
