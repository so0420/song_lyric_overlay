"""
노래책/노래신청 기능 단위 테스트 (명세 10절)

자체 완결 테스트 — conftest.py 의존 없이 파일 안에서 픽스처/헬퍼를 정의한다.
- API 레벨: 라우터만 모은 FastAPI 인스턴스 + dependency_overrides (라이브 DB/Redis 접속 없음, lifespan 미실행)
- 리포지토리 레벨: FakeDB (transaction/session/fetch_one 시뮬레이션) 로 쿼리/파라미터 검증
"""
import pytest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI

from app.api.v1.streamers import router as streamers_router
from app.api.v1.songbook import router as songbook_router
from app.api.v1.song_requests import router as song_requests_router
from app.core.auth import get_current_user
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter
from app.database.streamer_repository import get_streamer_repository
from app.database.songbook_repository import get_songbook_repository
from app.database.song_request_repository import SongRequestRepository, get_song_request_repository
from app.database.song_repository import get_song_repository
from app.database.lyrics_repository import get_lyrics_repository


# ===============================================================
# 공통 테스트 데이터
# ===============================================================
APPROVED_USER = {"id": 1, "email": "tester@example.com", "name": "테스트유저", "is_admin": False}
OTHER_USER = {"id": 2, "email": "other@example.com", "name": "다른유저", "is_admin": False}

STREAMER_UUID = "11111111-2222-3333-4444-555555555555"


def make_streamer_row(**over):
    """streamers + users JOIN 결과 형태의 row (repository 가 JSON 파싱까지 끝낸 상태)"""
    row = {
        "id": 10,
        "user_id": 1,
        "streamer_id": STREAMER_UUID,
        "slug": "tester",
        "description": None,
        "social_links": [],
        "tags": [],
        "request_enabled": 1,
        "request_web_enabled": 1,
        "request_auto_playlist": 1,
        "name": "테스트유저",
        "picture": None,
    }
    row.update(over)
    return row


def make_request_row(**over):
    """song_requests 조회(_REQUEST_SELECT) 결과 형태의 row"""
    row = {
        "id": 123,
        "streamer_id": 10,
        "requester": "시청자",
        "requester_type": "WEB",
        "requester_platform": "Web",
        "sort_order": 1,
        "status": "waiting",
        "song_id": 45,
        "title": None,
        "artist": None,
        "delivered_at": None,
        "ref_song_title": "노래제목",
        "song_external_id": "custom_it_1",
        "ref_artist_name": "가수",
        "ref_song_cover": None,
        "sb_mr_video_id": "sbvid",
        "ref_lyrics_id": 67,
        "ref_lyrics_title": "정식 싱크",
        "lyrics_mr_video_id": "lyrvid",
        "is_in_songbook": 1,
    }
    row.update(over)
    return row


def make_entry_row(**over):
    """streamer_songbooks.get_entry 결과 형태의 row (소유권 검증용 user_id 포함)"""
    row = {
        "id": 5,
        "streamer_id": 10,
        "sort_order": 1,
        "song_id": 45,
        "mr_youtube_video_id": None,
        "lyrics_id": None,
        "cover_image_url": None,
        "tags": [],
        "difficulty": 5,
        "memo": None,
        "user_id": 1,
    }
    row.update(over)
    return row


# ===============================================================
# 픽스처 / 헬퍼
# ===============================================================
@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """slowapi 한도 검사 비활성화 (검사 키 함수가 세션 미들웨어를 요구하므로)"""
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


def make_repos():
    """엔드포인트에 주입할 리포지토리 mock 묶음"""
    repos = SimpleNamespace(
        streamer=AsyncMock(),
        songbook=AsyncMock(),
        request=AsyncMock(),
        song=AsyncMock(),
        lyrics=AsyncMock(),
    )
    # 신청 폭주 상한/소유권 검사 기본값 (해피패스: 대기 0건, 소유권 있음)
    repos.request.count_waiting.return_value = 0
    repos.request.belongs_to.return_value = True
    return repos


def build_app(repos, user):
    """노래책 관련 라우터만 모은 경량 FastAPI 앱 (lifespan 없음 → 라이브 DB 접속 없음)"""
    app = FastAPI()
    app.include_router(streamers_router, prefix="/api/v1/streamers")
    app.include_router(songbook_router, prefix="/api/v1/songbook")
    app.include_router(song_requests_router, prefix="/api/v1/song-requests")

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[verify_csrf] = lambda: True
    app.dependency_overrides[get_streamer_repository] = lambda: repos.streamer
    app.dependency_overrides[get_songbook_repository] = lambda: repos.songbook
    app.dependency_overrides[get_song_request_repository] = lambda: repos.request
    app.dependency_overrides[get_song_repository] = lambda: repos.song
    app.dependency_overrides[get_lyrics_repository] = lambda: repos.lyrics
    return app


@asynccontextmanager
async def api_client(repos, user=None, approved=True):
    """ASGITransport 기반 비동기 클라이언트 (승인 여부는 access repo mock 으로 제어)"""
    app = build_app(repos, user)
    mock_access_repo = MagicMock()
    mock_access_repo.is_user_approved = AsyncMock(return_value=approved)
    # require_approved_user / GET /me 는 streamers 모듈 전역의 팩토리를 직접 호출한다
    with patch("app.api.v1.streamers.get_access_request_repository", return_value=mock_access_repo):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


# ===============================================================
# 리포지토리 레벨 Fake DB
# ===============================================================
def _norm(query: str) -> str:
    return " ".join(query.split())


class FakeTx:
    """db_handler.transaction() 이 yield 하는 TransactionContext 대역"""

    def __init__(self, fetch_one_results=None, lastrowid=1):
        self.calls = []  # (kind, query, params)
        self._fetch_one_results = list(fetch_one_results or [])
        self.lastrowid = lastrowid

    async def execute_query(self, query, params=None):
        self.calls.append(("execute", _norm(query), params))
        return self.lastrowid

    async def fetch_one(self, query, params=None):
        self.calls.append(("fetch_one", _norm(query), params))
        if self._fetch_one_results:
            return self._fetch_one_results.pop(0)
        return None

    def executed(self):
        return [c for c in self.calls if c[0] == "execute"]


class FakeCursor:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, query, params=None):
        self._db.executed.append((_norm(query), params))

    @property
    def rowcount(self):
        return self._db.rowcount


class FakeConn:
    def __init__(self, db):
        self._db = db

    def cursor(self):
        return FakeCursor(self._db)


class FakeDB:
    """MariaDBHandler 대역: transaction/session/fetch_one 만 시뮬레이션"""

    def __init__(self, tx_fetch_one=None, fetch_one_results=None, rowcount=1, lastrowid=1):
        self.tx = FakeTx(tx_fetch_one, lastrowid)
        self.rowcount = rowcount
        self.executed = []      # session 경유 (query, params)
        self.fetch_calls = []   # 직접 fetch_one 호출 (query, params)
        self._fetch_one_results = list(fetch_one_results or [])
        self.tx_entered = 0

    @asynccontextmanager
    async def transaction(self):
        self.tx_entered += 1
        yield self.tx

    @asynccontextmanager
    async def session(self):
        yield FakeConn(self)

    async def fetch_one(self, query, params=None):
        self.fetch_calls.append((_norm(query), params))
        if self._fetch_one_results:
            return self._fetch_one_results.pop(0)
        return None


# ===============================================================
# 1. 승인 게이트 (require_approved_user) + 프로필 생성
# ===============================================================
class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_create_profile_unapproved_403(self):
        """미승인 유저의 프로필 생성 → 403"""
        repos = make_repos()
        async with api_client(repos, user=APPROVED_USER, approved=False) as client:
            response = await client.post("/api/v1/streamers/")

        assert response.status_code == 403
        assert "승인" in response.json()["detail"]
        repos.streamer.create_profile.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_profile_unauthenticated_401(self):
        """비로그인 프로필 생성 → 401"""
        repos = make_repos()
        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/streamers/")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unapproved_songbook_add_403(self):
        """미승인 유저의 노래책 곡 추가 → 403 (songbook 라우터에도 동일 게이트)"""
        repos = make_repos()
        async with api_client(repos, user=APPROVED_USER, approved=False) as client:
            response = await client.post("/api/v1/songbook/", json={"song_external_id": "custom_it_1"})

        assert response.status_code == 403
        repos.songbook.add_song.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_profile_success(self):
        """승인 유저 프로필 생성 → 200 + slug 는 이름 기반 자동 생성"""
        repos = make_repos()
        profile = make_streamer_row()
        repos.streamer.get_by_user_id.side_effect = [None, profile]  # 생성 전 조회 → 생성 후 재조회
        repos.streamer.is_slug_taken.return_value = False
        repos.streamer.create_profile.return_value = 10

        async with api_client(repos, user=APPROVED_USER, approved=True) as client:
            response = await client.post("/api/v1/streamers/")

        assert response.status_code == 200
        data = response.json()
        assert data["has_profile"] is True
        assert data["approved"] is True
        assert data["profile"]["id"] == STREAMER_UUID  # 외부 UUID 노출 (내부 id 미노출)
        repos.streamer.create_profile.assert_awaited_once_with(1, "테스트유저")

    @pytest.mark.asyncio
    async def test_create_profile_duplicate_400(self):
        """이미 프로필이 있으면 400"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()

        async with api_client(repos, user=APPROVED_USER, approved=True) as client:
            response = await client.post("/api/v1/streamers/")

        assert response.status_code == 400
        repos.streamer.create_profile.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_profile_slug_conflict_suffix(self):
        """slug 중복 시 -2, -3 suffix 자동 부여"""
        repos = make_repos()
        repos.streamer.get_by_user_id.side_effect = [None, make_streamer_row(slug="테스트유저-2")]
        repos.streamer.is_slug_taken.side_effect = [True, False]
        repos.streamer.create_profile.return_value = 10

        async with api_client(repos, user=APPROVED_USER, approved=True) as client:
            response = await client.post("/api/v1/streamers/")

        assert response.status_code == 200
        repos.streamer.create_profile.assert_awaited_once_with(1, "테스트유저-2")


# ===============================================================
# 2. 노래책 수록곡 소유권 / 검증
# ===============================================================
class TestSongbookOwnership:
    @pytest.mark.asyncio
    async def test_patch_other_users_entry_404(self):
        """타인 소유 entry PATCH → 404 (존재 여부 비노출)"""
        repos = make_repos()
        repos.songbook.get_entry.return_value = make_entry_row(user_id=999)

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/songbook/5", json={"difficulty": 3})

        assert response.status_code == 404
        repos.songbook.update_entry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_other_users_entry_404(self):
        """타인 소유 entry DELETE → 404"""
        repos = make_repos()
        repos.songbook.get_entry.return_value = make_entry_row(user_id=999)

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.delete("/api/v1/songbook/5")

        assert response.status_code == 404
        repos.songbook.remove_entry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_patch_nonexistent_entry_404(self):
        """없는 entry PATCH → 404"""
        repos = make_repos()
        repos.songbook.get_entry.return_value = None

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/songbook/9999", json={"difficulty": 3})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_patch_own_entry_success(self):
        """본인 entry PATCH → 전달된 필드만 update_entry 로 전달"""
        repos = make_repos()
        repos.songbook.get_entry.return_value = make_entry_row(user_id=1)
        repos.songbook.update_entry.return_value = True

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/songbook/5", json={"difficulty": 3, "memo": "쉬움"})

        assert response.status_code == 200
        assert response.json()["success"] is True
        repos.songbook.update_entry.assert_awaited_once_with(5, difficulty=3, memo="쉬움")

    @pytest.mark.asyncio
    async def test_patch_entry_unlink_lyrics(self):
        """lyrics_id 를 0 으로 명시하면 연결 해제 (NULL 저장)"""
        repos = make_repos()
        repos.songbook.get_entry.return_value = make_entry_row(user_id=1, lyrics_id=67)
        repos.songbook.update_entry.return_value = True

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/songbook/5", json={"lyrics_id": 0})

        assert response.status_code == 200
        repos.songbook.update_entry.assert_awaited_once_with(5, lyrics_id=None)
        repos.lyrics.get_lyrics_by_id.assert_not_awaited()  # 해제 시 가사 검증 불필요

    @pytest.mark.asyncio
    async def test_add_entry_without_profile_403(self):
        """프로필 없이 곡 추가 → 403"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = None

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post("/api/v1/songbook/", json={"song_external_id": "custom_it_1"})

        assert response.status_code == 403
        repos.songbook.add_song.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_entry_song_not_found_404(self):
        """DB 에 없는 곡 추가 → 404"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.song.get_song_by_external_id.return_value = None

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post("/api/v1/songbook/", json={"song_external_id": "custom_it_404"})

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_entry_lyrics_song_mismatch_400(self):
        """다른 곡의 가사를 연결하려 하면 400"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.song.get_song_by_external_id.return_value = {"id": 45, "title": "노래제목"}
        # 가사는 존재하지만 song_id 가 다른 곡
        repos.lyrics.get_lyrics_by_id.return_value = {
            "id": 67, "song_id": 999, "visibility": "public", "owner_id": 1,
        }

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post(
                "/api/v1/songbook/",
                json={"song_external_id": "custom_it_1", "lyrics_id": 67},
            )

        assert response.status_code == 400
        repos.songbook.add_song.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_entry_success(self):
        """정상 추가 → entry_id 반환 + add_song 파라미터 검증"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.song.get_song_by_external_id.return_value = {"id": 45, "title": "노래제목"}
        repos.songbook.add_song.return_value = 77

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post(
                "/api/v1/songbook/",
                json={"song_external_id": "custom_it_1", "difficulty": 7, "tags": ["발라드"]},
            )

        assert response.status_code == 200
        assert response.json()["entry_id"] == 77
        repos.songbook.add_song.assert_awaited_once_with(
            streamer_id=10, song_id=45, lyrics_id=None, mr_youtube_video_id=None,
            tags=["발라드"], difficulty=7, memo=None, cover_image_url=None,
        )


# ===============================================================
# 3. 노래 신청 검증 (POST /song-requests/)
# ===============================================================
class TestSongRequestCreate:
    @pytest.mark.asyncio
    async def test_streamer_not_found_404(self):
        """미승인/탈퇴 스트리머(공개 비노출) → 404"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = None

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자", "title": "곡",
            })

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_web_request_disabled_403(self):
        """request_web_enabled=0 → 403"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row(request_web_enabled=0)

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자", "title": "곡",
            })

        assert response.status_code == 403
        assert "신청을 받지 않고" in response.json()["detail"]
        repos.request.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_web_request_master_switch_off_403(self):
        """request_enabled=0 이면 web_enabled=1 이어도 403 (AND 조건)"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row(
            request_enabled=0, request_web_enabled=1,
        )

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자", "title": "곡",
            })

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_manual_request_by_anonymous_403(self):
        """MANUAL 신청을 익명이 → 403"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "스트리머",
                "requester_type": "MANUAL", "title": "곡",
            })

        assert response.status_code == 403
        repos.request.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_request_by_non_owner_403(self):
        """MANUAL 신청을 비소유자(타 유저)가 → 403"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row(user_id=1)

        async with api_client(repos, user=OTHER_USER) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "스트리머",
                "requester_type": "MANUAL", "title": "곡",
            })

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_manual_request_by_owner_bypasses_web_gate(self):
        """MANUAL 은 소유자 본인이면 신청 기능이 꺼져 있어도 허용 + 중복 검사 생략"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row(
            request_enabled=0, request_web_enabled=0,
        )
        repos.request.add_request.return_value = 123
        repos.request.get_request_push_data.return_value = make_request_row(requester_type="MANUAL")

        with patch("app.api.v1.song_requests.overlay_manager.broadcast_to_singers", new_callable=AsyncMock):
            async with api_client(repos, user=APPROVED_USER) as client:
                response = await client.post("/api/v1/song-requests/", json={
                    "streamer_id": STREAMER_UUID, "requester": "스트리머",
                    "requester_type": "MANUAL", "title": "곡",
                })

        assert response.status_code == 200
        repos.request.has_waiting_duplicate.assert_not_awaited()
        assert repos.request.add_request.await_args.kwargs["requester_type"] == "MANUAL"

    @pytest.mark.asyncio
    async def test_missing_song_id_and_title_400(self):
        """song_id 와 title 둘 다 없으면 400"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자",
            })

        assert response.status_code == 400
        repos.request.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_song_id_400(self):
        """존재하지 않는 song_id 신청 → 400"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()
        repos.song.get_song_with_artist.return_value = None

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자", "song_id": 9999,
            })

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_waiting_duplicate_400(self):
        """동일 신청자의 대기 중(waiting) 중복 신청 → 400"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()
        repos.song.get_song_with_artist.return_value = {"id": 45, "title": "노래제목"}
        repos.request.has_waiting_duplicate.return_value = True

        async with api_client(repos, user=None) as client:
            response = await client.post("/api/v1/song-requests/", json={
                "streamer_id": STREAMER_UUID, "requester": "시청자", "song_id": 45,
            })

        assert response.status_code == 400
        assert "대기 중" in response.json()["detail"]
        repos.request.add_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_web_request_success_pushes_ws(self):
        """정상 신청 → 200 + broadcast_to_singers 호출 + 푸시 데이터 계약(명세 7절) 검증"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()
        repos.song.get_song_with_artist.return_value = {"id": 45, "title": "노래제목"}
        repos.request.has_waiting_duplicate.return_value = False
        repos.request.add_request.return_value = 123
        repos.request.get_request_push_data.return_value = make_request_row()

        with patch(
            "app.api.v1.song_requests.overlay_manager.broadcast_to_singers",
            new_callable=AsyncMock,
        ) as mock_broadcast:
            async with api_client(repos, user=None) as client:
                response = await client.post("/api/v1/song-requests/", json={
                    "streamer_id": STREAMER_UUID, "requester": "시청자", "song_id": 45,
                })

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["request_id"] == 123

        mock_broadcast.assert_awaited_once()
        target_user_id, message = mock_broadcast.await_args.args
        assert target_user_id == 1  # 스트리머의 user_id 로 푸시
        assert message["type"] == "song_request_new"
        data = message["data"]
        assert data["request_id"] == 123
        assert data["title"] == "노래제목"        # ref_song_title 우선
        assert data["artist"] == "가수"
        assert data["lyrics_id"] == 67
        assert data["mr_video_id"] == "sbvid"     # 수록곡 MR 이 가사 MR 보다 우선
        assert data["is_in_songbook"] == 1
        assert data["auto_playlist"] is True

    @pytest.mark.asyncio
    async def test_ws_push_failure_does_not_fail_request(self):
        """WS 푸시 예외는 삼켜지고 신청 자체는 성공해야 한다"""
        repos = make_repos()
        repos.streamer.get_public_by_external_id.return_value = make_streamer_row()
        repos.request.has_waiting_duplicate.return_value = False
        repos.request.add_request.return_value = 124
        repos.request.get_request_push_data.return_value = make_request_row(id=124)

        with patch(
            "app.api.v1.song_requests.overlay_manager.broadcast_to_singers",
            new_callable=AsyncMock,
            side_effect=RuntimeError("WS down"),
        ):
            async with api_client(repos, user=None) as client:
                response = await client.post("/api/v1/song-requests/", json={
                    "streamer_id": STREAMER_UUID, "requester": "시청자", "title": "노래책 외 곡",
                })

        assert response.status_code == 200
        assert response.json()["request_id"] == 124


# ===============================================================
# 4. playlist-pending 필터
# ===============================================================
class TestPlaylistPending:
    @pytest.mark.asyncio
    async def test_unauthenticated_401(self):
        repos = make_repos()
        async with api_client(repos, user=None) as client:
            response = await client.get("/api/v1/song-requests/playlist-pending")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_no_profile_returns_empty(self):
        """프로필 없으면 빈 목록 (404 아님)"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = None

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.get("/api/v1/song-requests/playlist-pending")

        assert response.status_code == 200
        assert response.json() == {"items": []}

    @pytest.mark.asyncio
    async def test_auto_playlist_off_returns_empty(self):
        """request_auto_playlist=0 → 빈 목록 + DB 조회 자체를 생략"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row(request_auto_playlist=0)

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.get("/api/v1/song-requests/playlist-pending")

        assert response.status_code == 200
        assert response.json() == {"items": []}
        repos.request.get_playlist_pending.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_filters_out_items_without_lyrics_and_mr(self):
        """가사도 MR 도 없는 신청은 재생목록 투입 대상에서 제외"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.request.get_playlist_pending.return_value = [
            # 가사만 연결
            make_request_row(id=1, sb_mr_video_id=None, lyrics_mr_video_id=None),
            # MR 만 (가사의 MR fallback)
            make_request_row(id=2, ref_lyrics_id=None, ref_lyrics_title=None,
                             sb_mr_video_id=None, lyrics_mr_video_id="lvid"),
            # 둘 다 없음 → 제외 대상
            make_request_row(id=3, ref_lyrics_id=None, ref_lyrics_title=None,
                             sb_mr_video_id=None, lyrics_mr_video_id=None,
                             song_id=None, ref_song_title=None, title="노래책 외 곡"),
        ]

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.get("/api/v1/song-requests/playlist-pending")

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["request_id"] for item in items] == [1, 2]
        assert items[0]["lyrics_id"] == 67
        assert items[1]["mr_video_id"] == "lvid"  # sb MR 없으면 가사 MR fallback
        repos.request.get_playlist_pending.assert_awaited_once_with(10)


# ===============================================================
# 5. reorder / mark-delivered / 개별 수정 엔드포인트
# ===============================================================
class TestRequestManagementEndpoints:
    @pytest.mark.asyncio
    async def test_reorder_passes_ids_in_order(self):
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.put("/api/v1/song-requests/reorder", json={"ids": [3, 1, 2]})

        assert response.status_code == 200
        repos.request.reorder.assert_awaited_once_with(10, [3, 1, 2])

    @pytest.mark.asyncio
    async def test_reorder_empty_ids_422(self):
        """ids 빈 배열은 스키마(min_length=1)에서 거부"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.put("/api/v1/song-requests/reorder", json={"ids": []})

        assert response.status_code == 422
        repos.request.reorder.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mark_delivered_passes_ids(self):
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post("/api/v1/song-requests/mark-delivered", json={"ids": [1, 2]})

        assert response.status_code == 200
        repos.request.mark_delivered.assert_awaited_once_with(10, [1, 2])

    @pytest.mark.asyncio
    async def test_patch_request_not_owned_404(self):
        """타인 신청/없는 신청(소유권 없음) → 404"""
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.request.belongs_to.return_value = False

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/song-requests/55", json={"status": "done"})

        assert response.status_code == 404
        repos.request.update_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_patch_request_success(self):
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.request.update_request.return_value = 1

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.patch("/api/v1/song-requests/55", json={"status": "done"})

        assert response.status_code == 200
        repos.request.update_request.assert_awaited_once_with(55, 10, status="done")

    @pytest.mark.asyncio
    async def test_next_endpoint_returns_next_id(self):
        repos = make_repos()
        repos.streamer.get_by_user_id.return_value = make_streamer_row()
        repos.request.next_request.return_value = 7

        async with api_client(repos, user=APPROVED_USER) as client:
            response = await client.post("/api/v1/song-requests/next")

        assert response.status_code == 200
        assert response.json() == {"success": True, "next_id": 7}
        repos.request.next_request.assert_awaited_once_with(10)


# ===============================================================
# 6. SongRequestRepository 상태머신 / 쿼리 파라미터 (FakeDB)
# ===============================================================
class TestSongRequestRepositoryStateMachine:
    @pytest.mark.asyncio
    async def test_next_request_promotes_first_waiting(self):
        """next: playing → done, 첫 waiting → playing (트랜잭션 내 쿼리 순서/파라미터)"""
        db = FakeDB(tx_fetch_one=[{"id": 42}])
        repo = SongRequestRepository(db=db)

        result = await repo.next_request(10)

        assert result == 42
        assert db.tx_entered == 1
        executed = db.tx.executed()
        # 1) playing → done
        assert "status = 'done'" in executed[0][1]
        assert "status = 'playing'" in executed[0][1]
        assert executed[0][2] == (10,)
        # 2) 첫 waiting → playing
        assert "status = 'playing'" in executed[1][1]
        assert executed[1][2] == (42,)
        # waiting 후보 조회는 sort_order ASC
        select_call = [c for c in db.tx.calls if c[0] == "fetch_one"][0]
        assert "status = 'waiting'" in select_call[1]
        assert "ORDER BY sort_order ASC" in select_call[1]

    @pytest.mark.asyncio
    async def test_next_request_without_waiting_returns_none(self):
        """대기 곡이 없으면 None — playing → done 만 수행"""
        db = FakeDB(tx_fetch_one=[None])
        repo = SongRequestRepository(db=db)

        result = await repo.next_request(10)

        assert result is None
        assert len(db.tx.executed()) == 1  # done 처리만, playing 승격 UPDATE 없음

    @pytest.mark.asyncio
    async def test_prev_request_restores_last_done(self):
        """prev: playing → waiting, 마지막 done → playing (역방향 상태머신)"""
        db = FakeDB(tx_fetch_one=[{"id": 33}])
        repo = SongRequestRepository(db=db)

        result = await repo.prev_request(10)

        assert result == 33
        executed = db.tx.executed()
        # 1) playing → waiting
        assert "SET status = 'waiting'" in executed[0][1]
        assert executed[0][2] == (10,)
        # 2) 마지막 done → playing
        assert "SET status = 'playing'" in executed[1][1]
        assert executed[1][2] == (33,)
        # done 후보 조회는 sort_order DESC (마지막으로 부른 곡)
        select_call = [c for c in db.tx.calls if c[0] == "fetch_one"][0]
        assert "status = 'done'" in select_call[1]
        assert "ORDER BY sort_order DESC" in select_call[1]

    @pytest.mark.asyncio
    async def test_prev_request_without_done_returns_none(self):
        db = FakeDB(tx_fetch_one=[None])
        repo = SongRequestRepository(db=db)

        result = await repo.prev_request(10)

        assert result is None
        assert len(db.tx.executed()) == 1

    @pytest.mark.asyncio
    async def test_reorder_assigns_sequential_sort_order(self):
        """reorder: 전달 순서대로 sort_order 1..N + streamer_id 소유권 조건"""
        db = FakeDB()
        repo = SongRequestRepository(db=db)

        await repo.reorder(10, [5, 3, 9])

        assert db.tx_entered == 1  # 트랜잭션으로 감싸기
        executed = db.tx.executed()
        assert [c[2] for c in executed] == [(1, 5, 10), (2, 3, 10), (3, 9, 10)]
        for _, query, _ in executed:
            assert "WHERE id = %s AND streamer_id = %s" in query

    @pytest.mark.asyncio
    async def test_reorder_empty_ids_skips_transaction(self):
        db = FakeDB()
        repo = SongRequestRepository(db=db)

        await repo.reorder(10, [])

        assert db.tx_entered == 0

    @pytest.mark.asyncio
    async def test_mark_delivered_builds_in_clause(self):
        """mark_delivered: IN 플레이스홀더 개수 + (streamer_id, *ids) 파라미터"""
        db = FakeDB(rowcount=3)
        repo = SongRequestRepository(db=db)

        affected = await repo.mark_delivered(10, [1, 2, 3])

        assert affected == 3
        query, params = db.executed[0]
        assert "SET delivered_at = NOW()" in query
        assert "id IN (%s, %s, %s)" in query
        assert params == (10, 1, 2, 3)

    @pytest.mark.asyncio
    async def test_mark_delivered_empty_ids_noop(self):
        db = FakeDB()
        repo = SongRequestRepository(db=db)

        affected = await repo.mark_delivered(10, [])

        assert affected == 0
        assert db.executed == []

    @pytest.mark.asyncio
    async def test_has_waiting_duplicate_prefers_song_id(self):
        """song_id 가 있으면 song_id 기준으로 중복 검사"""
        db = FakeDB(fetch_one_results=[{"1": 1}])
        repo = SongRequestRepository(db=db)

        result = await repo.has_waiting_duplicate(10, "닉네임", song_id=45, title="무시될 제목")

        assert result is True
        query, params = db.fetch_calls[0]
        assert "song_id = %s" in query
        assert "status = 'waiting'" in query
        assert params == (10, "닉네임", 45)

    @pytest.mark.asyncio
    async def test_has_waiting_duplicate_falls_back_to_title(self):
        """song_id 가 없으면 title 기준"""
        db = FakeDB(fetch_one_results=[None])
        repo = SongRequestRepository(db=db)

        result = await repo.has_waiting_duplicate(10, "닉네임", song_id=None, title="노래책 외 곡")

        assert result is False
        query, params = db.fetch_calls[0]
        assert "title = %s" in query
        assert params == (10, "닉네임", "노래책 외 곡")

    @pytest.mark.asyncio
    async def test_add_request_assigns_next_sort_order(self):
        """add_request: MAX(sort_order)+1 부여 + lastrowid 반환"""
        db = FakeDB(tx_fetch_one=[{"next_sort": 4}], lastrowid=99)
        repo = SongRequestRepository(db=db)

        request_id = await repo.add_request(
            streamer_id=10, requester="닉", requester_type="WEB",
            requester_platform="Web", song_id=45,
        )

        assert request_id == 99
        insert = db.tx.executed()[0]
        assert "INSERT INTO song_requests" in insert[1]
        assert insert[2] == (10, "닉", "WEB", "Web", 4, 45, None, None)

    @pytest.mark.asyncio
    async def test_update_request_ignores_non_whitelisted_fields(self):
        """update_request: 화이트리스트 외 컬럼은 SQL 에 포함되지 않아야 한다"""
        db = FakeDB(rowcount=1)
        repo = SongRequestRepository(db=db)

        affected = await repo.update_request(7, 10, status="done", requester="해킹시도", delivered_at=None)

        assert affected == 1
        query, params = db.executed[0]
        assert "`status` = %s" in query
        assert "requester" not in query
        assert "delivered_at" not in query
        assert "WHERE id = %s AND streamer_id = %s" in query
        assert params == ("done", 7, 10)

    @pytest.mark.asyncio
    async def test_update_request_no_valid_fields_returns_zero(self):
        """유효 필드가 하나도 없으면 DB 호출 없이 0 반환"""
        db = FakeDB()
        repo = SongRequestRepository(db=db)

        affected = await repo.update_request(7, 10, hacked="x")

        assert affected == 0
        assert db.executed == []

    @pytest.mark.asyncio
    async def test_reset_status_keeps_delivered_at(self):
        """reset_status: 상태만 waiting 으로 — delivered_at 은 건드리지 않는다"""
        db = FakeDB(rowcount=5)
        repo = SongRequestRepository(db=db)

        affected = await repo.reset_status(10)

        assert affected == 5
        query, params = db.executed[0]
        assert "SET status = 'waiting'" in query
        assert "delivered_at" not in query  # 재전달 방지 (명세 2절)
        assert params == (10,)
