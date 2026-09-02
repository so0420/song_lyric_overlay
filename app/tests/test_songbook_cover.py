"""노래책 수록곡 커버 이미지 업로드/삭제/서빙 단위 테스트.

자체 완결 테스트 — conftest.py 의존 없이 파일 안에서 픽스처/헬퍼를 정의한다
(test_profile_image.py 와 같은 방식).

디스크는 tmp_path 로 갈아끼워서 실제 storage/ 를 절대 건드리지 않는다.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

import app.utils.image_storage as storage
from app.api.v1.streamers import require_approved_user
from app.database.songbook_repository import (
    COVER_IMAGE_URL_PREFIX,
    SONGBOOK_COVER_EXPR,
    get_songbook_repository,
)
from app.schemas.users import CurrentUserSchema
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter


OWNER = {"id": 1, "email": "o@e.com", "name": "소유자", "is_admin": False}
OTHER = {"id": 2, "email": "x@e.com", "name": "남", "is_admin": False}

ENTRY_ID = 7

# 최소한의 매직바이트 + 뒤에 아무 바이트나 (서버는 내용을 해석하지 않는다)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + bytes(range(256))


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
    root = tmp_path / "cover"
    monkeypatch.setattr(storage, "SONG_COVER_ROOT", root)
    monkeypatch.setattr(storage, "SONG_COVER_TMP", root / "tmp")
    yield root


def make_repo(entry=None):
    """SongbookRepository 대역. entry=None 이면 '수록곡 없음'."""
    repo = AsyncMock()
    repo.get_entry.return_value = entry
    repo.update_entry.return_value = True
    repo.remove_entry.return_value = True
    return repo


def entry_row(user_id=OWNER["id"], cover_image_path=None):
    return {
        "id": ENTRY_ID,
        "user_id": user_id,
        "song_id": 100,
        "cover_image_path": cover_image_path,
        "tags": [],
    }


def build_app(repo, user=OWNER):
    import app.api.v1.songbook as songbook_module

    app = FastAPI()
    app.include_router(songbook_module.router, prefix="/api/v1/songbook")
    app.dependency_overrides[require_approved_user] = lambda: CurrentUserSchema(**user)
    app.dependency_overrides[get_songbook_repository] = lambda: repo
    app.dependency_overrides[verify_csrf] = lambda: True
    return app


@asynccontextmanager
async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def stored_path(repo):
    """update_entry(entry_id, cover_image_path=...) 로 넘어간 상대 경로"""
    return repo.update_entry.call_args.kwargs["cover_image_path"]


# ===============================================================
# A. 커버 해석 순서 (SQL 식)
# ===============================================================
class TestCoverExpression:
    def test_uploaded_cover_wins_over_urls(self):
        """올린 커버 > 수록곡 지정 URL > 곡 자체 커버 순서로 COALESCE 된다"""
        expr = SONGBOOK_COVER_EXPR
        assert expr.index("sb.cover_image_path") < expr.index("sb.cover_image_url")
        assert expr.index("sb.cover_image_url") < expr.index("s.cover_image_url")

    def test_builds_serving_url_from_relative_path(self):
        """DB 에는 상대 경로만 두므로 조회 시 서빙 URL 로 조립한다"""
        assert f"CONCAT('{COVER_IMAGE_URL_PREFIX}', sb.cover_image_path)" in SONGBOOK_COVER_EXPR


# ===============================================================
# B. 업로드
# ===============================================================
class TestUpload:
    @pytest.mark.anyio
    async def test_stores_file_and_records_path(self, _isolated_storage):
        repo = make_repo(entry_row())
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=PNG_BYTES)

        assert res.status_code == 200
        rel = stored_path(repo)
        assert res.json()["cover_image_url"] == COVER_IMAGE_URL_PREFIX + rel
        # 매직바이트로 판별한 형식의 확장자가 붙는다 (클라이언트 신고값이 아니다)
        assert rel.endswith(".png")
        assert (_isolated_storage / rel).read_bytes() == PNG_BYTES

    @pytest.mark.anyio
    async def test_ignores_client_content_type(self, _isolated_storage):
        """Content-Type 은 클라이언트가 정하는 값이라 판별에 쓰지 않는다"""
        repo = make_repo(entry_row())
        async with client_for(build_app(repo)) as c:
            res = await c.post(
                f"/api/v1/songbook/{ENTRY_ID}/cover",
                content=JPEG_BYTES,
                headers={"Content-Type": "image/png"},
            )
        assert res.status_code == 200
        assert stored_path(repo).endswith(".jpg")

    @pytest.mark.anyio
    async def test_replacing_deletes_previous_file(self, _isolated_storage):
        old_rel = "aa/bb/old.png"
        old_file = _isolated_storage / old_rel
        old_file.parent.mkdir(parents=True)
        old_file.write_bytes(PNG_BYTES)

        repo = make_repo(entry_row(cover_image_path=old_rel))
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=JPEG_BYTES)

        assert res.status_code == 200
        assert not old_file.exists()
        assert (_isolated_storage / stored_path(repo)).exists()

    @pytest.mark.anyio
    async def test_rejects_non_image_bytes(self, _isolated_storage):
        repo = make_repo(entry_row())
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=b"<svg>x</svg>" * 4)

        assert res.status_code == 415
        repo.update_entry.assert_not_awaited()
        # 임시 파일도 남기지 않는다
        assert not list((_isolated_storage / "tmp").glob("*.part"))

    @pytest.mark.anyio
    async def test_rejects_empty_body(self):
        repo = make_repo(entry_row())
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=b"")
        assert res.status_code == 400
        repo.update_entry.assert_not_awaited()

    @pytest.mark.anyio
    async def test_rejects_oversize(self, monkeypatch):
        import app.api.v1.songbook as songbook_module

        monkeypatch.setattr(songbook_module, "MAX_SONG_COVER_BYTES", 64)
        repo = make_repo(entry_row())
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=PNG_BYTES)

        assert res.status_code == 413
        repo.update_entry.assert_not_awaited()

    @pytest.mark.anyio
    async def test_other_users_entry_is_404(self, _isolated_storage):
        """남의 수록곡은 존재 여부도 알리지 않고, 본문을 받지도 않는다"""
        repo = make_repo(entry_row(user_id=OTHER["id"]))
        async with client_for(build_app(repo, user=OWNER)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=PNG_BYTES)

        assert res.status_code == 404
        repo.update_entry.assert_not_awaited()
        assert not _isolated_storage.exists() or not list(_isolated_storage.rglob("*.png"))

    @pytest.mark.anyio
    async def test_missing_entry_is_404(self):
        repo = make_repo(None)
        async with client_for(build_app(repo)) as c:
            res = await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=PNG_BYTES)
        assert res.status_code == 404

    @pytest.mark.anyio
    async def test_db_failure_leaves_no_orphan_file(self, _isolated_storage):
        repo = make_repo(entry_row())
        repo.update_entry.side_effect = RuntimeError("db down")
        async with client_for(build_app(repo)) as c:
            with pytest.raises(RuntimeError):
                await c.post(f"/api/v1/songbook/{ENTRY_ID}/cover", content=PNG_BYTES)

        assert not list(_isolated_storage.rglob("*.png"))


# ===============================================================
# C. 삭제
# ===============================================================
class TestDelete:
    @pytest.mark.anyio
    async def test_clears_column_and_unlinks_file(self, _isolated_storage):
        rel = "aa/bb/cover.png"
        f = _isolated_storage / rel
        f.parent.mkdir(parents=True)
        f.write_bytes(PNG_BYTES)

        repo = make_repo(entry_row(cover_image_path=rel))
        async with client_for(build_app(repo)) as c:
            res = await c.delete(f"/api/v1/songbook/{ENTRY_ID}/cover")

        assert res.status_code == 200
        assert repo.update_entry.call_args.kwargs["cover_image_path"] is None
        assert not f.exists()

    @pytest.mark.anyio
    async def test_other_users_entry_is_404(self, _isolated_storage):
        rel = "aa/bb/cover.png"
        f = _isolated_storage / rel
        f.parent.mkdir(parents=True)
        f.write_bytes(PNG_BYTES)

        repo = make_repo(entry_row(user_id=OTHER["id"], cover_image_path=rel))
        async with client_for(build_app(repo)) as c:
            res = await c.delete(f"/api/v1/songbook/{ENTRY_ID}/cover")

        assert res.status_code == 404
        assert f.exists()

    @pytest.mark.anyio
    async def test_removing_entry_also_removes_cover_file(self, _isolated_storage):
        rel = "aa/bb/cover.png"
        f = _isolated_storage / rel
        f.parent.mkdir(parents=True)
        f.write_bytes(PNG_BYTES)

        repo = make_repo(entry_row(cover_image_path=rel))
        async with client_for(build_app(repo)) as c:
            res = await c.delete(f"/api/v1/songbook/{ENTRY_ID}")

        assert res.status_code == 200
        repo.remove_entry.assert_awaited_once_with(ENTRY_ID)
        assert not f.exists()


# ===============================================================
# D. 서빙
# ===============================================================
class TestServe:
    @pytest.mark.anyio
    async def test_serves_with_sniffed_mime(self, _isolated_storage):
        rel = "aa/bb/cover.png"
        f = _isolated_storage / rel
        f.parent.mkdir(parents=True)
        f.write_bytes(PNG_BYTES)

        async with client_for(build_app(make_repo())) as c:
            res = await c.get(f"/api/v1/songbook/cover-image/{rel}")

        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert "immutable" in res.headers.get("cache-control", "")
        assert res.content == PNG_BYTES

    @pytest.mark.anyio
    async def test_missing_file_is_404(self):
        async with client_for(build_app(make_repo())) as c:
            res = await c.get("/api/v1/songbook/cover-image/aa/bb/nope.png")
        assert res.status_code == 404

    def test_resolver_rejects_path_escape(self, _isolated_storage):
        """저장 루트를 벗어나는 상대 경로는 경로 해석 단계에서 막힌다"""
        with pytest.raises(ValueError):
            storage.resolve_song_cover_path("../secret.png")
        with pytest.raises(ValueError):
            storage.resolve_song_cover_path("aa/../../secret.png")

    @pytest.mark.anyio
    async def test_rejects_path_escape(self, _isolated_storage, tmp_path):
        """저장 루트 밖의 파일은 존재해도 내주지 않는다 (URL 인코딩으로 우회 시도)"""
        outside = tmp_path / "secret.png"
        outside.write_bytes(PNG_BYTES)

        async with client_for(build_app(make_repo())) as c:
            res = await c.get("/api/v1/songbook/cover-image/..%2Fsecret.png")

        assert res.status_code == 404
        assert res.content != PNG_BYTES

    @pytest.mark.anyio
    async def test_unknown_extension_is_404(self, _isolated_storage):
        """허용 목록 밖 확장자는 Content-Type 을 정할 수 없으니 내주지 않는다"""
        f = _isolated_storage / "aa/bb/cover.svg"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"<svg/>")

        async with client_for(build_app(make_repo())) as c:
            res = await c.get("/api/v1/songbook/cover-image/aa/bb/cover.svg")

        assert res.status_code == 404


@pytest.fixture
def anyio_backend():
    return "asyncio"
