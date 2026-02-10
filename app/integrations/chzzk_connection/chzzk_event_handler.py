import json
from app.utils.log import logger
from app.integrations.chzzk_connection.chzzk_event_schema import Chat, Donation, Subscription
from app.database.streamer_repository import StreamerRepository
from app.database.song_request_repository import SongRequestRepository
from app.database.meilisearch.meilisearch import meilisearch_handler
from app.database.mariadb import db_handler

class ChzzkEventHandler:
    """
    치지직 이벤트를 처리하는 핸들러 클래스
    """

    def _parse_json(self, data: dict) -> dict:
        """
        JSON 데이터 파싱 (data 필드가 문자열 JSON인 경우 처리)
        """
        try:
            if "data" in data and isinstance(data["data"], str):
                data["data"] = json.loads(data["data"])
        except json.JSONDecodeError:
            logger.error(f"[ChzzkEventHandler] JSON 파싱 실패: {data}")
        return data

    async def handle_chat(self, raw_data: dict):
        """
        채팅 이벤트 처리
        """
        data = self._parse_json(raw_data)
        try:
            chat_msg: Chat = Chat(**data)
            message = chat_msg.user_message.strip()
            
            # !신청 명령어 처리 (채팅은 무료 신청으로 처리)
            if message.startswith("!신청"):
                query = message[3:].strip()
                if query:
                    await self._process_song_request(
                        streamer_uid=chat_msg.streamer_uid,
                        requester_name=chat_msg.user_name,
                        query=query,
                        requester_type='CHAT'
                    )
            
            logger.info(f"[CHAT] [{chat_msg.streamer_name}|{chat_msg.user_name}] {chat_msg.user_message}")
        except Exception as e:
            logger.error(f"[ChzzkEventHandler] 채팅 처리 에러: {e}")

    async def handle_donation(self, raw_data: dict):
        """
        후원 이벤트 처리
        """
        data = self._parse_json(raw_data)
        try:
            donation: Donation = Donation(**data)
            message = donation.user_message.strip()

            # !신청 명령어 처리 (후원 금액 체크 포함)
            if message.startswith("!신청"):
                query = message[3:].strip()
                if query:
                    await self._process_song_request(
                        streamer_uid=donation.streamer_uid,
                        requester_name=donation.user_name or "익명",
                        query=query,
                        requester_type='DONATION',
                        pay_amount=donation.pay_amount
                    )

            logger.info(f"[DONATION] [{donation.streamer_name}|{donation.user_name}|{donation.donation_type}] {donation.pay_amount}원 {donation.user_message}")
        except Exception as e:
            logger.error(f"[ChzzkEventHandler] 후원 처리 에러: {e}")

    async def _process_song_request(self, streamer_uid: str, requester_name: str, query: str, requester_type: str, pay_amount: int = 0):
        """
        노래 신청 명령어 공통 처리 로직 (채팅/후원 공통)
        """
        streamer_repo = StreamerRepository()
        request_repo = SongRequestRepository()

        # 1. 스트리머 조회 및 설정 확인
        streamer = await streamer_repo.get_streamer_by_chzzk_channel_id(streamer_uid)
        if not streamer or not streamer['request_enabled']:
            return

        # 활성화 여부 세부 체크
        if requester_type == 'CHAT' and not streamer['request_chat_enabled']:
            return
        if requester_type == 'DONATION' and not streamer['request_donation_enabled']:
            return

        # 2. Meilisearch 검색
        search_results = await meilisearch_handler.search(query, attributes_to_search_on=["title", "singer"], limit=10)
        
        target_song = None
        if search_results:
            song_ids = [res['id'] for res in search_results]
            placeholders = ', '.join(['%s'] * len(song_ids))
            
            sql = f"""
                SELECT sb.song_id, s.title, a.name as artist_name, sb.price_cheese
                FROM streamer_songbooks sb
                JOIN songs s ON sb.song_id = s.id
                LEFT JOIN artists a ON s.artist_id = a.id
                WHERE sb.streamer_id = %s AND sb.song_id IN ({placeholders})
            """
            params = [streamer['id']] + song_ids
            matched_songs_list = await db_handler.fetch_all(sql, tuple(params))
            matched_songs_map = {int(s['song_id']): s for s in matched_songs_list}
            
            for res in search_results:
                song_id = int(res['id'])
                if song_id in matched_songs_map:
                    target_song = matched_songs_map[song_id]
                    break

        # 3. 가격 검증 (후원 신청일 경우에만)
        if requester_type == 'DONATION':
            required_price = 0
            if target_song:
                # 노래책에 있는 노래: 해당 노래에 설정된 가격 사용
                required_price = target_song.get('price_cheese') or 0
            else:
                # 노래책에 없는 노래: 스트리머 기본 설정 가격 사용
                required_price = streamer.get('default_price_cheese') or 0
            
            if pay_amount < required_price:
                logger.info(f"[ChzzkEventHandler] 후원 금액 부족: {requester_name} (보냄:{pay_amount} / 필요:{required_price})")
                return

        # 4. 신청곡 목록에 추가
        if target_song:
            await request_repo.add_request(
                streamer_id=streamer['id'],
                requester=requester_name,
                requester_type=requester_type,
                requester_platform='Chzzk',
                song_id=target_song['song_id'],
                title=target_song['title'],
                artist=target_song['artist_name'] or ''
            )
            logger.info(f"[ChzzkEventHandler] 노래 신청 성공 (매칭): {target_song['title']} - {requester_name} ({requester_type})")
        else:
            await request_repo.add_request(
                streamer_id=streamer['id'],
                requester=requester_name,
                requester_type=requester_type,
                requester_platform='Chzzk',
                title=query,
                artist=''
            )
            logger.info(f"[ChzzkEventHandler] 노래 신청 성공 (수동): {query} - {requester_name} ({requester_type})")

    async def handle_subscription(self, raw_data: dict):
        """
        구독 이벤트 처리
        """
        data = self._parse_json(raw_data)
        try:
            data: Subscription = Subscription(**data)
            logger.info(f"[SUBSCRIPTION] [{data.streamer_name}|{data.user_name}] {data.tier_name} {data.month}개월")
        except Exception as e:
            logger.error(f"[ChzzkEventHandler] 구독 처리 에러: {e}")

    async def handle_status(self, raw_data: dict):
        """
        상태 이벤트 처리
        """
        # 현재는 별도 처리 없이 통과
        pass

    async def handle_client_activity(self, raw_data: dict):
        """
        클라이언트 활동 이벤트 처리
        """
        logger.info(f"[CLIENT_ACTIVITY] {raw_data}")

# 싱글톤 인스턴스
chzzk_event_handler = ChzzkEventHandler()
