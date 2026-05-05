from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VoiceMessageUserInfo(BaseModel):
    id: str
    nick_name: str
    avatar: str | None = None


class VoiceMessageInfo(BaseModel):
    id: int
    channel_id: int
    user_id: str
    client_message_id: str | None = None
    audio_path: str
    audio_duration_ms: int
    audio_format: str
    mime_type: str | None = None
    file_size: int
    transcript_text: str | None = None
    waveform: list[int] | None = None
    created_at: datetime
    updated_at: datetime
    user: VoiceMessageUserInfo


class VoiceMessageUploadResponse(BaseModel):
    voice_message: VoiceMessageInfo


class VoiceMessagePage(BaseModel):
    total: int
    voice_messages: list[VoiceMessageInfo]


class VoiceMessageRecord(BaseModel):
    id: int
    channel_id: int
    user_id: str
    client_message_id: str | None = None
    audio_path: str
    audio_duration_ms: int
    audio_format: str
    mime_type: str | None = None
    file_size: int
    transcript_text: str | None = None
    waveform: list[int] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
