"""
문의 답변 이메일 HTML 템플릿
"""

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
