from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Literal


VisibilityT = Literal["public", "private", "whitelist"]


class _MrSourceMixin(BaseModel):
    """재생 소스 (유튜브 MR 또는 업로드 음원) — 둘 중 정확히 하나.

    mr_youtube_video_id 는 원래 필수였으나, 업로드 음원이 대안 소스로 생기면서
    선택 항목이 되었다. 대신 '아무 소스도 없는 가사'가 조용히 만들어지지 않도록
    여기서 막는다 (예전에는 저장은 되고 재생만 안 되는 상태가 가능했다).
    """
    mr_youtube_video_id: Optional[str] = Field(None, max_length=255)
    audio_file_id: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one_source(self):
        has_youtube = bool(self.mr_youtube_video_id)
        has_audio = self.audio_file_id is not None
        if not has_youtube and not has_audio:
            raise ValueError("MR 유튜브 영상 또는 업로드한 음원 중 하나는 지정해야 합니다.")
        if has_youtube and has_audio:
            raise ValueError("MR 유튜브 영상과 업로드 음원은 동시에 지정할 수 없습니다.")
        return self


class LyricsCreateSchema(_MrSourceMixin):
    song_id: int
    title: Optional[str] = None
    lyrics_data: str  # JSON string or structured data
    visibility: Optional[VisibilityT] = None  # 관리자만 지정 가능, 그 외 무시
    autolink_songbook: bool = True  # 가사 없는 노래책 수록곡에 자동 연결할지 (편집기 토글)


class LyricsUpdateSchema(_MrSourceMixin):
    title: Optional[str] = None
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
