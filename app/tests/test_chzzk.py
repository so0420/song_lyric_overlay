"""
치지직(Chzzk) 연동 단위 테스트 (jamkubot 위임 방식) — conftest 의존 없이 자체 완결.

- 통합 API: status / disconnect (채널 매핑)
- OAuth: login 리다이렉트(account-interlock, state 세션 저장) / callback(uid 저장, state 검증)
- 릴레이 이벤트 핸들러: message(CHAT/DONATION) → !신청 처리
- 릴레이 클라이언트: 'all' 1회 구독 + 연동 채널만 처리
- 채널 저장소: 쿼리 검증
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.integrations import router as integrations_router
from app.api.v1.oauth.chzzk_oauth import router as chzzk_oauth_router
from app.core.auth import get_current_user, get_current_user_api
from app.utils.csrf import verify_csrf
from app.database.chzzk_repository import get_chzzk_channel_repository


USER = {"id": 1, "email": "t@example.com", "name": "테스터", "is_admin": False}


def build_app(channel_repo, user):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(integrations_router, prefix="/api/v1/integrations")
    app.include_router(chzzk_oauth_router, prefix="/api/v1/oauth/chzzk")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_api] = lambda: user
    app.dependency_overrides[verify_csrf] = lambda: True
    app.dependency_overrides[get_chzzk_channel_repository] = lambda: channel_repo
    return app


def client_for(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", follow_redirects=False)


# ===============================================================
# 통합 상태 / 연동 해제
# ===============================================================
class TestIntegrationStatus:
    @pytest.mark.asyncio
    async def test_status_connected(self):
        repo = AsyncMock()
        repo.get.return_value = {"channel_id": "uid1", "channel_name": "내채널"}
        app = build_app(repo, USER)
        with patch("app.api.v1.integrations.settings") as s:
            s.chzzk_client_id = "cid"
            s.chzzk_interlock_redirect_uri = "http://jamkubot.com/login/naver"
            async with client_for(app) as c:
                r = await c.get("/api/v1/integrations/chzzk/status")
        assert r.status_code == 200
        body = r.json()
        assert body["is_connected"] is True
        assert body["channel_name"] == "내채널"
        assert body["configured"] is True

    @pytest.mark.asyncio
    async def test_status_not_connected(self):
        repo = AsyncMock()
        repo.get.return_value = None
        app = build_app(repo, USER)
        with patch("app.api.v1.integrations.settings") as s:
            s.chzzk_client_id = "cid"
            s.chzzk_interlock_redirect_uri = "http://jamkubot.com/login/naver"
            async with client_for(app) as c:
                r = await c.get("/api/v1/integrations/chzzk/status")
        assert r.json()["is_connected"] is False

    @pytest.mark.asyncio
    async def test_status_not_configured(self):
        repo = AsyncMock()
        repo.get.return_value = None
        app = build_app(repo, USER)
        with patch("app.api.v1.integrations.settings") as s:
            s.chzzk_client_id = ""
            s.chzzk_interlock_redirect_uri = ""
            async with client_for(app) as c:
                r = await c.get("/api/v1/integrations/chzzk/status")
        assert r.json()["configured"] is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        repo = AsyncMock()
        repo.delete.return_value = 1
        app = build_app(repo, USER)
        async with client_for(app) as c:
            r = await c.request("DELETE", "/api/v1/integrations/chzzk")
        assert r.status_code == 200 and r.json()["success"] is True
        repo.delete.assert_awaited_once_with(USER["id"])


# ===============================================================
# OAuth login / callback (jamkubot 위임)
# ===============================================================
class TestChzzkOAuth:
    @pytest.mark.asyncio
    async def test_login_redirects_to_interlock(self):
        repo = AsyncMock()
        app = build_app(repo, USER)
        with patch("app.api.v1.oauth.chzzk_oauth.settings") as s:
            s.chzzk_client_id = "eb6129e8-app"
            s.chzzk_interlock_redirect_uri = "http://jamkubot.com/login/naver"
            s.chzzk_state_prefix = "jamkusong_"
            async with client_for(app) as c:
                r = await c.get("/api/v1/oauth/chzzk/login?redirect_to=/songbook")
        assert r.status_code in (302, 307)
        loc = r.headers["location"]
        assert "chzzk.naver.com/account-interlock" in loc
        assert "clientId=eb6129e8-app" in loc
        assert "redirectUri=http://jamkubot.com/login/naver" in loc
        assert "state=jamkusong_" in loc

    @pytest.mark.asyncio
    async def test_login_not_configured_503(self):
        repo = AsyncMock()
        app = build_app(repo, USER)
        with patch("app.api.v1.oauth.chzzk_oauth.settings") as s:
            s.chzzk_client_id = ""
            s.chzzk_interlock_redirect_uri = ""
            s.chzzk_state_prefix = "jamkusong_"
            async with client_for(app) as c:
                r = await c.get("/api/v1/oauth/chzzk/login")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_callback_stores_channel_with_valid_state(self):
        repo = AsyncMock()
        app = build_app(repo, USER)
        with patch("app.api.v1.oauth.chzzk_oauth.settings") as s:
            s.chzzk_client_id = "cid"
            s.chzzk_interlock_redirect_uri = "http://jamkubot.com/login/naver"
            s.chzzk_state_prefix = "jamkusong_"
            async with client_for(app) as c:
                # 1) login 으로 state 를 세션에 심고 Location 에서 추출
                r1 = await c.get("/api/v1/oauth/chzzk/login?redirect_to=/songbook")
                loc = r1.headers["location"]
                state = loc.split("state=")[1]
                # 2) 같은 클라이언트(쿠키 유지)로 콜백 호출
                r2 = await c.get(f"/api/v1/oauth/chzzk/callback?uid=chzzkuid1&state={state}")
        assert r2.status_code in (302, 307)
        assert r2.headers["location"] == "/songbook"
        repo.link.assert_awaited_once()
        args = repo.link.await_args.args
        assert args[0] == 1 and args[1] == "chzzkuid1"

    @pytest.mark.asyncio
    async def test_callback_bad_state_400(self):
        repo = AsyncMock()
        app = build_app(repo, USER)
        with patch("app.api.v1.oauth.chzzk_oauth.settings") as s:
            s.chzzk_state_prefix = "jamkusong_"
            async with client_for(app) as c:
                # 세션에 state 없이 호출 → 400
                r = await c.get("/api/v1/oauth/chzzk/callback?uid=x&state=jamkusong_forged")
        assert r.status_code == 400
        repo.link.assert_not_awaited()


# ===============================================================
# 릴레이 이벤트 핸들러 (!신청)
# ===============================================================
def chat_msg(streamer_uid="uid1", nickname="시청자", content="!신청 사랑노래"):
    return {"type": "CHAT", "streamerUid": streamer_uid, "streamerName": "스트리머",
            "userName": nickname, "content": content, "messageTime": 0}


def donation_msg(streamer_uid="uid1", nickname="후원자", content="!신청 사랑노래", pay=1000):
    return {"type": "DONATION", "streamerUid": streamer_uid, "streamerName": "스트리머",
            "userName": nickname, "donationText": content, "payAmount": pay, "donationType": "CHAT"}


def make_streamer(**over):
    row = {"id": 10, "user_id": 1, "request_enabled": 1, "request_chat_enabled": 1,
           "request_donation_enabled": 1, "request_auto_playlist": 1, "default_price_cheese": 0}
    row.update(over)
    return row


@pytest.fixture
def handler_mocks():
    from app.integrations.chzzk_connection import chzzk_event_handler as mod
    streamer_repo = AsyncMock()
    request_repo = AsyncMock()
    request_repo.add_request.return_value = 555
    request_repo.get_request_push_data.return_value = {"id": 555, "requester": "시청자",
                                                       "requester_type": "CHAT", "title": "사랑노래"}
    with patch.object(mod, "StreamerRepository", return_value=streamer_repo), \
         patch.object(mod, "SongRequestRepository", return_value=request_repo), \
         patch.object(mod, "meilisearch_handler") as meili, \
         patch.object(mod, "db_handler") as db, \
         patch.object(mod, "search_itunes", new=AsyncMock(return_value=None)) as itunes, \
         patch.object(mod, "broadcast_new_request", new=AsyncMock()) as push:
        # Meilisearch 문서 id 는 song_external_id(문자열)
        meili.search = AsyncMock(return_value={"hits": [{"id": "custom_42"}]})
        db.fetch_all = AsyncMock(return_value=[
            {"song_external_id": "custom_42", "song_id": 42, "title": "사랑노래",
             "artist_name": "가수", "lyrics_title": None}])
        yield SimpleNamespace(streamer_repo=streamer_repo, request_repo=request_repo,
                              meili=meili, db=db, itunes=itunes, push=push, mod=mod)


class TestEventHandler:
    @pytest.mark.asyncio
    async def test_chat_matched_adds_and_pushes(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        await m.mod.chzzk_event_handler.handle_message(chat_msg())
        m.request_repo.add_request.assert_awaited_once()
        kwargs = m.request_repo.add_request.await_args.kwargs
        assert kwargs["requester_type"] == "CHAT" and kwargs["requester_platform"] == "Chzzk"
        assert kwargs["song_id"] == 42
        m.push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_disabled_globally_noop(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer(request_enabled=0)
        await m.mod.chzzk_event_handler.handle_message(chat_msg())
        m.request_repo.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_chat_chat_disabled_noop(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer(request_chat_enabled=0)
        await m.mod.chzzk_event_handler.handle_message(chat_msg())
        m.request_repo.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_command_ignored(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        await m.mod.chzzk_event_handler.handle_message(chat_msg(content="안녕하세요"))
        m.request_repo.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unmatched_song_manual_title(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        m.meili.search.return_value = {"hits": []}
        m.db.fetch_all.return_value = []  # 노래책 후보 없음
        await m.mod.chzzk_event_handler.handle_message(chat_msg(content="!신청 없는노래"))
        kwargs = m.request_repo.add_request.await_args.kwargs
        assert kwargs.get("song_id") is None and kwargs["title"] == "없는노래"

    @pytest.mark.asyncio
    async def test_match_by_lyrics_title(self, handler_mocks):
        """곡 제목은 영어인데 가사 제목이 한글이면, 한글 신청도 노래책 매칭"""
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        m.meili.search.return_value = {"hits": []}  # Meilisearch(제목/가수)로는 못 찾음
        m.db.fetch_all.return_value = [{
            "song_external_id": "custom_it_1", "song_id": 7,
            "title": "antifreeze", "artist_name": "엘르가든", "lyrics_title": "안티프리즈",
        }]
        await m.mod.chzzk_event_handler.handle_message(chat_msg(content="!신청 안티프리즈"))
        kwargs = m.request_repo.add_request.await_args.kwargs
        assert kwargs.get("song_id") == 7  # 가사제목으로 노래책 매칭 성공
        m.push.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_itunes_fallback_when_not_in_songbook(self, handler_mocks):
        """노래책에 없으면 iTunes 검색으로 정확한 곡명 보강 (관련성 통과 시)"""
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        m.meili.search.return_value = {"hits": []}
        m.db.fetch_all.return_value = []  # 노래책 매칭 없음
        m.itunes.return_value = [{"track_name": "Antifreeze", "artist_name": "Ellegarden"}]
        await m.mod.chzzk_event_handler.handle_message(chat_msg(content="!신청 antifreeze"))
        kwargs = m.request_repo.add_request.await_args.kwargs
        assert kwargs.get("song_id") is None and kwargs["title"] == "Antifreeze"

    @pytest.mark.asyncio
    async def test_itunes_irrelevant_falls_to_temp(self, handler_mocks):
        """iTunes 결과가 신청어와 전혀 다르면 무시하고 임시(입력값) 신청"""
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer()
        m.meili.search.return_value = {"hits": []}
        m.db.fetch_all.return_value = []
        m.itunes.return_value = [{"track_name": "완전히 다른 곡", "artist_name": "다른 가수"}]
        await m.mod.chzzk_event_handler.handle_message(chat_msg(content="!신청 안티프리즈"))
        kwargs = m.request_repo.add_request.await_args.kwargs
        assert kwargs.get("song_id") is None and kwargs["title"] == "안티프리즈"

    @pytest.mark.asyncio
    async def test_donation_insufficient_noop(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer(default_price_cheese=5000)
        await m.mod.chzzk_event_handler.handle_message(donation_msg(pay=1000))
        m.request_repo.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_donation_sufficient_adds(self, handler_mocks):
        m = handler_mocks
        m.streamer_repo.get_by_chzzk_channel_id.return_value = make_streamer(default_price_cheese=1000)
        await m.mod.chzzk_event_handler.handle_message(donation_msg(pay=1000))
        m.request_repo.add_request.assert_awaited_once()
        assert m.request_repo.add_request.await_args.kwargs["requester_type"] == "DONATION"

    @pytest.mark.asyncio
    async def test_unknown_type_ignored(self, handler_mocks):
        m = handler_mocks
        await m.mod.chzzk_event_handler.handle_message({"type": "SUBSCRIPTION", "streamerUid": "uid1"})
        m.request_repo.add_request.assert_not_awaited()


# ===============================================================
# 채널 저장소
# ===============================================================
class TestRelayClient:
    """V3 릴레이는 소켓당 채널 8개·동시 구독 1개라, 마스터 토큰 'all' 한 번만 구독한다."""

    def make(self, channels=("uid1", "uid2")):
        from app.integrations.chzzk_connection import chzzk_connection_client as mod
        c = mod.ChzzkConnectionClient()
        c._channel_repo = AsyncMock()
        c._channel_repo.get_all_channel_ids.return_value = list(channels)
        c.sio.emit = AsyncMock()
        return mod, c

    def handler(self, c, event):
        return c.sio.handlers["/"][event]

    @pytest.mark.asyncio
    async def test_connect_subscribes_all_once(self):
        mod, c = self.make()
        c.sio.connected = True
        with patch.object(mod.settings, "chzzk_relay_token", "tok"):
            await self.handler(c, "connect")()
        c.sio.emit.assert_awaited_once_with("subscribe", {"streamerUid": "all", "token": "tok"})

    @pytest.mark.asyncio
    async def test_only_linked_channels_are_handled(self):
        mod, c = self.make()
        await c._refresh_channels()
        with patch.object(mod, "chzzk_event_handler") as h:
            h.handle_message = AsyncMock()
            on_message = self.handler(c, "message")
            await on_message(chat_msg(streamer_uid="uid1"))
            await on_message(chat_msg(streamer_uid="other"))
            await on_message("garbage")
        h.handle_message.assert_awaited_once()
        assert h.handle_message.await_args.args[0]["streamerUid"] == "uid1"

    @pytest.mark.asyncio
    async def test_subscribed_ack_tracks_state(self):
        _, c = self.make()
        on_subscribed = self.handler(c, "subscribed")
        await on_subscribed({"success": False, "message": "Too many requests."})
        assert c._subscribed is False
        await on_subscribed({"streamerUid": "all", "success": True})
        assert c._subscribed is True
        await self.handler(c, "disconnect")()
        assert c._subscribed is False

    @pytest.mark.asyncio
    async def test_refresh_failure_keeps_previous_channels(self):
        _, c = self.make()
        await c._refresh_channels()
        c._channel_repo.get_all_channel_ids.side_effect = RuntimeError("db down")
        await c._refresh_channels()
        assert c._channels == {"uid1", "uid2"}


class FakeCursor:
    def __init__(self):
        self.rowcount = 1

    async def execute(self, sql, params=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDB:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.queries = []

    async def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        return 1

    async def fetch_one(self, sql, params=None):
        self.queries.append((sql, params))
        return {"channel_id": "uid1", "channel_name": "내채널"}

    async def fetch_all(self, sql, params=None):
        self.queries.append((sql, params))
        return [{"channel_id": "uid1"}, {"channel_id": "uid2"}]

    def session(self):
        return FakeConn(self.cursor_obj)


class TestChannelRepository:
    @pytest.mark.asyncio
    async def test_link_upsert(self):
        from app.database.chzzk_repository import ChzzkChannelRepository
        db = FakeDB()
        repo = ChzzkChannelRepository(db=db)
        await repo.link(1, "uid1", "내채널")
        sql, params = db.queries[-1]
        assert "ON DUPLICATE KEY UPDATE" in sql
        assert params == (1, "uid1", "내채널")

    @pytest.mark.asyncio
    async def test_get_all_channel_ids(self):
        from app.database.chzzk_repository import ChzzkChannelRepository
        db = FakeDB()
        repo = ChzzkChannelRepository(db=db)
        ids = await repo.get_all_channel_ids()
        assert ids == ["uid1", "uid2"]

    @pytest.mark.asyncio
    async def test_delete(self):
        from app.database.chzzk_repository import ChzzkChannelRepository
        db = FakeDB()
        repo = ChzzkChannelRepository(db=db)
        n = await repo.delete(1)
        assert n == 1
