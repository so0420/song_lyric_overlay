import bcrypt
import re
from typing import Tuple


def hash_password(password: str) -> str:
    """비밀번호를 bcrypt로 해시"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """비밀번호 검증"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def validate_password(password: str) -> Tuple[bool, str]:
    """
    비밀번호 복잡성 검증
    - 최소 8자 이상
    - 영문 대문자 또는 소문자 포함
    - 숫자 포함

    Returns:
        (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "비밀번호는 8자 이상이어야 합니다."

    if not re.search(r'[a-zA-Z]', password):
        return False, "비밀번호에 영문자가 포함되어야 합니다."

    if not re.search(r'\d', password):
        return False, "비밀번호에 숫자가 포함되어야 합니다."

    return True, ""
