"""치지직(Chzzk) 라이브 상세 조회

공개 API `https://api.chzzk.naver.com/service/v3.2/channels/{uid}/live-detail` 를
브라우저 User-Agent 로 위장해 호출한다. (OAuth/토큰 불필요 — 공개 정보)

노래 타임라인 기록에서 '방송 시작 시각(content.openDate)' 을 얻는 데 사용한다.
"""
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from app.utils.log import logger

# 치지직 API 는 브라우저가 아닌 요청을 막으므로 UA 를 위장한다.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

LIVE_DETAIL_URL = "https://api.chzzk.naver.com/service/v3.2/channels/{uid}/live-detail"

# 치지직 openDate 는 KST(UTC+9) 기준 naive 문자열 "YYYY-MM-DD HH:MM:SS" 로 온다.
KST = ZoneInfo("Asia/Seoul")


class ChzzkLiveError(Exception):
    """라이브 정보를 얻을 수 없을 때 (오프라인/조회 실패 등)."""


async def get_live_open_date(channel_id: str) -> datetime:
    """연동 채널의 현재 방송 시작 시각(openDate)을 KST-aware datetime 으로 반환.

    방송 중이 아니거나 조회에 실패하면 ChzzkLiveError 를 던진다.
    """
    url = LIVE_DETAIL_URL.format(uid=channel_id)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"치지직 라이브 조회 실패 (channel={channel_id}): {e}")
        raise ChzzkLiveError("방송 정보를 불러오지 못했습니다.")

    content = data.get("content") or {}
    open_date_str = content.get("openDate")
    status = content.get("status")

    # status 필드가 있으면 OPEN(방송 중)일 때만 허용. 없으면 openDate 유무로 판단.
    if status is not None and status != "OPEN":
        raise ChzzkLiveError("현재 방송 중이 아닙니다.")
    if not open_date_str:
        raise ChzzkLiveError("현재 방송 중이 아닙니다.")

    try:
        # "2026-07-22 20:00:00" (KST naive) → KST-aware
        open_date = datetime.strptime(open_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except ValueError:
        logger.warning(f"치지직 openDate 파싱 실패: {open_date_str!r}")
        raise ChzzkLiveError("방송 시작 시각을 해석할 수 없습니다.")

    return open_date


def now_kst() -> datetime:
    """현재 시각(KST-aware). 서버 타임존과 무관하게 KST 를 반환."""
    return datetime.now(KST)
