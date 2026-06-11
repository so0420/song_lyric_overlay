"""
Audit 로깅 유틸리티

관리자 및 중요 사용자 작업을 기록합니다.
"""
import json
from typing import Optional, Any, Dict
from fastapi import Request
from app.database.mariadb import db_handler


class AuditAction:
    """감사 로그 작업 유형"""
    # 접근 요청 관련
    APPROVE_ACCESS = "approve_access"
    REJECT_ACCESS = "reject_access"
    REVOKE_ACCESS = "revoke_access"

    # 사용자 관련
    USER_LOGIN = "user_login"
    USER_REGISTER = "user_register"
    PASSWORD_RESET = "password_reset"

    # 가사 관련
    LYRICS_CREATE = "lyrics_create"
    LYRICS_UPDATE = "lyrics_update"
    LYRICS_DELETE = "lyrics_delete"
    LYRICS_VISIBILITY_CHANGE = "lyrics_visibility_change"
    LYRICS_WHITELIST_CHANGE = "lyrics_whitelist_change"

    # 관리자 작업
    ADMIN_BROADCAST = "admin_broadcast"
    ADMIN_DISCONNECT = "admin_disconnect"
    ADMIN_IMPERSONATE = "admin_impersonate"            # 다른 사용자로 전환 시작
    ADMIN_IMPERSONATE_STOP = "admin_impersonate_stop"  # 전환 종료(관리자 복귀)


async def log_audit(
    actor_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None
) -> None:
    """
    감사 로그 기록

    Args:
        actor_id: 작업을 수행한 사용자 ID
        action: 수행한 작업 유형 (AuditAction 상수 사용)
        target_type: 대상 유형 (user, lyrics 등)
        target_id: 대상 ID
        details: 추가 상세 정보 (dict)
        ip_address: 요청 IP 주소
    """
    details_json = json.dumps(details, ensure_ascii=False) if details else None

    await db_handler.execute_query(
        """INSERT INTO audit_logs (actor_id, action, target_type, target_id, details, ip_address)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (actor_id, action, target_type, target_id, details_json, ip_address)
    )


def get_client_ip(request: Request) -> str:
    """요청에서 클라이언트 IP 추출"""
    # X-Forwarded-For 헤더 확인 (프록시/로드밸런서 뒤에 있는 경우)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
