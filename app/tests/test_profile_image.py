"""프로필 사진 업로드/삭제/서빙 단위 테스트.

자체 완결 테스트 — conftest.py 의존 없이 파일 안에서 픽스처/헬퍼를 정의한다
(test_audio.py 와 같은 방식).

디스크는 tmp_path 로 갈아끼워서 실제 storage/ 를 절대 건드리지 않는다.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

import app.utils.image_storage as storage
from app.core.auth import get_current_user_api
from app.schemas.users import CurrentUserSchema
from app.utils.csrf import verify_csrf
from app.utils.image_sniff import detect_image_mime
from app.utils.rate_limit import limiter


USER = {"id": 1, "email": "o@e.com", "name": "소유자", "is_admin": False}

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
    root = tmp_path / "profile"
    monkeypatch.setattr(storage, "PROFILE_IMAGE_ROOT", root)
    monkeypatch.setattr(storage, "PROFILE_IMAGE_TMP", root / "tmp")
    yield root


def make_db(picture_path=None):
    """app.api.v1.users 가 직접 쓰는 db_handler 대역"""
    db = AsyncMock()
    db.fetch_one.return_value = {"picture_path": picture_path}
    db.execute_query.return_value = 1
    return db


def build_app(db, monkeypatch, user=USER):
    import app.api.v1.users as users_module

    monkeypatch.setattr(users_module, "db_handler", db)

    app = FastAPI()
    app.include_router(users_module.router, prefix="/api/v1/users")
    app.dependency_overrides[get_current_user_api] = lambda: CurrentUserSchema(**user)
    app.dependency_overrides[verify_csrf] = lambda: True
    return app


@asynccontextmanager
async def client_for(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===============================================================
# A. 매직바이트 판별
# ===============================================================
class TestImageSniff:
    @pytest.mark.parametrize("label,head,expected", [
        ("png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png"),
        ("jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02\x03", "image/jpeg"),
        ("gif87a", b"GIF87a" + b"\x00" * 8, "image/gif"),
        ("gif89a", b"GIF89a" + b"\x00" * 8, "image/gif"),
        ("webp", b"RIFF\x24\x08\x00\x00WEBPVP8 ", "image/webp"),
    ])
    def test_detects_allowed_formats(self, label, head, expected):
        assert detect_image_mime(head) == expected, label

    @pytest.mark.parametrize("label,head", [
        # SVG 는 스크립트를 품을 수 있는 문서라 받지 않는다
        ("svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("svg with xml decl", b"<?xml version='1.0'?><svg></svg>"),
        # RIFF 만 보고 통과시키면 WAV 도 들어온다
        ("wav", b"RIFF\x24\x08\x00\x00WAVEfmt "),
        ("mp3", b"ID3\x03\x00\x00\x00" + b"\x00" * 8),
        ("html", b"<!DOCTYPE html><html><body>x"),
        ("too short", b"\x89PNG"),
    ])
    def test_rejects_others(self, label, head):
        assert detect_image_mime(head) is None, label


# ===============================================================
# B. 업로드
# ===============================================================
class TestUpload:
    @pytest.mark.asyncio
    async def test_uploads_and_records_url(self, monkeypatch, _isolated_storage):
        db = make_db()
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.post("/api/v1/users/me/picture", content=PNG_BYTES)

        assert res.status_code == 200, res.text
        picture = res.json()["picture"]
        assert picture.startswith("/api/v1/users/profile-image/")

        rel = picture[len("/api/v1/users/profile-image/"):]
        assert rel.endswith(".png")
        assert (_isolated_storage / rel).read_bytes() == PNG_BYTES

        # users.picture 와 users.picture_path 가 함께 갱신돼야 한다
        sql, params = db.execute_query.await_args.args
        assert "picture = %s" in sql and "picture_path = %s" in sql
        assert params == (picture, rel, USER["id"])

    @pytest.mark.asyncio
    async def test_replacing_deletes_previous_file(self, monkeypatch, _isolated_storage):
        old_rel = "aa/bb/old.jpg"
        old_path = _isolated_storage / old_rel
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(JPEG_BYTES)

        db = make_db(picture_path=old_rel)
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.post("/api/v1/users/me/picture", content=PNG_BYTES)

        assert res.status_code == 200, res.text
        assert not old_path.exists(), "교체하면 이전 파일은 디스크에서 사라져야 한다"

    @pytest.mark.asyncio
    async def test_rejects_non_image(self, monkeypatch, _isolated_storage):
        db = make_db()
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.post("/api/v1/users/me/picture", content=b"ID3\x03" + b"\x00" * 64)

        assert res.status_code == 415
        db.execute_query.assert_not_awaited()
        # 거부된 업로드가 임시 파일을 남기면 안 된다
        assert list((_isolated_storage / "tmp").glob("*")) == []

    @pytest.mark.asyncio
    async def test_rejects_empty_body(self, monkeypatch):
        db = make_db()
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.post("/api/v1/users/me/picture", content=b"")

        assert res.status_code == 400
        db.execute_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_oversize(self, monkeypatch):
        db = make_db()
        app = build_app(db, monkeypatch)
        payload = PNG_BYTES + b"\x00" * (storage.MAX_PROFILE_IMAGE_BYTES + 1)
        async with client_for(app) as c:
            res = await c.post("/api/v1/users/me/picture", content=payload)

        assert res.status_code == 413
        db.execute_query.assert_not_awaited()


# ===============================================================
# C. 삭제
# ===============================================================
class TestDelete:
    @pytest.mark.asyncio
    async def test_clears_columns_and_file(self, monkeypatch, _isolated_storage):
        rel = "aa/bb/mine.png"
        path = _isolated_storage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_BYTES)

        db = make_db(picture_path=rel)
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.delete("/api/v1/users/me/picture")

        assert res.status_code == 200, res.text
        sql, params = db.execute_query.await_args.args
        assert "picture = NULL" in sql and "picture_path = NULL" in sql
        assert params == (USER["id"],)
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_no_picture_is_not_an_error(self, monkeypatch):
        db = make_db(picture_path=None)
        app = build_app(db, monkeypatch)
        async with client_for(app) as c:
            res = await c.delete("/api/v1/users/me/picture")

        assert res.status_code == 200


# ===============================================================
# D. 서빙 (비로그인 열람 가능)
# ===============================================================
class TestServe:
    @pytest.mark.asyncio
    async def test_serves_with_sniffed_content_type(self, monkeypatch, _isolated_storage):
        rel = "aa/bb/mine.png"
        path = _isolated_storage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG_BYTES)

        app = build_app(make_db(), monkeypatch)
        async with client_for(app) as c:
            res = await c.get(f"/api/v1/users/profile-image/{rel}")

        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert "immutable" in res.headers["cache-control"]
        assert res.content == PNG_BYTES

    @pytest.mark.asyncio
    async def test_missing_file_is_404(self, monkeypatch):
        app = build_app(make_db(), monkeypatch)
        async with client_for(app) as c:
            res = await c.get("/api/v1/users/profile-image/aa/bb/nope.png")
        assert res.status_code == 404

    @pytest.mark.parametrize("escaping", ["../secret.png", "aa/../../secret.png", "/etc/passwd", ""])
    def test_rejects_paths_outside_root(self, escaping, _isolated_storage):
        """서빙 라우트가 URL 조각을 그대로 넘기므로, 경로 탈출은 여기서 막힌다.

        (HTTP 로 확인하지 않는 이유: 클라이언트가 '..' 를 미리 정규화해 버려서
         라우트에 도달하지도 않는 경우가 있어 검증이 헐거워진다)
        """
        with pytest.raises(ValueError):
            storage.resolve_profile_image_path(escaping)

    @pytest.mark.asyncio
    async def test_rejects_unexpected_extension(self, monkeypatch, _isolated_storage):
        rel = "aa/bb/config.env"
        path = _isolated_storage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SECRET=1")

        app = build_app(make_db(), monkeypatch)
        async with client_for(app) as c:
            res = await c.get(f"/api/v1/users/profile-image/{rel}")
        assert res.status_code == 404
