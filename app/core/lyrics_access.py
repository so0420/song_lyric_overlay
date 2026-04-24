"""가사 visibility(공개 범위) 접근 제어 유틸.

정책:
- 관리자(is_admin=1)는 항상 모든 가사 접근 가능
- 가사 소유자(owner_id 일치)는 항상 접근 가능
- visibility='public'   → 누구나
- visibility='private'  → 소유자+관리자만
- visibility='whitelist' → 소유자+관리자+lyrics_whitelist 에 등록된 유저
"""
from typing import Optional, Mapping, Any


async def can_view_lyrics(
    lyric_row: Mapping[str, Any],
    user: Optional[Mapping[str, Any]],
    repo,
) -> bool:
    """
    Args:
        lyric_row: song_lyrics 레코드 (최소 id, owner_id, visibility 포함)
        user: 로그인된 사용자 dict (없으면 None / 익명)
        repo: LyricsRepository (is_whitelisted 호출용)
    """
    if user and user.get("is_admin"):
        return True

    visibility = lyric_row.get("visibility", "public")
    if visibility == "public":
        return True

    if not user:
        return False

    if lyric_row.get("owner_id") == user["id"]:
        return True

    if visibility == "whitelist":
        return await repo.is_whitelisted(lyric_row["id"], user["id"])

    return False
