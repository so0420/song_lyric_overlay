"""
이메일 HTML 템플릿 모음
"""

from app.utils.config import config


def _get_base_email_layout(title: str, subtitle: str, content: str) -> str:
    """공통 이메일 레이아웃"""
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background-color: #f8fafc;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f8fafc; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%); padding: 32px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 700;">
                                {title}
                            </h1>
                            <p style="margin: 8px 0 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                                {subtitle}
                            </p>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px 32px;">
                            {content}
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8fafc; padding: 24px 32px; border-top: 1px solid #e2e8f0;">
                            <p style="margin: 0; text-align: center; font-size: 12px; color: #94a3b8;">
                                본 메일은 {config.app_name} 서비스에서 발송되었습니다.<br>
                                요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def _get_otp_block(code: str) -> str:
    """OTP 코드 블록 HTML"""
    return f"""
<div style="background: #f3f4f6; padding: 24px; text-align: center; border-radius: 12px; margin: 24px 0;">
    <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #1f2937;">{code}</span>
</div>
<p style="color: #6b7280; font-size: 14px; text-align: center;">
    이 인증 코드는 5분 동안 유효합니다.
</p>
"""


def get_verification_email(user_name: str, code: str) -> tuple[str, str]:
    """
    회원가입/재발송용 이메일 인증 템플릿

    :return: (html_content, text_content)
    """
    content = f"""
<p style="color: #374151; font-size: 16px; margin-bottom: 24px;">
    안녕하세요, <strong>{user_name}</strong>님!<br>
    아래 인증 코드를 입력하여 회원가입을 완료해주세요.
</p>
{_get_otp_block(code)}
"""

    html_content = _get_base_email_layout(
        title="이메일 인증",
        subtitle="회원가입 인증 코드",
        content=content
    )

    text_content = f"""안녕하세요, {user_name}님!

아래 인증 코드를 입력하여 회원가입을 완료해주세요.

인증 코드: {code}

이 인증 코드는 5분 동안 유효합니다.

본 메일은 {config.app_name} 서비스에서 발송되었습니다.
요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
"""

    return html_content, text_content


def get_password_reset_email(user_name: str, code: str) -> tuple[str, str]:
    """
    비밀번호 재설정용 이메일 템플릿

    :return: (html_content, text_content)
    """
    content = f"""
<p style="color: #374151; font-size: 16px; margin-bottom: 24px;">
    안녕하세요, <strong>{user_name}</strong>님!<br>
    비밀번호 재설정을 위한 인증 코드입니다.
</p>
{_get_otp_block(code)}
<hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
<p style="color: #9ca3af; font-size: 12px; text-align: center;">
    본인이 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.<br>
    비밀번호는 변경되지 않습니다.
</p>
"""

    html_content = _get_base_email_layout(
        title="비밀번호 재설정",
        subtitle="인증 코드 안내",
        content=content
    )

    text_content = f"""안녕하세요, {user_name}님!

비밀번호 재설정을 위한 인증 코드입니다.

인증 코드: {code}

이 인증 코드는 5분 동안 유효합니다.

본인이 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
비밀번호는 변경되지 않습니다.
"""

    return html_content, text_content


def get_inquiry_reply_email(
    user_name: str,
    subject: str,
    original_message: str,
    reply_content: str
) -> tuple[str, str]:
    """
    문의 답변 이메일 HTML과 텍스트 내용을 반환합니다.
    
    :return: (html_content, text_content)
    """
    
    html_content = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background-color: #f8fafc;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f8fafc; padding: 40px 20px;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%); padding: 32px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 700;">
                                🎵 PlayList
                            </h1>
                            <p style="margin: 8px 0 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                                문의에 답변 드립니다
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px 32px;">
                            <p style="margin: 0 0 24px 0; color: #0f172a; font-size: 16px; line-height: 1.6;">
                                안녕하세요, <strong>{user_name}</strong>님!
                            </p>
                            
                            <p style="margin: 0 0 24px 0; color: #64748b; font-size: 15px; line-height: 1.6;">
                                문의해 주신 내용에 대한 답변을 보내드립니다.
                            </p>
                            
                            <!-- Original Question -->
                            <div style="background-color: #f1f5f9; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                                <p style="margin: 0 0 12px 0; font-size: 13px; color: #64748b; font-weight: 600;">문의 내용</p>
                                <p style="margin: 0 0 8px 0; font-size: 15px; font-weight: 600; color: #0f172a;">{subject}</p>
                                <p style="margin: 0; font-size: 14px; color: #374151; line-height: 1.6; white-space: pre-wrap;">{original_message[:300]}{'...' if len(original_message) > 300 else ''}</p>
                            </div>
                            
                            <!-- Reply -->
                            <div style="background-color: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
                                <p style="margin: 0 0 12px 0; font-size: 13px; color: #64748b; font-weight: 600;">
                                    답변
                                </p>
                                <div style="font-size: 15px; color: #0f172a; line-height: 1.8; white-space: pre-wrap;">{reply_content}</div>
                            </div>
                            
                            <p style="margin: 0; color: #64748b; font-size: 14px; line-height: 1.6;">
                                추가 문의사항이 있으시면 언제든지 연락해 주세요.<br>
                                감사합니다.
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8fafc; padding: 24px 32px; border-top: 1px solid #e2e8f0;">
                            <p style="margin: 0; text-align: center; font-size: 12px; color: #94a3b8;">
                                © 2026 PlayList. All rights reserved.<br>
                                사업자등록번호: 837-35-01650
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    text_content = f"""
안녕하세요, {user_name}님!

문의해 주신 내용에 대한 답변을 보내드립니다.

---
[문의 내용]
{subject}

{original_message}

---
[답변]
{reply_content}

---
추가 문의사항이 있으시면 언제든지 연락해 주세요.
감사합니다.

© 2026 PlayList. All rights reserved.
사업자등록번호: 837-35-01650
"""

    return html_content, text_content
