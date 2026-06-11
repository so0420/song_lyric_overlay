from app.database.mariadb import db_handler
from typing import Optional, Dict, Any, List
import json
import uuid


# ---------------------------------------------------------------
# JSON TEXT 컬럼 공용 헬퍼 (tags, social_links 등)
# ---------------------------------------------------------------
def parse_json_field(value: Any, default: Any) -> Any:
    """TEXT 컬럼에 저장된 JSON 문자열을 파싱한다. 실패하거나 타입이 다르면 기본값 반환."""
    if value is None or value == "":
        return default
    # 이미 파싱된 값이면 그대로 반환 (멱등)
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except (ValueError, TypeError):
        return default


def dump_json_field(value: Any) -> str:
    """list/dict 를 JSON 문자열로 직렬화한다. 이미 문자열이면 그대로 통과 (멱등)."""
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else [], ensure_ascii=False)


# 공개 노출 필터: 탈퇴/비활성/승인 회수된 유저의 노래책은 즉시 비노출 (관리자는 항상 통과)
PUBLIC_EXPOSURE_FILTER = "u.is_active = 1 AND (u.overlay_approved = 1 OR u.is_admin = 1)"

# 공통 SELECT: 스트리머 프로필 + 유저 표시 정보 (탈퇴 유저 제외)
_BASE_SELECT = """
    SELECT s.*, u.name, u.picture
    FROM streamers s
    JOIN users u ON s.user_id = u.id AND u.deleted_at IS NULL
"""


class StreamerRepository:
    def __init__(self, db=db_handler):
        self.db = db

    # ---------------------------------------------------------------
    # 내부 헬퍼
    # ---------------------------------------------------------------
    @staticmethod
    def _normalize_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """JSON 컬럼(social_links, tags)을 파싱해서 반환 (실패 시 빈 리스트)"""
        if not row:
            return None
        row["social_links"] = parse_json_field(row.get("social_links"), [])
        row["tags"] = parse_json_field(row.get("tags"), [])
        return row

    # ---------------------------------------------------------------
    # 조회 (본인용 — 공개 노출 필터 없음)
    # ---------------------------------------------------------------
    async def get_by_user_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """user_id 로 스트리머 프로필 조회"""
        query = _BASE_SELECT + "WHERE s.user_id = %s"
        row = await self.db.fetch_one(query, (user_id,))
        return self._normalize_row(row)

    async def get_by_external_id(self, streamer_id: str) -> Optional[Dict[str, Any]]:
        """외부 노출용 스트리머 ID(UUID)로 프로필 조회"""
        query = _BASE_SELECT + "WHERE s.streamer_id = %s"
        row = await self.db.fetch_one(query, (streamer_id,))
        return self._normalize_row(row)

    async def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """공개 주소(slug)로 프로필 조회"""
        query = _BASE_SELECT + "WHERE s.slug = %s"
        row = await self.db.fetch_one(query, (slug,))
        return self._normalize_row(row)

    # ---------------------------------------------------------------
    # 조회 (공개용 — 공개 노출 필터 적용)
    # ---------------------------------------------------------------
    async def get_public_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """공개 노래책용 slug 조회 (미승인/비활성/탈퇴 유저는 비노출)"""
        query = _BASE_SELECT + f"WHERE s.slug = %s AND {PUBLIC_EXPOSURE_FILTER}"
        row = await self.db.fetch_one(query, (slug,))
        return self._normalize_row(row)

    async def get_public_by_external_id(self, streamer_id: str) -> Optional[Dict[str, Any]]:
        """공개 노래책용 외부 UUID 조회 (미승인/비활성/탈퇴 유저는 비노출)"""
        query = _BASE_SELECT + f"WHERE s.streamer_id = %s AND {PUBLIC_EXPOSURE_FILTER}"
        row = await self.db.fetch_one(query, (streamer_id,))
        return self._normalize_row(row)

    async def get_by_chzzk_channel_id(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """치지직 채널 ID(UID)로 스트리머 프로필 조회 (user_chzzk_channels 경유)

        채팅/후원 !신청 이벤트가 들어오면 어떤 스트리머의 것인지 역추적하는 데 쓴다.
        """
        query = (
            _BASE_SELECT
            + "JOIN user_chzzk_channels c ON s.user_id = c.user_id WHERE c.channel_id = %s"
        )
        row = await self.db.fetch_one(query, (channel_id,))
        return self._normalize_row(row)

    async def search_public(self, q: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """공개 스트리머 검색 (이름/slug LIKE). q 가 없으면 전체에서 최신순."""
        params: list = []
        query = _BASE_SELECT + f"WHERE {PUBLIC_EXPOSURE_FILTER}"
        if q:
            query += " AND (u.name LIKE %s OR s.slug LIKE %s)"
            pattern = f"%{q}%"
            params.extend([pattern, pattern])
        query += " ORDER BY s.created_at DESC LIMIT %s"
        params.append(limit)
        rows = await self.db.fetch_all(query, tuple(params))
        return [self._normalize_row(row) for row in rows]

    # ---------------------------------------------------------------
    # 생성 / 수정 / 삭제
    # ---------------------------------------------------------------
    async def create_profile(self, user_id: int, slug: str) -> int:
        """스트리머 프로필 생성. 외부 노출용 streamer_id(UUID)를 새로 발급한다.

        웹(노래책 페이지) 신청은 기본 ON — '신청 받기'(마스터)만 켜면 비로그인 시청자가
        바로 신청할 수 있게 한다. 마스터는 기본 OFF 이므로 켜기 전까지는 신청을 받지 않는다.
        """
        streamer_id = str(uuid.uuid4())
        query = """
            INSERT INTO streamers (user_id, streamer_id, slug, request_web_enabled)
            VALUES (%s, %s, %s, 1)
        """
        return await self.db.execute_query(query, (user_id, streamer_id, slug))

    async def update_profile(self, user_id: int, **fields) -> bool:
        """프로필 동적 UPDATE (화이트리스트 컬럼만). social_links/tags 는 JSON 직렬화."""
        allowed = {
            "slug", "description", "social_links", "tags",
            "request_enabled", "request_web_enabled", "request_auto_playlist",
            "request_chat_enabled", "request_donation_enabled", "default_price_cheese",
        }
        bool_cols = {
            "request_enabled", "request_web_enabled", "request_auto_playlist",
            "request_chat_enabled", "request_donation_enabled",
        }
        updates = []
        params = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            if key in ("social_links", "tags"):
                val = dump_json_field(val)
            elif key in bool_cols:
                val = 1 if val else 0
            updates.append(f"`{key}` = %s")
            params.append(val)

        if not updates:
            return False

        query = f"UPDATE streamers SET {', '.join(updates)} WHERE user_id = %s"
        params.append(user_id)
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, tuple(params))
                return cursor.rowcount > 0

    async def is_slug_taken(self, slug: str, exclude_user_id: Optional[int] = None) -> bool:
        """slug 중복 여부 확인 (exclude_user_id 본인 제외 가능)"""
        query = "SELECT 1 FROM streamers WHERE slug = %s"
        params: list = [slug]
        if exclude_user_id is not None:
            query += " AND user_id != %s"
            params.append(exclude_user_id)
        result = await self.db.fetch_one(query, tuple(params))
        return result is not None

    async def delete_profile(self, user_id: int) -> bool:
        """프로필 하드 삭제 (CASCADE 로 수록곡/신청도 함께 삭제됨)"""
        query = "DELETE FROM streamers WHERE user_id = %s"
        async with self.db.session() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id,))
                return cursor.rowcount > 0


def get_streamer_repository() -> StreamerRepository:
    return StreamerRepository()
