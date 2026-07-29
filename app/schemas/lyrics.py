from pydantic import BaseModel, Field
from typing import Optional, List, Literal


VisibilityT = Literal["public", "private", "whitelist"]


class LyricsCreateSchema(BaseModel):
    song_id: int
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str  # JSON string or structured data
    visibility: Optional[VisibilityT] = None  # 관리자만 지정 가능, 그 외 무시
    autolink_songbook: bool = True  # 가사 없는 노래책 수록곡에 자동 연결할지 (편집기 토글)


class LyricsUpdateSchema(BaseModel):
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str
    visibility: Optional[VisibilityT] = None  # 관리자만 지정 가능, 그 외 무시


class LyricsMemoSchema(BaseModel):
    memo: str


class VisibilityPatchSchema(BaseModel):
    visibility: VisibilityT


class WhitelistPutSchema(BaseModel):
    user_ids: List[int] = Field(default_factory=list)


class UserSearchResultSchema(BaseModel):
    id: int
    name: Optional[str] = None
    email: str
