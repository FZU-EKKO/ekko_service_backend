from pydantic import BaseModel, Field


class ChannelAnalysisRequest(BaseModel):
    prompt: str = Field(default="")


class ChannelAnalysisResponse(BaseModel):
    report: str
    prompt: str = ""
    source_count: int
    truncated: bool
