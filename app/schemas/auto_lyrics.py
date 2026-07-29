from pydantic import BaseModel, Field
from typing import Optional

# '이 곡만' 오프셋 허용 범위 (ms) — MR 인트로가 길면 첫 가사 기준 오프셋이 수십 초가 될 수 있어
# 넉넉히 ±10분으로 둔다. apply/patch 두 경로가 같은 범위를 쓴다.
OFFSET_MIN_MS = -600000
OFFSET_MAX_MS = 600000


class AutoLyricsApplySchema(BaseModel):
    """노래하기 탭에서 LRCLIB 자동 가사를 적용할 때 남기는 기록.

    프론트는 곡의 외부 ID(song_external_id, 예: custom_it_123)만 안정적으로 가지고 있어
    서버가 이를 숫자 songs.id 로 해석해 저장한다.
    """
    song_external_id: str = Field(..., max_length=255)
    source: str = Field("lrclib", max_length=20)
    source_id: Optional[str] = Field(None, max_length=64)
    track_name: Optional[str] = Field(None, max_length=255)
    artist_name: Optional[str] = Field(None, max_length=255)
    album_name: Optional[str] = Field(None, max_length=255)
    duration: Optional[int] = None
    synced_lyrics: Optional[str] = None
    lyrics_data: str  # 변환된 [{"start","end","text"}] JSON 문자열
    mr_youtube_video_id: Optional[str] = Field(None, max_length=255)
    offset_ms: int = Field(0, ge=OFFSET_MIN_MS, le=OFFSET_MAX_MS)


class OffsetPatchSchema(BaseModel):
    """'이 곡만 오프셋' 조정 시 기록 갱신."""
    offset_ms: int = Field(..., ge=OFFSET_MIN_MS, le=OFFSET_MAX_MS)


class AutoLyricsLinkSchema(BaseModel):
    """관리자가 편집기에서 저장해 만든 정식 가사를 자동가사 기록에 연결."""
    lyrics_id: int
    autolink_songbook: bool = True  # 가사 없는 노래책 수록곡에 자동 연결할지 (편집기 토글)
