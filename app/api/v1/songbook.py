"""노래책 수록곡 API

- 공개 조회: 외부 UUID 기반, 승인된 스트리머의 노래책만 노출
- 추가/수정/삭제: 오버레이 사용 승인된 유저 + 본인 노래책 소유권 확인
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.api.v1.streamers import require_approved_user
from app.core.auth import get_current_user
from app.core.lyrics_access import can_view_lyrics
from app.schemas.users import CurrentUserSchema
from app.schemas.songbook import SongbookEntryCreateSchema, SongbookEntryUpdateSchema
from app.database.streamer_repository import StreamerRepository, get_streamer_repository
from app.database.songbook_repository import (
    COVER_IMAGE_URL_PREFIX,
    SongbookRepository,
    get_songbook_repository,
)
from app.database.audio_repository import AudioRepository, get_audio_repository
from app.database.overlay_repository import OverlayRepository, get_overlay_repository
from app.database.song_repository import SongRepository, get_song_repository
from app.database.lyrics_repository import LyricsRepository, get_lyrics_repository
from app.utils.csrf import verify_csrf
from app.utils.image_sniff import ALLOWED_IMAGE
from app.utils.image_storage import (
    MAX_SONG_COVER_BYTES,
    new_cover_temp_path,
    resolve_song_cover_path,
)
from app.utils.image_upload import receive_image, unlink_image
from app.utils.log import logger
from app.utils.rate_limit import limiter, RATE_LIMITS

router = APIRouter()

# 서빙할 때 붙일 Content-Type. 확장자는 우리가 매직바이트로 판별해서 붙인 것뿐이라
# 여기서 되짚어도 클라이언트 신고값을 신뢰하는 게 아니다.
_MIME_BY_EXTENSION = {ext: mime for mime, ext in ALLOWED_IMAGE.items()}


async def _unlink_cover(storage_path: Optional[str]) -> None:
    """옛 커버 이미지 파일을 지운다. 실패해도 요청을 실패시키지는 않는다."""
    await unlink_image(storage_path, resolve_song_cover_path, "songbook-cover")


# ---------------------------------------------------------------------
# 커버 이미지 (수록곡별 — 이 노래책에서만 보이고 songs 테이블은 건드리지 않는다)
#
# 라우트 순서 주의: 아래 GET /{streamer_id} 보다 먼저 선언한다. 저장 경로가
# 'ab/cd/....jpg' 라 실제로는 세그먼트 수가 달라 겹치지 않지만, 순서에 기대지
# 않아도 되게 해 둔다.
# ---------------------------------------------------------------------

@router.get("/cover-image/{storage_path:path}")
async def get_cover_image(storage_path: str):
    """수록곡 커버 이미지 서빙 (비로그인 열람 가능).

    공개 노래책 페이지에 그대로 노출되는 자산이라 인증을 걸지 않는다
    (app/api/v1/users.py 의 프로필 사진 서빙과 같은 정책).
    경로는 uuid4 기반이고 커버를 바꿀 때마다 새 경로가 되므로,
    옛 URL 은 파일과 함께 사라진다 (그래서 immutable 로 캐시해도 안전하다).
    """
    try:
        path = resolve_song_cover_path(storage_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    if not path.is_file():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    mime = _MIME_BY_EXTENSION.get(path.suffix.lower().lstrip("."))
    if mime is None:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    # filename= 을 넘기면 Content-Disposition 이 attachment 가 되어 표시 대신
    # 다운로드가 되므로 넘기지 않는다.
    return FileResponse(
        path,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


async def _own_entry_or_404(
    entry_id: int, user: CurrentUserSchema, songbook_repo: SongbookRepository
) -> dict:
    """본인 노래책의 수록곡만 통과 (타인 소유는 존재 여부를 노출하지 않도록 404)"""
    entry = await songbook_repo.get_entry(entry_id)
    if not entry or entry["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="수록곡을 찾을 수 없습니다.")
    return entry


@router.post("/{entry_id}/cover", dependencies=[Depends(verify_csrf)])
@limiter.limit(RATE_LIMITS["cover_upload_hour"])
@limiter.limit(RATE_LIMITS["cover_upload_minute"])
async def upload_entry_cover(
    request: Request,
    entry_id: int,
    user: CurrentUserSchema = Depends(require_approved_user),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
):
    """수록곡 커버 이미지 업로드. **요청 본문 = 이미지 바이트 원본** (멀티파트 아님).

    본문 수신·검증·배치는 app/utils/image_upload.py 의 receive_image 가 맡는다
    (멀티파트를 쓰지 않는 이유도 그 모듈 주석 참고).

    올린 커버는 **이 노래책의 이 수록곡에만** 적용된다 — songs.cover_image_url 은
    건드리지 않으므로 다른 이용자의 노래책이나 곡 검색 결과에는 영향이 없다.

    브라우저는 올리기 전에 640px 정사각형 JPEG 으로 줄여서 보내지만
    (app/static/js/cover_image.js), 서버는 그 전제를 믿지 않고 크기와
    매직바이트를 다시 확인한다.
    """
    entry = await _own_entry_or_404(entry_id, user, songbook_repo)

    stored = await receive_image(
        request,
        max_bytes=MAX_SONG_COVER_BYTES,
        temp_factory=new_cover_temp_path,
        resolver=resolve_song_cover_path,
        oversize_detail="커버 이미지는 5MB 를 넘을 수 없습니다.",
    )

    try:
        await songbook_repo.update_entry(entry_id, cover_image_path=stored.storage_path)
    except Exception:
        # DB 기록 실패 — 아무도 참조하지 못하는 고아 파일을 남기지 않는다
        stored.path.unlink(missing_ok=True)
        raise

    await _unlink_cover(entry.get("cover_image_path"))

    logger.info(
        f"[songbook-cover] 업로드 완료 user={user['id']} entry={entry_id} "
        f"{stored.mime} {stored.byte_size}B"
    )
    return {"success": True, "cover_image_url": COVER_IMAGE_URL_PREFIX + stored.storage_path}


@router.delete("/{entry_id}/cover", dependencies=[Depends(verify_csrf)])
async def delete_entry_cover(
    entry_id: int,
    user: CurrentUserSchema = Depends(require_approved_user),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
):
    """올린 커버 이미지 삭제 — 수록곡 지정 URL / 곡 자체 커버로 되돌아간다."""
    entry = await _own_entry_or_404(entry_id, user, songbook_repo)

    await songbook_repo.update_entry(entry_id, cover_image_path=None)
    await _unlink_cover(entry.get("cover_image_path"))
    return {"success": True}


def _parse_tags_param(tags: Optional[str]) -> Optional[List[str]]:
    """쉼표 구분 태그 쿼리 파라미터 → 태그 이름 리스트 (빈 값 제거)"""
    if not tags:
        return None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return tag_list or None


def _serialize_entry(row: dict) -> dict:
    """수록곡 row → 응답용 dict (tags 는 repository 에서 이미 파싱됨)

    주의: 이 함수는 **공개** 노래책 응답(get_public_songbook)에 쓰인다.
    업로드 음원의 id 는 절대 넣지 말 것 — 재생 권한은 가사 공개 범위로 판정하므로
    id 가 공개되면 판정 경로를 우회할 여지가 생긴다. 보유 여부(has_audio)만 노출한다.
    """
    has_audio = bool(row.get("audio_file_id") or row.get("lyrics_audio_file_id"))
    return {
        "entry_id": row["entry_id"],
        "song_id": row["song_id"],
        "song_external_id": row["song_external_id"],
        # 표시용 제목/가수 — 수록곡에 덮어쓴 값이 있으면 그 값 (repository 에서 COALESCE)
        "title": row["title"],
        "artist_name": row.get("artist_name"),
        # 원곡(songs/artists)의 표기. 수정 화면이 '덮어썼는지 / 무엇으로 되돌리는지'를
        # 판단하려면 표시용 값만으로는 알 수 없어서 함께 내려준다.
        "original_title": row.get("original_title"),
        "original_artist_name": row.get("original_artist_name"),
        "cover_image_url": row.get("cover_image_url"),
        # 커버가 '이 노래책에서 직접 올린 것'인지 — 수정 화면의 삭제 버튼 노출 판단용
        "has_uploaded_cover": bool(row.get("cover_image_path")),
        # MR 해석: 수록곡 지정 MR 우선, 없으면 연결된 가사의 MR 으로 폴백
        # (신청 흐름의 core.song_request_push.resolve_mr_video_id 와 동일 규칙)
        "mr_youtube_video_id": row.get("mr_youtube_video_id") or row.get("lyrics_mr_video_id"),
        "has_audio": has_audio,
        "lyrics_id": row.get("lyrics_id"),
        "lyrics_title": row.get("lyrics_title"),
        "has_lyrics": row.get("has_lyrics", False),
        "tags": row.get("tags", []),
        "difficulty": row.get("difficulty"),
        "memo": row.get("memo"),
        # 최근 1달간 신청 횟수 (없으면 0)
        "recent_request_count": int(row.get("recent_request_count") or 0),
    }


async def _validate_lyrics_link(
    lyrics_id: int,
    song_internal_id: int,
    user: CurrentUserSchema,
    lyrics_repo: LyricsRepository,
) -> None:
    """가사 연결 가능 여부 검증: 존재(미삭제) + 노래 일치(형제 곡 허용) + 열람 권한 — 실패 시 400"""
    # get_lyrics_by_id 는 deleted_at IS NULL 필터를 포함한다
    lyric_row = await lyrics_repo.get_lyrics_by_id(lyrics_id)
    if not lyric_row:
        raise HTTPException(status_code=400, detail="해당 가사를 연결할 수 없습니다.")
    # 같은 곡 또는 같은 제목+가수인 형제 곡(중복 레코드)의 가사면 연결 허용
    if lyric_row["song_id"] != song_internal_id:
        if not await lyrics_repo.is_canonical_sibling(lyric_row["song_id"], song_internal_id):
            raise HTTPException(status_code=400, detail="해당 가사를 연결할 수 없습니다.")
    if not await can_view_lyrics(lyric_row, user, lyrics_repo):
        raise HTTPException(status_code=400, detail="해당 가사를 연결할 수 없습니다.")


async def _validate_audio_link(
    audio_file_id: int,
    user: CurrentUserSchema,
    audio_repo: AudioRepository,
) -> None:
    """음원 연결 가능 여부 검증: 존재(미삭제) + **본인 소유** — 실패 시 400.

    수록곡 음원은 소유자 전용 경로(GET /api/v1/audio/{id})로 재생되므로, 남의 파일을
    붙이면 스트리머 본인도 재생하지 못한다. 그리고 그런 연결은 애초에 허용해선 안 된다.
    """
    row = await audio_repo.get_by_id(audio_file_id)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=400, detail="해당 음원을 연결할 수 없습니다.")
    if not user.get("is_admin") and row.get("owner_id") != user["id"]:
        raise HTTPException(status_code=400, detail="해당 음원을 연결할 수 없습니다.")


@router.get("/{streamer_id}")
@limiter.limit(RATE_LIMITS["api"])
async def get_public_songbook(
    request: Request,
    streamer_id: str,
    q: Optional[str] = Query(None, max_length=100, description="검색어 (제목/아티스트)"),
    tags: Optional[str] = Query(None, description="쉼표로 구분된 태그 이름 필터"),
    has_lyrics: Optional[bool] = Query(None, description="가사 보유 필터 (true=있음, false=없음)"),
    sort: str = Query(
        "default",
        pattern="^(default|requests|requests_asc)$",
        description="정렬 (default=최근 추가순, requests=최근 1달 신청 많은 순, requests_asc=적은 순)",
    ),
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
        streamer["id"], q=q, tags=tag_list, limit=limit, offset=offset,
        has_lyrics=has_lyrics, sort=sort,
    )
    total = await songbook_repo.count_songbook(streamer["id"], q=q, tags=tag_list, has_lyrics=has_lyrics)

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


@router.get("/{streamer_id}/entry/{entry_id}")
@limiter.limit(RATE_LIMITS["api"])
async def get_public_songbook_entry(
    request: Request,
    streamer_id: str,
    entry_id: int,
    user=Depends(get_current_user),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
):
    """공개 노래책의 수록곡 1건 조회

    노래하기 페이지가 '이 곡 부르기'로 넘어온 곡을 재생목록에 담을 때 쓴다.
    제목/커버/MR 을 URL 로 받아쓰지 않고 여기서 다시 읽는 이유는, 재생목록에 들어갈
    값을 클라이언트가 마음대로 정하지 못하게 하기 위해서다.

    응답은 목록(get_public_songbook)과 같은 공개 필드이고, **노래책 주인 본인일 때만**
    업로드 음원 id 를 덧붙인다. 음원 재생은 소유자 전용 경로라 남에게 내려봐야 쓸 수
    없고, 내려서도 안 된다 (_serialize_entry 주석 참고).
    """
    streamer = await streamer_repo.get_public_by_external_id(streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="노래책을 찾을 수 없습니다.")

    row = await songbook_repo.get_songbook_entry(streamer["id"], entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="수록곡을 찾을 수 없습니다.")

    entry = _serialize_entry(row)
    if user and user.get("id") == streamer["user_id"]:
        entry["audio_file_id"] = row.get("audio_file_id")
    return entry


def _serialize_playlist_item(item: dict) -> dict:
    """저장된 재생목록 아이템 → 공개 노출용 최소 필드 (제목/아티스트/커버/영상ID)

    음원 항목은 video_id 가 빈 문자열이 되고, 공개 페이지는 이미 썸네일 폴백을 갖고 있다.
    음원 id 나 재생 주소는 공개 응답에 넣지 않는다.
    """
    is_audio = item.get("sourceType") == "audio" or (not item.get("sourceType") and item.get("audioId"))
    return {
        "song_title": item.get("songTitle") or item.get("song_title") or "",
        "artist_name": item.get("artistName") or item.get("artist_name") or "",
        "cover_image_url": item.get("coverImageUrl") or item.get("coverUrl") or "",
        "video_id": "" if is_audio else (item.get("videoId") or item.get("mr_youtube_video_id") or ""),
        "source_type": "audio" if is_audio else "youtube",
    }


@router.get("/{streamer_id}/playlist")
@limiter.limit(RATE_LIMITS["api"])
async def get_public_playlist(
    request: Request,
    streamer_id: str,
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    overlay_repo: OverlayRepository = Depends(get_overlay_repository),
):
    """공개 재생목록 조회 — 스트리머가 지금 부르고 있는/예정인 곡 목록 (미승인/탈퇴는 404)"""
    streamer = await streamer_repo.get_public_by_external_id(streamer_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="노래책을 찾을 수 없습니다.")

    data = await overlay_repo.get_playlist(streamer["user_id"])
    items = [_serialize_playlist_item(it) for it in data.get("playlist", []) if isinstance(it, dict)]
    return {
        "items": items,
        "current_index": data.get("current_index", -1),
        "total": len(items),
    }


@router.post("/", dependencies=[Depends(verify_csrf)])
async def add_songbook_entry(
    payload: SongbookEntryCreateSchema,
    user: CurrentUserSchema = Depends(require_approved_user),
    streamer_repo: StreamerRepository = Depends(get_streamer_repository),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
    song_repo: SongRepository = Depends(get_song_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
    audio_repo: AudioRepository = Depends(get_audio_repository),
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
    else:
        # 직접 지정하지 않았으면 같은 곡(형제 곡 포함)의 기존 공개 가사를 자동 연결
        lyrics_id = await lyrics_repo.get_best_public_lyrics_id_for_song(song["id"])

    if payload.audio_file_id:
        await _validate_audio_link(payload.audio_file_id, user, audio_repo)

    entry_id = await songbook_repo.add_song(
        streamer_id=streamer["id"],
        song_id=song["id"],
        lyrics_id=lyrics_id,
        mr_youtube_video_id=payload.mr_youtube_video_id,
        audio_file_id=payload.audio_file_id or None,
        tags=payload.tags,
        difficulty=payload.difficulty,
        memo=payload.memo,
        cover_image_url=payload.cover_image_url,
        custom_title=payload.custom_title,
        custom_artist=payload.custom_artist,
    )
    return {"entry_id": entry_id}


@router.patch("/{entry_id}", dependencies=[Depends(verify_csrf)])
async def update_songbook_entry(
    entry_id: int,
    payload: SongbookEntryUpdateSchema,
    user: CurrentUserSchema = Depends(require_approved_user),
    songbook_repo: SongbookRepository = Depends(get_songbook_repository),
    lyrics_repo: LyricsRepository = Depends(get_lyrics_repository),
    audio_repo: AudioRepository = Depends(get_audio_repository),
):
    """수록곡 수정 (전달된 필드만 갱신, 본인 노래책의 곡만)"""
    entry = await _own_entry_or_404(entry_id, user, songbook_repo)

    fields = payload.model_dump(exclude_unset=True)

    # lyrics_id 는 명시 여부로 연결/해제를 구분 (0 또는 null 명시 = 연결 해제)
    if "lyrics_id" in payload.model_fields_set:
        if payload.lyrics_id:
            await _validate_lyrics_link(payload.lyrics_id, entry["song_id"], user, lyrics_repo)
            fields["lyrics_id"] = payload.lyrics_id
        else:
            fields["lyrics_id"] = None

    # audio_file_id 도 같은 규칙 (0 또는 null 명시 = 연결 해제)
    if "audio_file_id" in payload.model_fields_set:
        if payload.audio_file_id:
            await _validate_audio_link(payload.audio_file_id, user, audio_repo)
            fields["audio_file_id"] = payload.audio_file_id
        else:
            fields["audio_file_id"] = None

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
    entry = await _own_entry_or_404(entry_id, user, songbook_repo)

    await songbook_repo.remove_entry(entry_id)
    # 행이 사라지면 경로를 알 수 없으므로 삭제 직후 파일도 함께 지운다
    await _unlink_cover(entry.get("cover_image_path"))
    return {"success": True}
