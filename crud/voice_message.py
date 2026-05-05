from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import Users
from models.voice_message import VoiceMessages


async def get_voice_message_by_client_id(db: AsyncSession, *, channel_id: int, user_id: str, client_message_id: str):
    result = await db.execute(
        select(VoiceMessages).where(
            (VoiceMessages.channel_id == channel_id)
            & (VoiceMessages.user_id == user_id)
            & (VoiceMessages.client_message_id == client_message_id)
        )
    )
    return result.scalar_one_or_none()


async def select_voice_message_by_id(db: AsyncSession, voice_message_id: int):
    result = await db.execute(select(VoiceMessages).where(VoiceMessages.id == voice_message_id))
    return result.scalar_one_or_none()


async def create_voice_message(
    db: AsyncSession,
    *,
    channel_id: int,
    user_id: str,
    audio_path: str,
    audio_duration_ms: int,
    audio_format: str,
    mime_type: str | None,
    file_size: int,
    client_message_id: str | None = None,
    transcript_text: str | None = None,
    waveform: list[int] | None = None,
):
    voice_message = VoiceMessages(
        channel_id=channel_id,
        user_id=user_id,
        client_message_id=client_message_id,
        audio_path=audio_path,
        audio_duration_ms=audio_duration_ms,
        audio_format=audio_format,
        mime_type=mime_type,
        file_size=file_size,
        transcript_text=transcript_text,
        waveform=waveform,
    )
    db.add(voice_message)
    await db.commit()
    await db.refresh(voice_message)
    return voice_message


async def count_voice_messages_by_channel(db: AsyncSession, channel_id: int):
    result = await db.execute(
        select(func.count(VoiceMessages.id)).where(VoiceMessages.channel_id == channel_id)
    )
    return result.scalar() or 0


async def select_voice_messages_by_channel(
    db: AsyncSession,
    channel_id: int,
    *,
    offset: int | None = None,
    limit: int | None = None,
):
    query = (
        select(VoiceMessages, Users)
        .join(Users, Users.id == VoiceMessages.user_id)
        .where(VoiceMessages.channel_id == channel_id)
        .order_by(VoiceMessages.created_at.desc(), VoiceMessages.id.desc())
    )
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return result.all()


async def update_voice_message_transcript(
    db: AsyncSession,
    voice_message_id: int,
    *,
    transcript_text: str | None,
):
    record = await select_voice_message_by_id(db, voice_message_id)
    if not record:
        return None
    record.transcript_text = transcript_text
    await db.commit()
    await db.refresh(record)
    return record
