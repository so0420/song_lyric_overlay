from pydantic import BaseModel
from typing import Optional


class LyricsCreateSchema(BaseModel):
    song_id: int
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str  # JSON string or structured data


class LyricsUpdateSchema(BaseModel):
    title: Optional[str] = None
    mr_youtube_video_id: str
    lyrics_data: str
