import os
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

# 프로젝트 루트 디렉토리 설정 (app/utils/templates.py 기준)
# app/utils/templates.py -> app/utils -> app -> app/templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# 전역 Jinja2Templates 인스턴스
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def csrf_input(request) -> Markup:
    """CSRF 토큰을 hidden input으로 반환"""
    try:
        from app.utils.csrf import get_csrf_token
        token = get_csrf_token(request)
        return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')
    except Exception:
        return Markup('<input type="hidden" name="csrf_token" value="">')


def csrf_token(request) -> str:
    """CSRF 토큰 값만 반환"""
    try:
        from app.utils.csrf import get_csrf_token
        return get_csrf_token(request)
    except Exception:
        return ""


# Jinja2 전역 함수 등록
templates.env.globals["csrf_input"] = csrf_input
templates.env.globals["csrf_token"] = csrf_token
