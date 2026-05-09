from datetime import datetime

from pydantic import BaseModel, Field


class ChannelAnalysisRequest(BaseModel):
    prompt: str = Field(default="")
    start_time: datetime | None = None
    end_time: datetime | None = None


class ChannelAnalysisResponse(BaseModel):
    report: str
    prompt: str = ""
    source_count: int
    truncated: bool
    start_time: datetime | None = None
    end_time: datetime | None = None
