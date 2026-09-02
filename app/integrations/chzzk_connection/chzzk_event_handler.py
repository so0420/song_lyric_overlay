"""jamkubot 릴레이(relay.jamkubot.com) 의 message 이벤트 처리

릴레이는 단일 'message' 이벤트로 평탄한 페이로드를 보낸다(type 으로 분기):
  CHAT     : {type, streamerUid, userName, content, ...}
  DONATION : {type, streamerUid, userName, donationText, payAmount, ...}
채팅/후원 메시지가 '!신청 ...' 이면 노래 신청으로 처리한다.
"""
import re

from app.utils.log import logger
from app.database.streamer_repository import StreamerRepository
from app.database.song_request_repository import SongRequestRepository
from app.database.songbook_repository import SONGBOOK_ARTIST_EXPR, SONGBOOK_TITLE_EXPR
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.mariadb import db_handler
from app.core.song_request_push import broadcast_new_request
from app.integrations.itunes_search import search_itunes

_COMMAND = "!신청"

# 관련성 판정: 정규화(공백/특수문자 제거, 소문자) 후 최소 글자 수
_MIN_MATCH_LEN = 2
# 비교용 정규화 — 영숫자 + 한글 + 일본어(히라가나/가타카나/한자)만 남긴다
_NORM_RE = re.compile(r"[^0-9a-z가-힣぀-ヿ一-鿿]")


def _norm(s) -> str:
    return _NORM_RE.sub("", (s or "").lower())


def _is_relevant(query: str, *fields) -> bool:
    """정규화한 검색어가 후보 필드(곡명/가수/가사제목)와 서로 포함관계면 관련성 있음.

    - 너무 짧은 검색어(노이즈)는 제외
    - 양방향 포함 허용: 검색어⊂필드(검색어가 결과에 포함) 또는 필드⊂검색어(여분 단어 입력)
    이로써 Meilisearch/iTunes 가 내놓는 '전혀 다른 결과'를 걸러낸다.
    """
    nq = _norm(query)
    if len(nq) < _MIN_MATCH_LEN:
        return False
    for f in fields:
        nf = _norm(f)
        if nf and (nq in nf or nf in nq):
            return True
    return False


class ChzzkEventHandler:
    async def handle_message(self, data: dict):
        """릴레이 message 이벤트 진입점 (type 으로 분기)"""
        if not isinstance(data, dict):
            return
        msg_type = data.get("type")
        try:
            if msg_type == "CHAT":
                await self._handle_chat(data)
            elif msg_type == "DONATION":
                await self._handle_donation(data)
            # SUBSCRIPTION 등은 현재 처리 없음
        except Exception as e:
            logger.error(f"[ChzzkEventHandler] 메시지 처리 에러: {e}")

    async def _handle_chat(self, data: dict):
        streamer_uid = data.get("streamerUid")
        requester = data.get("userName") or "익명"
        content = (data.get("content") or "").strip()
        query = self._extract_request_query(content)
        # 신청(!신청)일 때만 로그를 남긴다
        if streamer_uid and query:
            logger.info(f"[CHAT] [{data.get('streamerName')}|{requester}] {content}")
            await self._process_song_request(streamer_uid, requester, query, "CHAT")

    async def _handle_donation(self, data: dict):
        streamer_uid = data.get("streamerUid")
        requester = data.get("userName") or "익명"
        content = (data.get("donationText") or "").strip()
        pay_amount = int(data.get("payAmount") or 0)
        query = self._extract_request_query(content)
        # 신청(!신청)일 때만 로그를 남긴다
        if streamer_uid and query:
            logger.info(f"[DONATION] [{data.get('streamerName')}|{requester}] {pay_amount}원 {content}")
            await self._process_song_request(streamer_uid, requester, query, "DONATION", pay_amount)

    @staticmethod
    def _extract_request_query(message: str):
        """'!신청 노래제목' 에서 검색어 추출 (명령이 아니면 None)"""
        if not message.startswith(_COMMAND):
            return None
        query = message[len(_COMMAND):].strip()
        return query or None

    async def _process_song_request(
        self, streamer_uid: str, requester_name: str, query: str, requester_type: str, pay_amount: int = 0
    ):
        """채팅/후원 !신청 공통 처리"""
        streamer_repo = StreamerRepository()
        request_repo = SongRequestRepository()

        # 1) 스트리머 조회 + 신청 활성화 여부
        streamer = await streamer_repo.get_by_chzzk_channel_id(streamer_uid)
        if not streamer or not streamer.get("request_enabled"):
            return
        if requester_type == "CHAT" and not streamer.get("request_chat_enabled"):
            return
        if requester_type == "DONATION" and not streamer.get("request_donation_enabled"):
            return

        # 2) 후원 신청이면 가격 검증 (스트리머 기본 가격 기준)
        if requester_type == "DONATION":
            required_price = streamer.get("default_price_cheese") or 0
            if pay_amount < required_price:
                logger.info(
                    f"[ChzzkEventHandler] 후원 금액 부족: {requester_name} "
                    f"(보냄:{pay_amount} / 필요:{required_price})"
                )
                return

        common = dict(
            streamer_id=streamer["id"], requester=requester_name,
            requester_type=requester_type, requester_platform="Chzzk",
        )

        # 3) 신청곡 결정 — 단계별 폴백
        # ① 노래책 매칭(Meilisearch 제목/가수 + 가사제목, 관련성 필터)
        target = await self._match_songbook_song(streamer["id"], query)
        if target:
            request_id = await request_repo.add_request(
                **common, song_id=target["song_id"],
                title=target["title"], artist=target.get("artist_name") or "",
            )
            logger.info(f"[ChzzkEventHandler] 신청 성공(노래책): {target['title']} - {requester_name}")
        else:
            # ② iTunes 검색 — 관련성 통과 시 정확한 곡명/가수로 보강
            itunes = await self._itunes_fallback(query)
            if itunes:
                request_id = await request_repo.add_request(
                    **common, title=itunes["title"], artist=itunes["artist"],
                )
                logger.info(f"[ChzzkEventHandler] 신청 성공(iTunes): {itunes['title']} - {requester_name}")
            else:
                # ③ 임시 — 신청자가 입력한 곡명 그대로 (DB 등록 없음)
                request_id = await request_repo.add_request(**common, title=query, artist="")
                logger.info(f"[ChzzkEventHandler] 신청 성공(임시): {query} - {requester_name}")

        # 4) 노래하기 페이지로 푸시 (웹 신청과 동일 — 자동 재생목록 등록)
        row = await request_repo.get_request_push_data(request_id)
        if row:
            await broadcast_new_request(
                streamer["user_id"], row, auto_playlist=bool(streamer.get("request_auto_playlist"))
            )

    async def _match_songbook_song(self, streamer_internal_id: int, query: str):
        """노래책에서 신청곡 매칭 (없으면 None).

        Meilisearch(곡 제목/가수 퍼지) 후보 + 노래책의 곡제목/가수/연결 가사제목 DB 검색을
        합쳐 후보를 만들고, 관련성 필터로 '전혀 다른 결과'를 배제한다.

        노래책 주인이 수록곡 표기를 덮어썼으면(streamer_songbooks.custom_title/artist)
        그 표기로도 찾을 수 있어야 한다 — 시청자가 공개 노래책에서 보는 이름이 그것이다.
        Meilisearch 색인은 전체 곡(원곡 표기)이라 덮어쓴 이름을 모르므로, 그쪽은
        DB LIKE 조건이 받아준다. 원곡 표기로도 계속 찾을 수 있게 조건을 '더한다'.
        """
        # Meilisearch 퍼지 후보 (문서 id = song_external_id)
        meili_ext_ids = []
        try:
            result = await meilisearch_handler.search(
                query, attributes_to_search_on=["title", "singer"], limit=10
            )
            hits = result.get("hits", []) if isinstance(result, dict) else []
            meili_ext_ids = [str(h["id"]) for h in hits if h.get("id") is not None]
        except Exception:
            pass

        like = f"%{query}%"
        nospace = f"%{query.replace(' ', '')}%"
        # custom_* 는 NULL 이면 LIKE 결과도 NULL 이라 자연히 매칭에서 빠진다
        conds = [
            "s.title LIKE %s", "a.name LIKE %s", "l.title LIKE %s",
            "REPLACE(s.title, ' ', '') LIKE %s", "REPLACE(l.title, ' ', '') LIKE %s",
            "sb.custom_title LIKE %s", "sb.custom_artist LIKE %s",
            "REPLACE(sb.custom_title, ' ', '') LIKE %s",
        ]
        params = [streamer_internal_id, like, like, like, nospace, nospace, like, like, nospace]
        if meili_ext_ids:
            placeholders = ", ".join(["%s"] * len(meili_ext_ids))
            conds.append(f"s.song_external_id IN ({placeholders})")
            params.extend(meili_ext_ids)

        # 제목/가수는 '이 노래책에서 보이는 표기'로 돌려준다 — 신청 목록·노래하기에
        # 시청자가 부른 이름 그대로 남는다. 관련성 판정에는 원곡 표기도 함께 쓴다.
        sql = f"""
            SELECT sb.song_id, s.song_external_id,
                   {SONGBOOK_TITLE_EXPR} AS title,
                   {SONGBOOK_ARTIST_EXPR} AS artist_name,
                   s.title AS original_title, a.name AS original_artist_name,
                   l.title AS lyrics_title
            FROM streamer_songbooks sb
            JOIN songs s ON sb.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            LEFT JOIN song_lyrics l ON sb.lyrics_id = l.id AND l.deleted_at IS NULL
            WHERE sb.streamer_id = %s AND ({' OR '.join(conds)})
            LIMIT 30
        """
        candidates = await db_handler.fetch_all(sql, tuple(params))
        if not candidates:
            return None

        # 관련성 필터 + Meilisearch 매칭곡 우선
        relevant = [
            c for c in candidates
            if _is_relevant(
                query, c.get("title"), c.get("artist_name"),
                c.get("original_title"), c.get("original_artist_name"), c.get("lyrics_title"),
            )
        ]
        if not relevant:
            return None
        meili_set = set(meili_ext_ids)
        relevant.sort(key=lambda c: 0 if c.get("song_external_id") in meili_set else 1)
        return relevant[0]

    async def _itunes_fallback(self, query: str):
        """노래책에 없을 때 iTunes 검색으로 정확한 곡명/가수 보강 (관련성 없으면 None)."""
        try:
            results = await search_itunes(term=query, limit=10)
        except Exception:
            return None
        if not results:
            return None
        for r in results:
            if _is_relevant(query, r.get("track_name"), r.get("artist_name")):
                return {"title": r.get("track_name") or query, "artist": r.get("artist_name") or ""}
        return None


# 싱글톤 인스턴스
chzzk_event_handler = ChzzkEventHandler()
