"""업로드 음원 기능 단위 테스트.

자체 완결 테스트 — conftest.py 의존 없이 파일 안에서 픽스처/헬퍼를 정의한다
(test_songbook.py 와 같은 방식).

디스크는 tmp_path 로 갈아끼워서 실제 storage/ 를 절대 건드리지 않는다.
"""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

import app.utils.audio_storage as storage
from app.core.auth import get_current_user, get_current_user_api
from app.database.audio_repository import get_audio_repository
from app.database.lyrics_repository import get_lyrics_repository
from app.utils.audio_sniff import detect_audio_mime
from app.schemas.users import CurrentUserSchema
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter


# ===============================================================
# 공통 테스트 데이터
# ===============================================================
OWNER = {"id": 1, "email": "o@e.com", "name": "소유자", "is_admin": False}
OTHER = {"id": 2, "email": "x@e.com", "name": "타인", "is_admin": False}
ADMIN = {"id": 9, "email": "a@e.com", "name": "관리자", "is_admin": True}

# ID3 헤더 + MPEG 프레임 싱크 (매직바이트 판별이 통과하는 최소 mp3)
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + bytes(range(256)) * 8


def audio_row(**over):
    row = {
        "id": 42,
        "owner_id": 1,
        "storage_path": "aa/bb/testfile.mp3",
        "original_filename": "mr.mp3",
        "mime_type": "audio/mpeg",
        "byte_size": len(MP3_BYTES),
        "sha256": hashlib.sha256(MP3_BYTES).hexdigest(),
        "duration_ms": 213000,
        "created_at": None,
        "deleted_at": None,
    }
    row.update(over)
    return row


def lyric_row(**over):
    row = {
        "id": 5,
        "owner_id": 1,
        "song_id": 3,
        "visibility": "public",
        "audio_file_id": 42,
        "mr_youtube_video_id": None,
        "lyrics_data": "[]",
        "deleted_at": None,
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


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """저장 루트를 임시 디렉터리로 바꿔 실제 storage/ 를 건드리지 않게 한다"""
    monkeypatch.setattr(storage, "AUDIO_ROOT", tmp_path / "audio")
    monkeypatch.setattr(storage, "AUDIO_TMP", tmp_path / "audio" / "tmp")
    yield tmp_path / "audio"


def make_audio_repo(**over):
    repo = AsyncMock()
    repo.find_by_owner_sha256.return_value = None
    repo.create.return_value = 42
    repo.get_by_id.return_value = audio_row()
    repo.total_bytes.return_value = 0
    repo.is_linked.return_value = False
    for k, v in over.items():
        getattr(repo, k).return_value = v
    return repo


def make_lyrics_repo(row=None, whitelisted=False):
    repo = AsyncMock()
    repo.get_lyrics_by_id.return_value = row if row is not None else lyric_row()
    repo.is_whitelisted.return_value = whitelisted
    repo.update_visibility_owned.return_value = True
    return repo


def build_audio_app(audio_repo, user=OWNER):
    from app.api.v1.audio import router as audio_router

    app = FastAPI()
    app.include_router(audio_router, prefix="/api/v1/audio")
    app.dependency_overrides[get_current_user_api] = lambda: CurrentUserSchema(**user)
    app.dependency_overrides[verify_csrf] = lambda: True
    app.dependency_overrides[get_audio_repository] = lambda: audio_repo
    return app


def build_lyrics_app(lyrics_repo, audio_repo, user=OWNER):
    from app.api.v1.lyrics import router as lyrics_router

    app = FastAPI()
    app.include_router(lyrics_router, prefix="/api/v1/lyrics")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_api] = lambda: (
        CurrentUserSchema(**user) if user else None
    )
    app.dependency_overrides[verify_csrf] = lambda: True
    app.dependency_overrides[get_lyrics_repository] = lambda: lyrics_repo
    app.dependency_overrides[get_audio_repository] = lambda: audio_repo
    return app


@asynccontextmanager
async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def place_blob(root, rel="aa/bb/testfile.mp3", data=MP3_BYTES):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ===============================================================
# A. 매직바이트 판별
# ===============================================================
class TestAudioSniff:
    @pytest.mark.parametrize("label,head,expected", [
        ("ID3 mp3", b"ID3\x03\x00\x00\x00" + b"\x00" * 20, "audio/mpeg"),
        ("raw mp3", b"\xff\xfb\x90\x00" + b"\x00" * 20, "audio/mpeg"),
        ("wav", b"RIFF\x24\x08\x00\x00WAVEfmt ", "audio/wav"),
        ("flac", b"fLaC\x00\x00\x00\x22", "audio/flac"),
        ("ogg/opus", b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead\x01\x02", "audio/ogg"),
        ("ogg/vorbis", b"OggS\x00\x02" + b"\x00" * 22 + b"\x01vorbis", "audio/ogg"),
    ])
    def test_detects_allowed_formats(self, label, head, expected):
        assert detect_audio_mime(head) == expected, label

    @pytest.mark.parametrize("label,head", [
        # 영상 트랙을 담을 수 있는 컨테이너는 서버에 디먹서가 없어 거부한다
        ("mp4", b"\x00\x00\x00\x20ftypisom"),
        ("webm", b"\x1aE\xdf\xa3\x01\x00\x00\x00"),
        ("ogg/theora", b"OggS\x00\x02" + b"\x00" * 22 + b"\x80theora"),
        ("gif", b"GIF89a\x00\x00"),
        ("pdf", b"%PDF-1.7\n"),
        ("zip", b"PK\x03\x04\x14\x00\x00\x00"),
        ("empty", b""),
        ("1 byte", b"\xff"),
    ])
    def test_rejects_others(self, label, head):
        assert detect_audio_mime(head) is None, label


# ===============================================================
# B. 업로드
# ===============================================================
class TestUpload:
    @pytest.mark.asyncio
    async def test_happy_path(self, _isolated_storage):
        repo = make_audio_repo()
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=mr.mp3&duration_ms=213000", content=MP3_BYTES)

        assert res.status_code == 200
        kwargs = repo.create.call_args.kwargs
        # 클라이언트 신고값이 아니라 서버가 판별한 형식이 저장돼야 한다
        assert kwargs["mime_type"] == "audio/mpeg"
        assert kwargs["byte_size"] == len(MP3_BYTES)
        assert kwargs["sha256"] == hashlib.sha256(MP3_BYTES).hexdigest()
        blob = storage.resolve_audio_path(kwargs["storage_path"])
        assert blob.exists()
        assert blob.stat().st_mode & 0o777 == 0o640

    @pytest.mark.asyncio
    async def test_ignores_declared_content_type(self):
        """Content-Type 을 audio/mpeg 로 속여도 내용으로 판별해 거부한다"""
        repo = make_audio_repo()
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post(
                "/api/v1/audio?filename=x.mp3",
                content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 200,
                headers={"Content-Type": "audio/mpeg"},
            )
        assert res.status_code == 415
        repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_empty(self):
        repo = make_audio_repo()
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=x.mp3", content=b"")
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_oversize_by_content_length(self):
        """Content-Length 가 정직하게 크면 본문을 읽기 전에 끊는다 (값싼 경로)"""
        repo = make_audio_repo()
        big = b"ID3\x03\x00\x00\x00" + b"\x00" * (storage.MAX_AUDIO_BYTES + 10)
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=x.mp3", content=big)
        assert res.status_code == 413
        repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_oversize_while_streaming(self, _isolated_storage):
        """Content-Length 없이 흘려보내도 읽는 도중에 끊고, .part 를 남기지 않는다.

        UploadFile(멀티파트)로는 이 동작이 불가능하다 — 이 테스트가 그 구현 선택을 지킨다.
        """
        async def gen():
            yield b"ID3\x03\x00\x00\x00\x00\x00\x00"
            for _ in range(storage.MAX_AUDIO_BYTES // (1024 * 1024) + 1):
                yield b"\x00" * (1024 * 1024)

        repo = make_audio_repo()
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=x.mp3", content=gen())

        assert res.status_code == 413
        repo.create.assert_not_awaited()
        assert list(storage.AUDIO_TMP.glob("*.part")) == []

    @pytest.mark.asyncio
    async def test_dedup_same_owner(self, _isolated_storage):
        """같은 사용자가 같은 파일을 다시 올리면 기존 기록을 돌려주고 파일을 더 쓰지 않는다"""
        repo = make_audio_repo()
        repo.find_by_owner_sha256.return_value = audio_row()
        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=mr.mp3", content=MP3_BYTES)

        assert res.status_code == 200
        assert res.json()["id"] == 42
        repo.create.assert_not_awaited()
        assert list(storage.AUDIO_ROOT.rglob("*.mp3")) == []

    @pytest.mark.asyncio
    async def test_db_failure_removes_blob(self, _isolated_storage):
        """DB 기록에 실패하면 아무도 참조하지 못하는 고아 블롭을 남기지 않는다"""
        repo = make_audio_repo()
        repo.create.side_effect = RuntimeError("db down")
        async with client_for(build_audio_app(repo)) as c:
            with pytest.raises(RuntimeError):
                await c.post("/api/v1/audio?filename=mr.mp3", content=MP3_BYTES)

        assert list(storage.AUDIO_ROOT.rglob("*.mp3")) == []
        assert list(storage.AUDIO_TMP.glob("*.part")) == []


# ===============================================================
# C. 재생 (권한 + Range)
# ===============================================================
class TestStreaming:
    URL = "/api/v1/lyrics/5/audio"

    @pytest.mark.asyncio
    async def test_anonymous_denied_even_for_public_lyric(self, _isolated_storage):
        """공개 가사라도 음원 재생에는 로그인이 필요하다 (무료 MP3 배포처가 되지 않도록)"""
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo(), user=None)
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == 401

    @pytest.mark.asyncio
    async def test_private_other_user_denied(self, _isolated_storage):
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(lyric_row(visibility="private")),
                               make_audio_repo(), user=OTHER)
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("user", [OWNER, ADMIN])
    async def test_owner_and_admin_allowed(self, _isolated_storage, user):
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(lyric_row(visibility="private")),
                               make_audio_repo(), user=user)
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == 200
        assert res.content == MP3_BYTES

    @pytest.mark.asyncio
    @pytest.mark.parametrize("whitelisted,expected", [(True, 200), (False, 403)])
    async def test_whitelist(self, _isolated_storage, whitelisted, expected):
        place_blob(_isolated_storage)
        app = build_lyrics_app(
            make_lyrics_repo(lyric_row(visibility="whitelist"), whitelisted=whitelisted),
            make_audio_repo(), user=OTHER,
        )
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == expected

    @pytest.mark.asyncio
    async def test_range_returns_206(self, _isolated_storage):
        """<audio> 탐색이 여기 의존한다. starlette 를 올릴 때 깨지면 이 테스트가 잡는다."""
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        async with client_for(app) as c:
            res = await c.get(self.URL, headers={"Range": "bytes=0-9"})
        assert res.status_code == 206
        assert len(res.content) == 10
        assert res.headers["content-range"] == f"bytes 0-9/{len(MP3_BYTES)}"
        assert res.headers["accept-ranges"] == "bytes"

    @pytest.mark.asyncio
    async def test_unsatisfiable_range_416(self, _isolated_storage):
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        async with client_for(app) as c:
            res = await c.get(self.URL, headers={"Range": "bytes=99999999-"})
        assert res.status_code == 416

    @pytest.mark.asyncio
    async def test_inline_not_attachment(self, _isolated_storage):
        """filename= 을 넘기면 attachment 가 되어 재생 대신 다운로드가 된다 — 그 회귀 방지"""
        place_blob(_isolated_storage)
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert "attachment" not in res.headers.get("content-disposition", "")
        assert res.headers["content-type"] == "audio/mpeg"

    @pytest.mark.asyncio
    async def test_missing_blob_is_404_not_500(self, _isolated_storage):
        """DB 행은 있는데 파일이 없는 저장소 드리프트 — 500 이 아니라 404 로 내린다"""
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_lyric_without_audio_404(self, _isolated_storage):
        app = build_lyrics_app(
            make_lyrics_repo(lyric_row(audio_file_id=None, mr_youtube_video_id="abc")),
            make_audio_repo(),
        )
        async with client_for(app) as c:
            res = await c.get(self.URL)
        assert res.status_code == 404


# ===============================================================
# D. 저장 경로 안전성
# ===============================================================
class TestStoragePaths:
    def test_rejects_traversal(self, _isolated_storage):
        with pytest.raises(ValueError):
            storage.resolve_audio_path("../../etc/passwd")

    def test_rejects_absolute(self, _isolated_storage):
        with pytest.raises(ValueError):
            storage.resolve_audio_path("/etc/passwd")

    def test_new_storage_path_is_fanned_out(self):
        rel = storage.new_storage_path("mp3")
        parts = rel.split("/")
        assert len(parts) == 3 and len(parts[0]) == 2 and len(parts[1]) == 2
        assert rel.endswith(".mp3")


# ===============================================================
# E. 가사 연결
# ===============================================================
class TestLinking:
    @pytest.mark.asyncio
    async def test_requires_exactly_one_source(self):
        """소스가 없거나 둘 다면 422 — 조용히 재생 불가 가사가 만들어지지 않게 한다"""
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        base = {"song_id": 3, "lyrics_data": "[]"}
        async with client_for(app) as c:
            none = await c.post("/api/v1/lyrics/", json=base)
            both = await c.post("/api/v1/lyrics/", json={
                **base, "mr_youtube_video_id": "abc12345678", "audio_file_id": 42})
        assert none.status_code == 422
        assert both.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_other_users_audio(self):
        """남의 음원을 내 가사에 붙이지 못한다 (가장 중요한 인가 검사)"""
        audio_repo = make_audio_repo()
        audio_repo.get_by_id.return_value = audio_row(owner_id=999)
        app = build_lyrics_app(make_lyrics_repo(), audio_repo, user=OWNER)
        async with client_for(app) as c:
            res = await c.post("/api/v1/lyrics/", json={
                "song_id": 3, "lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_deleted_audio(self):
        audio_repo = make_audio_repo()
        audio_repo.get_by_id.return_value = audio_row(deleted_at="2026-01-01")
        app = build_lyrics_app(make_lyrics_repo(), audio_repo)
        async with client_for(app) as c:
            res = await c.post("/api/v1/lyrics/", json={
                "song_id": 3, "lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_audio_linked_lyric_defaults_to_private(self):
        """음원을 붙인 가사는 비공개가 기본 (지금은 비관리자 가사가 무조건 public 이 된다)"""
        lyrics_repo = make_lyrics_repo()
        lyrics_repo.check_title_duplicate.return_value = False
        lyrics_repo.create_lyrics.return_value = 7
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.post("/api/v1/lyrics/", json={
                "song_id": 3, "lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 200
        assert lyrics_repo.create_lyrics.call_args.kwargs["visibility"] == "private"

    @pytest.mark.asyncio
    async def test_youtube_lyric_stays_public(self):
        lyrics_repo = make_lyrics_repo()
        lyrics_repo.check_title_duplicate.return_value = False
        lyrics_repo.create_lyrics.return_value = 7
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.post("/api/v1/lyrics/", json={
                "song_id": 3, "lyrics_data": "[]", "mr_youtube_video_id": "abc12345678"})
        assert res.status_code == 200
        assert lyrics_repo.create_lyrics.call_args.kwargs["visibility"] == "public"

    @pytest.mark.asyncio
    async def test_switching_source_clears_the_old_one(self):
        """유튜브 → 음원으로 바꾸면 옛 video id 가 지워져야 한다 (둘 다 남으면 해석이 흔들린다)"""
        lyrics_repo = make_lyrics_repo()
        lyrics_repo.check_title_duplicate.return_value = False
        lyrics_repo.update_lyrics.return_value = True
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.patch("/api/v1/lyrics/5", json={
                "lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 200
        kwargs = lyrics_repo.update_lyrics.call_args.kwargs
        assert kwargs["audio_file_id"] == 42
        assert kwargs["mr_youtube_video_id"] is None

    @pytest.mark.asyncio
    async def test_detail_exposes_source_fields(self, _isolated_storage):
        app = build_lyrics_app(make_lyrics_repo(), make_audio_repo())
        async with client_for(app) as c:
            body = (await c.get("/api/v1/lyrics/5")).json()
        assert body["mr_source"] == "audio"
        assert body["audio_url"] == "/api/v1/lyrics/5/audio"

    @pytest.mark.asyncio
    async def test_owner_can_change_own_visibility(self):
        """음원 연결 시 private 강제가 일방통행이 되지 않도록 소유자에게 되돌릴 길을 준다"""
        lyrics_repo = make_lyrics_repo()
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.patch("/api/v1/lyrics/5/visibility", json={"visibility": "public"})
        assert res.status_code == 200
        lyrics_repo.update_visibility_owned.assert_awaited_once_with(5, 1, "public")

    @pytest.mark.asyncio
    async def test_visibility_change_on_other_lyric_404(self):
        lyrics_repo = make_lyrics_repo()
        lyrics_repo.update_visibility_owned.return_value = False  # 소유권 조건 미충족
        app = build_lyrics_app(lyrics_repo, make_audio_repo(), user=OTHER)
        async with client_for(app) as c:
            res = await c.patch("/api/v1/lyrics/5/visibility", json={"visibility": "public"})
        assert res.status_code == 404


# ===============================================================
# F. 소스 우선순위 (노래책 override)
# ===============================================================
class TestResolveMrSource:
    def test_priority_order(self):
        from app.core.song_request_push import resolve_mr_source

        # ① 수록곡 음원이 최우선
        assert resolve_mr_source({
            "sb_audio_file_id": 1, "sb_mr_video_id": "v1",
            "lyrics_audio_file_id": 2, "lyrics_mr_video_id": "v2",
        }) == {"type": "audio", "video_id": None, "audio_file_id": 1}

        # ② 수록곡 유튜브가 '가사의 음원'을 이긴다
        #    (스트리머가 명시적으로 지정한 MR 이 무시되면 안 된다)
        assert resolve_mr_source({
            "sb_mr_video_id": "v1", "lyrics_audio_file_id": 2, "lyrics_mr_video_id": "v2",
        }) == {"type": "youtube", "video_id": "v1", "audio_file_id": None}

        # ③ 수록곡 지정이 없으면 가사의 음원
        assert resolve_mr_source({
            "lyrics_audio_file_id": 2, "lyrics_mr_video_id": "v2",
        }) == {"type": "audio", "video_id": None, "audio_file_id": 2}

        # ④ 마지막이 가사의 유튜브
        assert resolve_mr_source({"lyrics_mr_video_id": "v2"}) == {
            "type": "youtube", "video_id": "v2", "audio_file_id": None}

        # 아무 것도 없음
        assert resolve_mr_source({})["type"] is None


class TestSongbookExposure:
    def test_public_entry_hides_audio_id(self):
        """공개 노래책 응답에 음원 id 가 새어나가면 안 된다 (보유 여부만)"""
        from app.api.v1.songbook import _serialize_entry

        out = _serialize_entry({
            "entry_id": 1, "song_id": 2, "song_external_id": "e", "title": "t",
            "audio_file_id": 42, "lyrics_audio_file_id": None,
        })
        assert out["has_audio"] is True
        assert "audio_file_id" not in out

    def test_public_playlist_item_hides_audio(self):
        from app.api.v1.songbook import _serialize_playlist_item

        out = _serialize_playlist_item({
            "songTitle": "t", "sourceType": "audio", "audioId": 42, "videoId": None})
        assert out["source_type"] == "audio"
        assert out["video_id"] == ""
        assert "audioId" not in out and "audio_id" not in out

    def test_update_entry_whitelist_includes_audio(self):
        """화이트리스트에서 빠지면 PATCH 가 200 을 주면서 아무것도 안 바뀐다"""
        import inspect

        from app.database.songbook_repository import SongbookRepository

        src = inspect.getsource(SongbookRepository.update_entry)
        assert '"audio_file_id"' in src


# ===============================================================
# G. 수명 관리
# ===============================================================
class TestPurge:
    @pytest.mark.asyncio
    async def test_purge_one_order(self, _isolated_storage):
        """선점 → 파일 삭제 → 행 삭제 순서여야 한다 (중간에 죽어도 회수 가능하도록)"""
        from app.database import audio_purge

        blob = place_blob(_isolated_storage)
        calls = []
        repo = AsyncMock()
        repo.claim_unlinked_for_purge.side_effect = lambda *a: calls.append("claim") or True
        repo.hard_delete.side_effect = lambda *a: calls.append("delete_row")

        ok = await audio_purge.purge_one(42, "aa/bb/testfile.mp3", repo)

        assert ok is True
        assert calls == ["claim", "delete_row"]
        assert not blob.exists()   # 행 삭제 전에 파일이 지워졌다

    @pytest.mark.asyncio
    async def test_purge_one_skips_when_already_claimed(self, _isolated_storage):
        from app.database import audio_purge

        blob = place_blob(_isolated_storage)
        repo = AsyncMock()
        repo.claim_unlinked_for_purge.return_value = False

        assert await audio_purge.purge_one(42, "aa/bb/testfile.mp3", repo) is False
        assert blob.exists()
        repo.hard_delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_removes_only_old_temp_files(self, _isolated_storage):
        import os
        import time

        from app.database import audio_purge

        storage.ensure_dir(storage.AUDIO_TMP)
        old = storage.AUDIO_TMP / "old.part"
        new = storage.AUDIO_TMP / "new.part"
        old.write_bytes(b"x")
        new.write_bytes(b"x")
        stale = time.time() - audio_purge.TMP_MAX_AGE_SECONDS - 60
        os.utime(old, (stale, stale))

        removed = await audio_purge.sweep_temp_files()

        assert removed == 1
        assert not old.exists() and new.exists()

    def test_account_purge_reads_paths_before_delete(self):
        """행을 지우기 전에 storage_path 를 확보해야 블롭을 지울 수 있다"""
        import inspect

        from app.database import account_purge

        src = inspect.getsource(account_purge.purge_account)
        select_at = src.index("SELECT storage_path")
        delete_at = src.index("DELETE FROM audio_files")
        assert select_at < delete_at
        # 파일 삭제는 트랜잭션 블록 밖(커밋 후)이어야 한다
        assert src.index("unlink") > src.index("_PURGE_USER_SQL")

    def test_audio_files_not_in_purge_tables(self):
        """_PURGE_TABLES 에 넣으면 storage_path 를 잃고 블롭이 전부 샌다"""
        from app.database.account_purge import _PURGE_TABLES

        assert all(t != "audio_files" for t, _ in _PURGE_TABLES)


# ===============================================================
# H. ultracode 검증에서 확정된 결함들의 회귀 방지
# ===============================================================
class TestVerifiedRegressions:
    @pytest.mark.asyncio
    async def test_patch_to_audio_forces_private(self):
        """전체공개 유튜브 가사에 음원만 갈아끼워도 비공개로 내려가야 한다.

        create 에만 private 강제를 두고 update 를 빠뜨리면, 공개 가사에 음원을 붙이는
        것만으로 아무 로그인 사용자나 원본 MP3 를 받아갈 수 있게 된다.
        """
        lyrics_repo = make_lyrics_repo(lyric_row(visibility="public", audio_file_id=None,
                                                 mr_youtube_video_id="abc12345678"))
        lyrics_repo.check_title_duplicate.return_value = False
        lyrics_repo.update_lyrics.return_value = True
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.patch("/api/v1/lyrics/5", json={"lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 200
        lyrics_repo.update_visibility.assert_awaited_once_with(5, "private")

    @pytest.mark.asyncio
    async def test_patch_on_already_audio_lyric_keeps_visibility(self):
        """이미 음원 가사면 저장할 때마다 private 로 되돌리지 않는다 (소유자가 넓혀둔 설정 보존)"""
        lyrics_repo = make_lyrics_repo(lyric_row(visibility="public", audio_file_id=42))
        lyrics_repo.check_title_duplicate.return_value = False
        lyrics_repo.update_lyrics.return_value = True
        app = build_lyrics_app(lyrics_repo, make_audio_repo())
        async with client_for(app) as c:
            res = await c.patch("/api/v1/lyrics/5", json={"lyrics_data": "[]", "audio_file_id": 42})
        assert res.status_code == 200
        lyrics_repo.update_visibility.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reupload_after_soft_delete_revives_instead_of_500(self, _isolated_storage):
        """삭제한 파일을 다시 올리면 UNIQUE(owner_id, sha256) 위반 500 이 아니라 되살아나야 한다"""
        repo = make_audio_repo()
        repo.find_by_owner_sha256.return_value = audio_row(deleted_at="2026-01-01",
                                                           storage_path="aa/bb/old.mp3")
        repo.revive.return_value = True
        place_blob(_isolated_storage, "aa/bb/old.mp3")

        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=mr.mp3", content=MP3_BYTES)

        assert res.status_code == 200
        repo.create.assert_not_awaited()
        repo.revive.assert_awaited_once()
        # 옛 블롭은 정리되고 새 경로로 갈아끼워져야 한다
        assert not (_isolated_storage / "aa/bb/old.mp3").exists()
        assert repo.revive.call_args.kwargs["storage_path"] != "aa/bb/old.mp3"

    @pytest.mark.asyncio
    async def test_concurrent_same_file_upload_returns_winner(self, _isolated_storage):
        """같은 파일 동시 업로드(select-then-insert 경쟁)에서 500 대신 먼저 들어간 행을 돌려준다"""
        from pymysql.err import IntegrityError

        repo = make_audio_repo()
        repo.find_by_owner_sha256.side_effect = [None, audio_row()]  # 조회 시엔 없다가 INSERT 때 충돌
        repo.create.side_effect = IntegrityError(1062, "Duplicate entry")

        async with client_for(build_audio_app(repo)) as c:
            res = await c.post("/api/v1/audio?filename=mr.mp3", content=MP3_BYTES)

        assert res.status_code == 200
        assert res.json()["id"] == 42
        assert list(_isolated_storage.rglob("*.mp3")) == []   # 방금 쓴 블롭은 버려야 한다

    @pytest.mark.asyncio
    async def test_reaper_claim_rechecks_link(self):
        """리퍼 선점은 '미연결' 조건을 UPDATE 안에서 재확인해야 한다.

        대상 선정과 선점이 별개 트랜잭션이라, 재확인이 없으면 그 사이에 가사에 연결된
        음원을 지워버린다(FK SET NULL 로 연결까지 조용히 끊긴다).
        """
        import inspect

        from app.database import audio_purge
        from app.database.audio_repository import AudioRepository

        sql = inspect.getsource(AudioRepository.claim_unlinked_for_purge)
        assert "NOT EXISTS" in sql and "song_lyrics" in sql and "streamer_songbooks" in sql
        # 리퍼가 그 함수를 쓰는지 (조건 없는 claim_for_purge 를 쓰면 안 된다)
        assert "claim_unlinked_for_purge" in inspect.getsource(audio_purge.purge_one)

    @pytest.mark.asyncio
    async def test_reaper_skips_when_linked_meanwhile(self, _isolated_storage):
        """선점이 실패하면(그 사이 연결됨) 파일을 지우지 않고 넘어간다"""
        from app.database import audio_purge

        blob = place_blob(_isolated_storage)
        repo = AsyncMock()
        repo.claim_unlinked_for_purge.return_value = False

        assert await audio_purge.purge_one(42, "aa/bb/testfile.mp3", repo) is False
        assert blob.exists()
        repo.hard_delete.assert_not_awaited()
