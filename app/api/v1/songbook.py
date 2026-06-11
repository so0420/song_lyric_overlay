"""노래책 수록곡 API

- 공개 조회: 외부 UUID 기반, 승인된 스트리머의 노래책만 노출
- 추가/수정/삭제: 오버레이 사용 승인된 유저 + 본인 노래책 소유권 확인
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.v1.streamers import require_approved_user
from app.core.lyrics_access import can_view_lyrics
from app.schemas.users import CurrentUserSchema
from app.schemas.songbook import SongbookEntryCreateSchema, SongbookEntryUpdateSchema
from app.database.streamer_repository import StreamerRepository, get_streamer_repository
from app.database.songbook_repository import SongbookRepository, get_songbook_repository
from app.database.song_repository import SongRepository, get_song_repository
from app.database.lyrics_repository import LyricsRepository, get_lyrics_repository
from app.utils.csrf import verify_csrf
from app.utils.rate_limit import limiter, RATE_LIMITS

router = APIRouter()


def _parse_tags_param(tags: Optional[str]) -> Optional[List[str]]:
    """쉼표 구분 태그 쿼리 파라미터 → 태그 이름 리스트 (빈 값 제거)"""
    if not tags:
        return None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return tag_list or None


def _serialize_entry(row: dict) -> dict:
    """수록곡 row → 응답용 dict (tags 는 repository 에서 이미 파싱됨)"""
    return {
        "entry_id": row["entry_id"],
        "song_id": row["song_id"],
        "song_external_id": row["song_external_id"],
        "title": row["title"],
        "artist_name": row.get("artist_name"),
        "cover_image_url": row.get("cover_image_url"),
        "mr_youtube_video_id": row.get("mr_youtube_video_id"),
        "lyrics_id": row.get("lyrics_id"),
        "lyrics_title": row.get("lyrics_title"),
        "has_lyrics": row.get("has_lyrics", False),
        "tags": row.get("tags", []),
        "difficulty": row.get("difficulty"),
        "memo": row.get("memo"),
    }


async def _validate_lyrics_link(
    lyrics_id: int,
    song_internal_id: int,
    user: CurrentUserSchema,
    lyrics_repo: LyricsRepository,
) -> None:
    """가사 연결 가능 여부 검증: 존재(미삭제) + 노래 일치 + 열람 권한 — 실패 시 400"""
    # get_lyrics_by_id 는 deleted_at IS NULL 필터를 포함한다
    lyric_row = await lyrics_repo.get_lyrics_by_id(lyrics_id)
    if not lyric_row or lyric_row["song_id"] != song_internal_id:
        raise HTTPException(status_code=400, detail="해당 가사를 연결할 수 없습니다.")
    if not await can_view_lyrics(lyric_row, user, lyrics_repo):
        raise HTTPException(status_code=400, detail="해당 가사를 연결할 수 없습니다.")


@router.get("/{streamer_id}")
@limiter.limit(RATE_LIMITS["api"])
async def get_public_songbook(
    request: Request,
    streamer_id: str,
    q: Optional[str] = Query(None, max_length=100, description="검색어 (제목/아티스트)"),
    tags: Optional[str] = Query(None, description="쉼표로 구분된 태그 이름 필터"),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
):
    """공개 노래책 조회 (streamer_id 는 외부 UUID, 미승인/탈퇴 스트리머는 404)"""
    streamer = await streamer_repo.get_public_by_external_id(streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="노래책을 찾을 수 없습니다.")

    tag_list = _parse_tags_param(tags)
    rows = await songbook_repo.get_songbook(
        streamer["id"], q=q, tags=tag_list, limit=limit, offset=offset
    )
    total = await songbook_repo.count_songbook(streamer["id"], q=q, tags=tag_list)

    return {
        "items": [_serialize_entry(row) for row in rows],
        "total": total,
        "streamer": {
            "id": streamer["streamer_id"],
            "name": streamer["name"],
            "slug": streamer["slug"],
            "request_enabled": bool(streamer.get("request_enabled")),
            "request_web_enabled": bool(streamer.get("request_web_enabled")),
        },
    }


@router.post("/", dependencies=[Depends(verify_csrf)])
async def add_songbook_entry(
    payload: SongbookEntryCreateSchema,
    user: CurrentUserSchema = Depends(require_approved_user),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
    song_repo: SongRepository = Depends(get_song_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """노래책에 곡 추가 (같은 곡 재추가 시 메타데이터 갱신)"""
    streamer = await streamer_repo.get_by_user_id(user["id"])
    if not streamer:
        raise HTTPException(status_code=403, detail="노래책 프로필을 먼저 만들어주세요.")

    # 검색 API 가 iTunes 곡을 DB 에 선등록하므로 정상 흐름에서는 항상 존재
    song = await song_repo.get_song_by_external_id(payload.song_external_id)
    if not song:
        raise HTTPException(status_code=404, detail="노래를 찾을 수 없습니다. 검색을 통해 선택해주세요.")

    lyrics_id = payload.lyrics_id or None
    if lyrics_id:
        await _validate_lyrics_link(lyrics_id, song["id"], user, lyrics_repo)

    entry_id = await songbook_repo.add_song(
        streamer_id=streamer["id"],
        song_id=song["id"],
        lyrics_id=lyrics_id,
        mr_youtube_video_id=payload.mr_youtube_video_id,
        tags=payload.tags,
        difficulty=payload.difficulty,
        memo=payload.memo,
        cover_image_url=payload.cover_image_url,
    )
    return {"entry_id": entry_id}


@router.patch("/{entry_id}", dependencies=[Depends(verify_csrf)])
async def update_songbook_entry(
    entry_id: int,
    payload: SongbookEntryUpdateSchema,
    user: CurrentUserSchema = Depends(require_approved_user),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
):
    """수록곡 수정 (전달된 필드만 갱신, 본인 노래책의 곡만)"""
    entry = await songbook_repo.get_entry(entry_id)
    if not entry or entry["user_id"] != user["id"]:
        # 타인 소유는 존재 여부를 노출하지 않도록 404
        raise HTTPException(status_code=404, detail="수록곡을 찾을 수 없습니다.")

    fields = payload.model_dump(exclude_unset=True)

    # lyrics_id 는 명시 여부로 연결/해제를 구분 (0 또는 null 명시 = 연결 해제)
    if "lyrics_id" in payload.model_fields_set:
        if payload.lyrics_id:
            await _validate_lyrics_link(payload.lyrics_id, entry["song_id"], user, lyrics_repo)
            fields["lyrics_id"] = payload.lyrics_id
        else:
            fields["lyrics_id"] = None

    if fields:
        await songbook_repo.update_entry(entry_id, **fields)

    return {"success": True}


@router.delete("/{entry_id}", dependencies=[Depends(verify_csrf)])
async def remove_songbook_entry(
    entry_id: int,
    user: CurrentUserSchema = Depends(require_approved_user),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
):
    """수록곡 삭제 (본인 노래책의 곡만)"""
    entry = await songbook_repo.get_entry(entry_id)
    if not entry or entry["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="수록곡을 찾을 수 없습니다.")

    await songbook_repo.remove_entry(entry_id)
    return {"success": True}
