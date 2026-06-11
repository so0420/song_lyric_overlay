import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
from app.utils.config import settings

# 로그 디렉토리 설정
LOG_DIR = settings.log_file_path

# Windows 콘솔 한글 깨짐 방지 (표준 출력을 UTF-8로 설정)
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

class ColoredFormatter(logging.Formatter):
    """콘솔 출력을 위한 색상 포맷터"""
    
    # ANSI 색상 코드
    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"
    bold_red = "\033[1;31m"
    cyan = "\033[96m"
    reset = "\033[0m"

    FORMAT = '[%(asctime)s] %(levelname)-8s [%(name)s | %(filename)s:%(lineno)d] - %(message)s'

    LEVEL_COLORS = {
        logging.DEBUG: cyan,
        logging.INFO: green,
        logging.WARNING: yellow,
        logging.ERROR: red,
        logging.CRITICAL: bold_red,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.reset)
        # levelname 부분에만 색상을 입힙니다.
        original_levelname = record.levelname
        record.levelname = f"{color}{original_levelname:8s}{self.reset}"
        
        formatter = logging.Formatter(self.FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
        result = formatter.format(record)
        
        # 다른 핸들러에 영향을 주지 않도록 복구
        record.levelname = original_levelname
        return result

def get_logger(name: str = "songbook"):
    """
    설정된 로거를 반환합니다.
    콘솔에는 INFO 레벨 이상, 파일에는 DEBUG 레벨 이상을 기록합니다.
    """
    if not os.path.exists(settings.log_file_path):
        os.makedirs(settings.log_file_path)
    logger = logging.getLogger(name)
    
    # 이미 핸들러가 설정되어 있다면 중복 추가 방지
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 기본 포맷 설정 (파일용)
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(name)s | %(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 콘솔 핸들러 설정 (색상 포맷터 적용)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 파일 핸들러 설정
    current_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    log_file = os.path.join(LOG_DIR, f"{current_time}.log")
    
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger

def setup_uvicorn_logging():
    """
    Uvicorn과 FastAPI의 로거를 우리 로거의 설정(핸들러, 포맷터)과 통합합니다.
    """
    # 통합할 대상 로거 이름들
    target_loggers = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "fastapi",
    ]

    # 단순화된 포맷 설정
    simple_format = '[%(asctime)s] %(levelname)-8s [Fastapi] - %(message)s'
    
    # 단순화된 콘솔 포맷터 (색상 포함)
    simple_console_formatter = ColoredFormatter()
    simple_console_formatter.FORMAT = simple_format
    
    # 단순화된 파일 포맷터
    simple_file_formatter = logging.Formatter(simple_format, datefmt='%Y-%m-%d %H:%M:%S')

    for logger_name in target_loggers:
        logger_obj = logging.getLogger(logger_name)
        
        # 기존 핸들러 제거
        logger_obj.handlers = []
        
        # 새 핸들러 생성 (기본 로거의 출력 대상을 따라감)
        # 콘솔 핸들러
        console_h = logging.StreamHandler(sys.stdout)
        console_h.setLevel(logging.INFO)
        console_h.setFormatter(simple_console_formatter)
        logger_obj.addHandler(console_h)
        
        # 파일 핸들러 (현재 활성화된 파일 로그에 기록)
        songbook_logger = get_logger()
        for h in songbook_logger.handlers:
            if isinstance(h, TimedRotatingFileHandler):
                log_file = h.baseFilename
                file_h = TimedRotatingFileHandler(
                    log_file,
                    when="midnight",
                    interval=1,
                    backupCount=30,
                    encoding="utf-8"
                )
                file_h.setLevel(logging.DEBUG)
                file_h.setFormatter(simple_file_formatter)
                logger_obj.addHandler(file_h)
                break
        
        # 전파 중지 (중복 출력 방지)
        logger_obj.propagate = False
        # 레벨 설정 (INFO 이상만 출력)
        logger_obj.setLevel(logging.INFO)

    # 루트 로거도 우리 핸들러를 사용하도록 설정 (라이브러리 로그 캡처용)
    # root_logger = logging.getLogger()
    # for handler in handlers:
    #     if handler not in root_logger.handlers:
    #         root_logger.addHandler(handler)


# 기본 로거 인스턴스
logger = get_logger()

def handle_exception(exc_type, exc_value, exc_traceback):
    """
    처리되지 않은 예외를 캐치하여 로거에 기록합니다.
    (정상 종료/이벤트 루프 정리 과정의 무해한 예외는 제외)
    """
    # 정상 종료 신호는 기본 처리에 위임
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit, GeneratorExit)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # 서버 종료 시 uvicorn/asyncio 가 내는 알려진 무해한 종료 예외는 무시
    if issubclass(exc_type, RuntimeError) and "Event loop stopped before Future completed" in str(exc_value):
        return

    logger.critical("Unhandled exception occurred!", exc_info=(exc_type, exc_value, exc_traceback))

# 전역 예외 처리기 등록
sys.excepthook = handle_exception
