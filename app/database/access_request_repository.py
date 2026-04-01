from app.database.mariadb import db_handler
from app.database.redis.redis import redis
from app.schemas.access_request import AccessRequestCreateSchema, AccessRequestStatus
from typing import Optional, Dict, Any, List

AUTO_APPROVE_KEY = "admin:auto_approve_access"


class AccessRequestRepository:
    def __init__(self, db=db_handler):
        self.db = db

    async def get_auto_approve(self) -> bool:
        """자동 승인 설정 조회"""
        val = await redis.get(AUTO_APPROVE_KEY)
        return val == "1"

    async def set_auto_approve(self, enabled: bool) -> None:
        """자동 승인 설정 변경"""
        await redis.set(AUTO_APPROVE_KEY, "1" if enabled else "0")

    async def auto_approve_request(self, request_id: int, user_id: int) -> bool:
        """요청 자동 승인 처리"""
        await self.db.execute_query(
            """UPDATE overlay_access_requests
               SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (request_id,)
        )
        await self.db.execute_query(
            "UPDATE users SET overlay_approved = 1 WHERE id = %s",
            (user_id,)
        )
        return True

    async def get_user_latest_request(self, user_id: int) -> Optional[Dict[str, Any]]:
        """사용자의 가장 최근 요청 조회"""
        result = await self.db.fetch_one(
            """SELECT id, user_id, platform_url, message, status, rejection_reason,
                      reviewed_by, reviewed_at, created_at, updated_at
               FROM overlay_access_requests
               WHERE user_id = %s
               ORDER BY created_at DESC
               LIMIT 1""",
            (user_id,)
        )
        return dict(result) if result else None

    async def get_user_pending_request(self, user_id: int) -> Optional[Dict[str, Any]]:
        """사용자의 대기 중인 요청 조회"""
        result = await self.db.fetch_one(
            """SELECT id, user_id, platform_url, message, status, rejection_reason,
                      reviewed_by, reviewed_at, created_at, updated_at
               FROM overlay_access_requests
               WHERE user_id = %s AND status = 'pending'
               ORDER BY created_at DESC
               LIMIT 1""",
            (user_id,)
        )
        return dict(result) if result else None

    async def create_request(self, user_id: int, data: AccessRequestCreateSchema) -> int:
        """접근 요청 생성"""
        request_id = await self.db.execute_query(
            """INSERT INTO overlay_access_requests (user_id, platform_url, message, status)
               VALUES (%s, %s, %s, 'pending')""",
            (user_id, data.platform_url, data.message)
        )
        return request_id

    async def get_all_requests(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """모든 요청 조회 (관리자용)"""
        if status:
            results = await self.db.fetch_all(
                """SELECT r.id, r.user_id, r.platform_url, r.message, r.status, r.rejection_reason,
                          r.reviewed_by, r.reviewed_at, r.created_at, r.updated_at,
                          u.name as user_name, u.email as user_email
                   FROM overlay_access_requests r
                   JOIN users u ON r.user_id = u.id
                   WHERE r.status = %s
                   ORDER BY r.created_at DESC
                   LIMIT %s OFFSET %s""",
                (status, limit, offset)
            )
        else:
            results = await self.db.fetch_all(
                """SELECT r.id, r.user_id, r.platform_url, r.message, r.status, r.rejection_reason,
                          r.reviewed_by, r.reviewed_at, r.created_at, r.updated_at,
                          u.name as user_name, u.email as user_email
                   FROM overlay_access_requests r
                   JOIN users u ON r.user_id = u.id
                   ORDER BY
                       CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END,
                       r.created_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset)
            )
        return [dict(r) for r in results]

    async def get_pending_count(self) -> int:
        """대기 중인 요청 수"""
        result = await self.db.fetch_one(
            "SELECT COUNT(*) as count FROM overlay_access_requests WHERE status = 'pending'"
        )
        return result['count'] if result else 0

    async def get_request_by_id(self, request_id: int) -> Optional[Dict[str, Any]]:
        """요청 ID로 조회"""
        result = await self.db.fetch_one(
            """SELECT r.id, r.user_id, r.platform_url, r.message, r.status, r.rejection_reason,
                      r.reviewed_by, r.reviewed_at, r.created_at, r.updated_at,
                      u.name as user_name, u.email as user_email
               FROM overlay_access_requests r
               JOIN users u ON r.user_id = u.id
               WHERE r.id = %s""",
            (request_id,)
        )
        return dict(result) if result else None

    async def approve_request(self, request_id: int, admin_id: int) -> bool:
        """요청 승인"""
        # 요청 정보 가져오기
        request = await self.get_request_by_id(request_id)
        if not request or request['status'] != 'pending':
            return False

        # 요청 상태 업데이트
        await self.db.execute_query(
            """UPDATE overlay_access_requests
               SET status = 'approved', reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (admin_id, request_id)
        )

        # 사용자 승인 상태 업데이트
        await self.db.execute_query(
            "UPDATE users SET overlay_approved = 1 WHERE id = %s",
            (request['user_id'],)
        )

        return True

    async def reject_request(self, request_id: int, admin_id: int, reason: str) -> bool:
        """요청 거절"""
        request = await self.get_request_by_id(request_id)
        if not request or request['status'] != 'pending':
            return False

        await self.db.execute_query(
            """UPDATE overlay_access_requests
               SET status = 'rejected', rejection_reason = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (reason, admin_id, request_id)
        )

        return True

    async def is_user_approved(self, user_id: int) -> bool:
        """사용자 승인 여부 확인"""
        result = await self.db.fetch_one(
            "SELECT overlay_approved, is_admin FROM users WHERE id = %s",
            (user_id,)
        )
        if result:
            # 관리자는 자동 승인
            return result['is_admin'] == 1 or result['overlay_approved'] == 1
        return False

    async def revoke_approval(self, user_id: int, admin_id: int, reason: str) -> bool:
        """승인 취소 (권한 회수)"""
        # 사용자 승인 상태 업데이트
        await self.db.execute_query(
            "UPDATE users SET overlay_approved = 0 WHERE id = %s",
            (user_id,)
        )

        # 가장 최근 승인된 요청을 회수로 변경
        latest_approved = await self.db.fetch_one(
            """SELECT id FROM overlay_access_requests
               WHERE user_id = %s AND status = 'approved'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,)
        )

        if latest_approved:
            await self.db.execute_query(
                """UPDATE overlay_access_requests
                   SET status = 'revoked', rejection_reason = %s, reviewed_by = %s, reviewed_at = CURRENT_TIMESTAMP
                   WHERE id = %s""",
                (reason, admin_id, latest_approved['id'])
            )
        else:
            # 승인된 요청이 없으면 새 회수 레코드 생성
            await self.db.execute_query(
                """INSERT INTO overlay_access_requests
                   (user_id, platform_url, message, status, rejection_reason, reviewed_by, reviewed_at)
                   VALUES (%s, '권한 회수', '관리자에 의해 권한이 회수됨', 'revoked', %s, %s, CURRENT_TIMESTAMP)""",
                (user_id, reason, admin_id)
            )

        return True

    async def get_approved_users(self, search: str = None, limit: int = 50, offset: int = 0) -> list:
        """승인된 사용자 목록 조회"""
        if search:
            search_pattern = f"%{search}%"
            results = await self.db.fetch_all(
                """SELECT u.id, u.name, u.email, u.overlay_approved, u.created_at,
                          r.platform_url, r.reviewed_at as approved_at
                   FROM users u
                   LEFT JOIN (
                       SELECT user_id, platform_url, reviewed_at,
                              ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY reviewed_at DESC) as rn
                       FROM overlay_access_requests
                       WHERE status = 'approved'
                   ) r ON u.id = r.user_id AND r.rn = 1
                   WHERE u.overlay_approved = 1 AND u.is_admin = 0
                     AND (u.name LIKE %s OR u.email LIKE %s)
                   ORDER BY r.reviewed_at DESC
                   LIMIT %s OFFSET %s""",
                (search_pattern, search_pattern, limit, offset)
            )
        else:
            results = await self.db.fetch_all(
                """SELECT u.id, u.name, u.email, u.overlay_approved, u.created_at,
                          r.platform_url, r.reviewed_at as approved_at
                   FROM users u
                   LEFT JOIN (
                       SELECT user_id, platform_url, reviewed_at,
                              ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY reviewed_at DESC) as rn
                       FROM overlay_access_requests
                       WHERE status = 'approved'
                   ) r ON u.id = r.user_id AND r.rn = 1
                   WHERE u.overlay_approved = 1 AND u.is_admin = 0
                   ORDER BY r.reviewed_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset)
            )
        return [dict(r) for r in results]


def get_access_request_repository() -> AccessRequestRepository:
    return AccessRequestRepository()
