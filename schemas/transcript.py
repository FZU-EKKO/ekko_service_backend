from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.transcript import TranscriptSessionStatus


class TranscriptSessionCreateRequest(BaseModel):
    channel_id: int


class TranscriptPacketRequest(BaseModel):
    sequence: int = Field(ge=0)
    audio_base64: str
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=1)
    sample_width: int = Field(default=2, ge=2, le=2)


class TranscriptSessionFinishRequest(BaseModel):
    force: bool = False


class TranscriptSessionInfo(BaseModel):
    id: int
    channel_id: int
    started_by: str
    status: TranscriptSessionStatus
    started_at: datetime
    ended_at: datetime | None
    last_error: str | None

    model_config = ConfigDict(from_attributes=True)


class TranscriptSegmentInfo(BaseModel):
    id: int
    session_id: int
    user_id: str
    seq_no: int
    start_ms: int
    end_ms: int
    text: str
    is_final: bool
    words: list[dict] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TranscriptSegmentsResponse(BaseModel):
    total: int
    segments: list[TranscriptSegmentInfo]


class TranscriptLiveStateResponse(BaseModel):
    meta: dict
    partials: dict[str, dict]
    segments: list[dict]
