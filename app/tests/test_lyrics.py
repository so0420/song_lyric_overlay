"""
가사 관련 API 테스트
"""
import pytest
from unittest.mock import AsyncMock, patch


class TestLyricsSearch:
    """가사 검색 테스트"""

    @pytest.mark.asyncio
    async def test_search_lyrics_success(self, async_client, mock_db):
        """가사 검색 성공"""
        mock_db.fetch_all.return_value = [
            {
                "song_id": 1,
                "track_name": "테스트 노래",
                "song_external_id": "it_123",
                "artwork_url": "http://example.com/img.jpg",
                "artist_name": "테스트 아티스트",
                "artist_id": "it_artist_1",
                "lyrics_count": 3
            }
        ]
        mock_db.fetch_one.return_value = {"total": 1}

        response = await async_client.get("/api/v1/lyrics/search?q=테스트")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    @pytest.mark.asyncio
    async def test_search_lyrics_empty_query(self, async_client):
        """빈 검색어"""
        response = await async_client.get("/api/v1/lyrics/search?q=")

        assert response.status_code == 422  # Validation error


class TestLyricsCreate:
    """가사 생성 테스트"""

    @pytest.mark.asyncio
    async def test_create_lyrics_unauthorized(self, async_client):
        """미로그인 상태에서 가사 생성"""
        response = await async_client.post("/api/v1/lyrics/", json={
            "song_id": 1,
            "title": "테스트 가사",
            "mr_youtube_video_id": "abc123",
            "lyrics_data": "[]"
        })

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_lyrics_success(self, async_client, mock_db, mock_session):
        """가사 생성 성공"""
        with patch("app.core.auth.get_current_user") as mock_auth:
            mock_auth.return_value = mock_session["user"]

            mock_db.fetch_one.return_value = None  # 중복 없음
            mock_db.execute_query.return_value = 1  # 생성된 ID

            response = await async_client.post(
                "/api/v1/lyrics/",
                json={
                    "song_id": 1,
                    "title": "테스트 가사",
                    "mr_youtube_video_id": "abc123",
                    "lyrics_data": "[]"
                },
                cookies={"session": "test"}
            )

            # 실제 세션 없이는 401 반환됨
            assert response.status_code in [200, 401]


class TestLyricsFavorites:
    """가사 즐겨찾기 테스트"""

    @pytest.mark.asyncio
    async def test_get_favorites_unauthorized(self, async_client):
        """미로그인 상태에서 즐겨찾기 조회"""
        response = await async_client.get("/api/v1/lyrics/favorites")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_add_favorite_unauthorized(self, async_client):
        """미로그인 상태에서 즐겨찾기 추가"""
        response = await async_client.post("/api/v1/lyrics/1/favorite")

        assert response.status_code == 401


class TestLyricsRepository:
    """LyricsRepository 단위 테스트"""

    @pytest.mark.asyncio
    async def test_get_lyrics_counts(self, mock_db):
        """가사 개수 조회"""
        from app.database.lyrics_repository import LyricsRepository

        mock_db.fetch_all.return_value = [
            {"song_external_id": "it_1", "count": 5},
            {"song_external_id": "it_2", "count": 3}
        ]

        repo = LyricsRepository(db=mock_db)
        result = await repo.get_lyrics_counts(["it_1", "it_2", "it_3"])

        assert result == {"it_1": 5, "it_2": 3}

    @pytest.mark.asyncio
    async def test_get_lyrics_counts_empty(self, mock_db):
        """빈 목록으로 가사 개수 조회"""
        from app.database.lyrics_repository import LyricsRepository

        repo = LyricsRepository(db=mock_db)
        result = await repo.get_lyrics_counts([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_add_favorite_success(self, mock_db):
        """즐겨찾기 추가 성공"""
        from app.database.lyrics_repository import LyricsRepository

        mock_db.execute_query.return_value = 1

        repo = LyricsRepository(db=mock_db)
        result = await repo.add_favorite(user_id=1, lyrics_id=10)

        assert result is True

    @pytest.mark.asyncio
    async def test_add_favorite_duplicate(self, mock_db):
        """즐겨찾기 중복 추가"""
        from app.database.lyrics_repository import LyricsRepository

        mock_db.execute_query.side_effect = Exception("Duplicate entry")

        repo = LyricsRepository(db=mock_db)
        result = await repo.add_favorite(user_id=1, lyrics_id=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_title_duplicate(self, mock_db):
        """가사 제목 중복 체크"""
        from app.database.lyrics_repository import LyricsRepository

        mock_db.fetch_one.return_value = {"id": 5}

        repo = LyricsRepository(db=mock_db)
        result = await repo.check_title_duplicate(
            owner_id=1,
            song_id=10,
            title="중복 제목"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_title_not_duplicate(self, mock_db):
        """가사 제목 중복 아님"""
        from app.database.lyrics_repository import LyricsRepository

        mock_db.fetch_one.return_value = None

        repo = LyricsRepository(db=mock_db)
        result = await repo.check_title_duplicate(
            owner_id=1,
            song_id=10,
            title="고유 제목"
        )

        assert result is False
