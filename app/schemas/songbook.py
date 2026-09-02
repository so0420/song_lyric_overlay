import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal


# 공개 주소(slug) 형식: 2~30자의 소문자/숫자/한글/언더스코어/하이픈
SLUG_PATTERN = re.compile(r"^[a-z0-9가-힣_-]{2,30}$")

SongRequestStatusT = Literal["waiting", "playing", "done"]


def _validate_cover_image_url(v: Optional[str]) -> Optional[str]:
    """커버 이미지 URL 검증: 빈 값은 None, http(s) 스킴만 허용 (속성 주입 차단)"""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 1000:
        raise ValueError("커버 이미지 URL이 너무 깁니다.")
    if not re.match(r"^https?://", v, re.IGNORECASE):
        raise ValueError("커버 이미지 URL은 http(s) 주소만 사용할 수 있습니다.")
    return v


def _validate_custom_song_field(v: Optional[str]) -> Optional[str]:
    """수록곡별 곡 정보 덮어쓰기 값: 빈 값은 None(= 원곡 표기 사용)

    빈 문자열을 저장하지 않는 이유는 조회가 COALESCE 하나로 끝나야 하기 때문이다.
    '덮어썼지만 비어 있는' 중간 상태가 생기면 화면에 빈 제목이 나온다.
    길이는 원본 컬럼(songs.title / artists.name = VARCHAR(512))에 맞춘다.
    """
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 512:
        raise ValueError("512자를 넘을 수 없습니다.")
    return v


class SocialLinkSchema(BaseModel):
    """스트리머 소셜 링크 항목"""
    name: str = Field(..., min_length=1, max_length=50, description="링크 이름")
    url: str = Field(..., min_length=1, max_length=500, description="링크 URL")


class StreamerTagSchema(BaseModel):
    """노래책 태그(카테고리) 항목"""
    name: str = Field(..., min_length=1, max_length=50, description="태그 이름")
    color: str = Field(..., min_length=1, max_length=30, description="태그 색상")


class StreamerProfileUpdateSchema(BaseModel):
    """스트리머 프로필 수정 (PATCH /streamers/me) — 전달된 필드만 갱신"""
    slug: Optional[str] = Field(None, description="노래책 공개 주소")
    description: Optional[str] = Field(None, max_length=1000, description="스트리머 소개")
    social_links: Optional[List[SocialLinkSchema]] = Field(None, max_length=10, description="소셜 링크 목록")
    tags: Optional[List[StreamerTagSchema]] = Field(None, max_length=30, description="노래 태그 목록")
    request_enabled: Optional[bool] = Field(None, description="노래 신청 기능 전체 on/off")
    request_web_enabled: Optional[bool] = Field(None, description="웹(노래책 페이지) 신청 on/off")
    request_auto_playlist: Optional[bool] = Field(None, description="신청 곡 노래하기 재생목록 자동 추가 on/off")
    request_chat_enabled: Optional[bool] = Field(None, description="치지직 채팅(!신청) on/off")
    request_donation_enabled: Optional[bool] = Field(None, description="치지직 후원(!신청) on/off")
    default_price_cheese: Optional[int] = Field(None, ge=0, le=1000000, description="후원 신청 기본 치즈 가격")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: Optional[str]) -> Optional[str]:
        """slug 형식 검증 (2~30자의 소문자/숫자/한글/_/-)"""
        if v is None:
            return v
        v = v.strip()
        if not SLUG_PATTERN.fullmatch(v):
            raise ValueError("공개 주소는 2~30자의 영문 소문자/숫자/한글/_/- 만 사용할 수 있습니다.")
        return v


class SongbookEntryCreateSchema(BaseModel):
    """노래책 수록곡 추가 (POST /songbook/)"""
    song_external_id: str = Field(..., min_length=1, max_length=255, description="노래 외부 ID")
    lyrics_id: Optional[int] = Field(None, description="연결할 가사 ID")
    mr_youtube_video_id: Optional[str] = Field(None, max_length=255, description="MR 유튜브 영상 ID")
    audio_file_id: Optional[int] = Field(None, description="연결할 업로드 음원 ID (본인 소유만)")
    tags: List[str] = Field(default_factory=list, max_length=30, description="노래 태그 이름 목록")
    difficulty: Optional[int] = Field(None, ge=1, le=10, description="난이도 (1~10, 없으면 미설정)")
    memo: Optional[str] = Field(None, max_length=255, description="노래 설명/메모")
    cover_image_url: Optional[str] = Field(None, description="커버 이미지 URL")
    custom_title: Optional[str] = Field(None, description="이 노래책에서만 쓸 곡 제목 (비우면 원곡 제목)")
    custom_artist: Optional[str] = Field(None, description="이 노래책에서만 쓸 가수 이름 (비우면 원곡 가수)")

    _validate_cover = field_validator("cover_image_url")(_validate_cover_image_url)
    _validate_custom = field_validator("custom_title", "custom_artist")(_validate_custom_song_field)


class SongbookEntryUpdateSchema(BaseModel):
    """노래책 수록곡 수정 (PATCH /songbook/{entry_id}) — 전달된 필드만 갱신
    (lyrics_id 연결 해제는 0 또는 null 을 명시 — model_fields_set 으로 명시 여부 구분)
    """
    lyrics_id: Optional[int] = Field(None, description="연결할 가사 ID (0 또는 null 명시 시 해제)")
    mr_youtube_video_id: Optional[str] = Field(None, max_length=255, description="MR 유튜브 영상 ID")
    audio_file_id: Optional[int] = Field(None, description="연결할 업로드 음원 ID (0 또는 null 명시 시 해제)")
    tags: Optional[List[str]] = Field(None, max_length=30, description="노래 태그 이름 목록")
    difficulty: Optional[int] = Field(None, ge=1, le=10, description="난이도 (1~10)")
    memo: Optional[str] = Field(None, max_length=255, description="노래 설명/메모")
    cover_image_url: Optional[str] = Field(None, description="커버 이미지 URL")
    custom_title: Optional[str] = Field(None, description="이 노래책에서만 쓸 곡 제목 (null/빈 값 명시 시 원곡 제목으로 되돌림)")
    custom_artist: Optional[str] = Field(None, description="이 노래책에서만 쓸 가수 이름 (null/빈 값 명시 시 원곡 가수로 되돌림)")

    _validate_cover = field_validator("cover_image_url")(_validate_cover_image_url)
    _validate_custom = field_validator("custom_title", "custom_artist")(_validate_custom_song_field)


class SongRequestCreateSchema(BaseModel):
    """노래 신청 (POST /song-requests/) — 익명 허용"""
    streamer_id: str = Field(..., min_length=1, max_length=255, description="스트리머 외부 ID (UUID 문자열)")
    requester: str = Field(..., min_length=1, max_length=30, description="신청자 닉네임")
    requester_type: Literal["WEB", "MANUAL"] = Field("WEB", description="신청 경로")
    song_id: Optional[int] = Field(None, description="songs 테이블 ID (노래책 곡 신청 시)")
    title: Optional[str] = Field(None, max_length=255, description="노래 제목 (노래책 외 신청용)")
    artist: Optional[str] = Field(None, max_length=255, description="아티스트 (노래책 외 신청용)")

    @field_validator("requester", mode="before")
    @classmethod
    def strip_requester(cls, v):
        """닉네임 앞뒤 공백 제거 (이후 길이 제약 검증)"""
        if isinstance(v, str):
            return v.strip()
        return v


class PlaylistRequestCreateSchema(BaseModel):
    """노래하기 재생목록에서 직접 추가한 곡 → 신청목록 동기화 생성 (POST /song-requests/from-playlist)

    재생목록發이므로 WS 푸시 없이 곧바로 전달 완료(delivered) 처리한다(이중 추가/루프 방지).
    """
    song_external_id: Optional[str] = Field(None, max_length=255, description="노래 외부 ID (songs 매핑용)")
    title: Optional[str] = Field(None, max_length=255, description="노래 제목")
    artist: Optional[str] = Field(None, max_length=255, description="아티스트")


class SongRequestUpdateSchema(BaseModel):
    """노래 신청 수정 (PATCH /song-requests/{request_id})"""
    status: Optional[SongRequestStatusT] = Field(None, description="상태: 대기중/부르는중/이미부름")
    sort_order: Optional[int] = Field(None, description="신청 순서")
    title: Optional[str] = Field(None, max_length=255, description="노래 제목")
    artist: Optional[str] = Field(None, max_length=255, description="아티스트")


class SongRequestReorderSchema(BaseModel):
    """신청 순서 재정렬 (PUT /song-requests/reorder)"""
    ids: List[int] = Field(..., min_length=1, max_length=500, description="새 순서대로 정렬된 신청 ID 목록")


class MarkDeliveredSchema(BaseModel):
    """재생목록 전달 완료 마킹 (POST /song-requests/mark-delivered)"""
    ids: List[int] = Field(..., min_length=1, max_length=500, description="전달 완료된 신청 ID 목록")


class RandomFillSchema(BaseModel):
    """노래책 랜덤 채우기 (POST /song-requests/batch/random)"""
    n: int = Field(..., ge=1, le=50, description="추가할 곡 수 (1~50)")
