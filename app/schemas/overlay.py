from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class LyricsInitSchema(BaseModel):
    """곡 시작 시 전체 가사 데이터 전송"""
    songTitle: Optional[str] = None
    artist: Optional[str] = None
    lyrics: Optional[List[dict]] = None  # [{id, start, end, text}, ...]
    currentTime: float = 0               # ms (obsOffset 적용됨)
    isPlaying: bool = False


class LyricsTimeSyncSchema(BaseModel):
    """주기적 시간 동기화"""
    currentTime: float       # ms (obsOffset 적용됨)
    isPlaying: bool = True


class PlaylistItemSchema(BaseModel):
    """재생목록 아이템"""
    songTitle: Optional[str] = None
    artistName: Optional[str] = None
    coverUrl: Optional[str] = None

    class Config:
        extra = "allow"


class PlaylistSyncSchema(BaseModel):
    """재생목록 동기화 데이터"""
    items: Optional[List[PlaylistItemSchema]] = None
    currentIndex: Optional[int] = None

    class Config:
        extra = "allow"


class OverlaySettingsSchema(BaseModel):
    # 가사 스타일
    font_family: str = "Pretendard"
    font_size: int = 52
    font_color: str = "#FFFFFF"
    highlight_color: str = "#FFE500"
    # 요소별 굵기
    current_line_weight: int = 800
    prev_line_weight: int = 600
    next_line_weight: int = 600
    song_title_weight: int = 800
    artist_weight: int = 600
    # 텍스트 외곽선
    text_stroke: bool = True
    stroke_color: str = "#000000"
    # 요소별 외곽선 두께
    current_line_stroke: int = 3
    prev_line_stroke: int = 2
    next_line_stroke: int = 2
    song_title_stroke: int = 3
    artist_stroke: int = 2
    text_shadow: bool = True
    # 표시 옵션
    animation_enabled: bool = True
    show_prev_line: bool = True
    show_next_line: bool = True
    # 외국어 가사 줄 표시 옵션 (\n으로 구분된 각 줄)
    show_lyrics_line1: bool = True   # 원문 (1번째 줄)
    show_lyrics_line2: bool = True   # 발음 (2번째 줄)
    show_lyrics_line3: bool = True   # 해석 (3번째 줄)
    # 여러 줄 가사일 때 이전/다음 가사 숨기기
    hide_adj_lines_for_multiline: bool = False
    # 노래 정보
    show_song_title: bool = True
    show_artist: bool = True
    show_now_badge: bool = True
    song_title_size: int = 48
    artist_size: int = 28
    song_info_position: str = "top-left"
    # 재생목록 설정
    show_playlist: bool = False
    playlist_position: str = "right"
    playlist_max_items: int = 5
    playlist_font_size: int = 16
    playlist_bg_color: str = "#000000"
    playlist_bg_opacity: float = 0.7
    playlist_text_color: str = "#FFFFFF"
    playlist_highlight_color: str = "#FFE500"
    playlist_show_thumbnail: bool = True
    playlist_show_artist: bool = True


class OverlayPresetCreateSchema(BaseModel):
    """프리셋 생성"""
    name: str = Field(..., min_length=1, max_length=100)
    settings: OverlaySettingsSchema


class OverlayPresetUpdateSchema(BaseModel):
    """프리셋 수정"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    settings: Optional[OverlaySettingsSchema] = None


class OverlayPresetResponseSchema(BaseModel):
    """프리셋 응답"""
    id: int
    name: str
    settings: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
