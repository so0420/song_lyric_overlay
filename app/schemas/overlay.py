from pydantic import BaseModel
from typing import Optional, List, Any


class LyricsSyncSchema(BaseModel):
    """가사 동기화 데이터"""
    prev: Optional[str] = None
    current: Optional[str] = None
    next: Optional[str] = None
    songTitle: Optional[str] = None
    artist: Optional[str] = None

    class Config:
        extra = "allow"  # 추가 필드 허용


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
