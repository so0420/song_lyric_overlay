import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.utils.config import settings
from app.utils.log import logger

def send_email(to_email: str, subject: str, html_content: str = None, text_content: str = None):
    """
    이메일을 발송합니다.
    
    원본 소스코드 참고: https://dev-gallery.tistory.com/10

    :param to_email: 수신자 이메일
    :param subject: 제목
    :param html_content: HTML 내용
    :param text_content: 일반 텍스트 내용 (html이 호환되지 않을 경우를 대비)
    :return: 성공 여부
    """
    my_email = settings.email_sender
    password = settings.google_app_key
    smtp_address = settings.email_smtp_address
    
    # root 메시지 생성
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = my_email
    message["To"] = to_email

    # 일반 텍스트 부분 추가 (html이 호환되지 않을 경우를 대비)
    if text_content:
        part1 = MIMEText(text_content, "plain", _charset="utf-8")
        message.attach(part1)
    
    # HTML 부분 추가
    if html_content:
        part2 = MIMEText(html_content, "html", _charset="utf-8")
        message.attach(part2)

    # SMTP 서버 연결 및 발송
    try:
        with smtplib.SMTP(smtp_address, 587) as server:
            server.starttls()
            server.login(my_email, password)
            server.sendmail(my_email, to_email, message.as_string())
        logger.info(f'메일 전송 성공 - 수신자: {to_email}, 제목: {subject}')
        return True
    except Exception as e:
        logger.error(f'메일 전송 중 오류 발생: {e}')
        return False

if __name__ == "__main__":
    # 테스트 코드
    test_subject = "안녕하세요, 이메일 발송 테스트입니다."
    test_html = """
    <html>
        <body>
            <h1 style="color: #4A90E2;">Hello!</h1>
            <p>이것은 <strong>HTML</strong> 형식의 테스트 이메일입니다.</p>
            <p>한글 테스트: 가나다라마바사</p>
        </body>
    </html>
    """
    test_text = "이것은 일반 텍스트 형식의 테스트 이메일입니다. 한글 테스트: 가나다라마바사"
    
    success = send_email(
        to_email="nicestar0911@gmail.com",
        subject=test_subject,
        html_content=test_html,
        text_content=test_text
    )
    
    if success:
        print("이메일 발송 성공!")
    else:
        print("이메일 발송 실패.")