"""jamkubot 릴레이(relay.jamkubot.com) 의 message 이벤트 처리

릴레이는 단일 'message' 이벤트로 평탄한 페이로드를 보낸다(type 으로 분기):
  CHAT     : {type, streamerUid, userName, content, ...}
  DONATION : {type, streamerUid, userName, donationText, payAmount, ...}
채팅/후원 메시지가 '!신청 ...' 이면 노래 신청으로 처리한다.
"""
from app.utils.log import logger
from app.database.streamer_repository import StreamerRepository
from app.database.song_request_repository import SongRequestRepository
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.mariadb import db_handler
from app.core.song_request_push import broadcast_new_request

_COMMAND = "!신청"


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
        logger.info(f"[CHAT] [{data.get('streamerName')}|{requester}] {content}")
        query = self._extract_request_query(content)
        if streamer_uid and query:
            await self._process_song_request(streamer_uid, requester, query, "CHAT")

    async def _handle_donation(self, data: dict):
        streamer_uid = data.get("streamerUid")
        requester = data.get("userName") or "익명"
        content = (data.get("donationText") or "").strip()
        pay_amount = int(data.get("payAmount") or 0)
        logger.info(f"[DONATION] [{data.get('streamerName')}|{requester}] {pay_amount}원 {content}")
        query = self._extract_request_query(content)
        if streamer_uid and query:
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

        # 2) Meilisearch 로 노래책 수록곡 매칭
        target_song = await self._match_songbook_song(streamer["id"], query)

        # 3) 후원 신청이면 가격 검증 (스트리머 기본 가격 기준)
        if requester_type == "DONATION":
            required_price = streamer.get("default_price_cheese") or 0
            if pay_amount < required_price:
                logger.info(
                    f"[ChzzkEventHandler] 후원 금액 부족: {requester_name} "
                    f"(보냄:{pay_amount} / 필요:{required_price})"
                )
                return

        # 4) 신청 등록
        if target_song:
            request_id = await request_repo.add_request(
                streamer_id=streamer["id"],
                requester=requester_name,
                requester_type=requester_type,
                requester_platform="Chzzk",
                song_id=target_song["song_id"],
                title=target_song["title"],
                artist=target_song.get("artist_name") or "",
            )
            logger.info(f"[ChzzkEventHandler] 신청 성공(매칭): {target_song['title']} - {requester_name}")
        else:
            request_id = await request_repo.add_request(
                streamer_id=streamer["id"],
                requester=requester_name,
                requester_type=requester_type,
                requester_platform="Chzzk",
                title=query,
                artist="",
            )
            logger.info(f"[ChzzkEventHandler] 신청 성공(수동): {query} - {requester_name}")

        # 5) 노래하기 페이지로 푸시 (웹 신청과 동일 — 자동 재생목록 등록)
        row = await request_repo.get_request_push_data(request_id)
        if row:
            await broadcast_new_request(
                streamer["user_id"], row, auto_playlist=bool(streamer.get("request_auto_playlist"))
            )

    async def _match_songbook_song(self, streamer_internal_id: int, query: str):
        """검색어로 노래책 수록곡 중 첫 매칭 곡을 찾는다 (없으면 None)

        Meilisearch 문서의 id 는 song_external_id(문자열) 이므로 그 값으로 매칭한다.
        """
        try:
            result = await meilisearch_handler.search(
                query, attributes_to_search_on=["title", "singer"], limit=10
            )
        except Exception:
            return None
        hits = result.get("hits", []) if isinstance(result, dict) else []
        ext_ids = [str(h["id"]) for h in hits if h.get("id") is not None]
        if not ext_ids:
            return None

        placeholders = ", ".join(["%s"] * len(ext_ids))
        sql = f"""
            SELECT s.song_external_id, sb.song_id, s.title, a.name AS artist_name
            FROM streamer_songbooks sb
            JOIN songs s ON sb.song_id = s.id
            LEFT JOIN artists a ON s.artist_id = a.id
            WHERE sb.streamer_id = %s AND s.song_external_id IN ({placeholders})
        """
        params = [streamer_internal_id] + ext_ids
        matched = await db_handler.fetch_all(sql, tuple(params))
        matched_map = {m["song_external_id"]: m for m in matched}
        for h in hits:  # Meilisearch 관련도 순서 유지
            ext = str(h.get("id"))
            if ext in matched_map:
                return matched_map[ext]
        return None


# 싱글톤 인스턴스
chzzk_event_handler = ChzzkEventHandler()
