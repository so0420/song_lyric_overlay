from pydantic import BaseModel, Field, field_validator
from typing import List


class TimelineRecordCreateSchema(BaseModel):
    """노래 타임라인 기록 생성 요청.

    title 은 노래하기 페이지의 '현재 틀어둔 노래' 를 기본값으로 하되,
    저장 전 사용자가 커스텀으로 바꿀 수 있다.
    경과 시간(방송 시작 기준)은 서버가 치지직 openDate 로 계산한다.
    """
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("제목을 입력해주세요.")
        return v[:255]


class TimelineRecordSchema(BaseModel):
    """단일 타임라인 기록."""
    id: int
    elapsed_seconds: int
    title: str


class TimelineBroadcastSchema(BaseModel):
    """방송(openDate) 단위로 묶은 타임라인."""
    open_date: str  # "YYYY-MM-DD HH:MM:SS" (KST)
    records: List[TimelineRecordSchema]
