import os
from fastapi.templating import Jinja2Templates

# 프로젝트 루트 디렉토리 설정 (app/utils/templates.py 기준)
# app/utils/templates.py -> app/utils -> app -> app/templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# 전역 Jinja2Templates 인스턴스
templates = Jinja2Templates(directory=TEMPLATES_DIR)
