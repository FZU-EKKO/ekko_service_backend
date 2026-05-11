from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.users import Users
from models.user_channel_voice_profile import UserChannelVoiceProfile
from models.voice_message import VoiceMessages


async def select_voice_messages_by_transcription_statuses(
    db: AsyncSession,
    *,
    statuses: list[str],
):
    if not statuses:
        return []
    result = await db.execute(
        select(VoiceMessages)
        .where(VoiceMessages.transcription_status.in_(statuses))
        .order_by(VoiceMessages.created_at.asc(), VoiceMessages.id.asc())
    )
    return list(result.scalars().all())


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
    client_message_id: str | None = None,
    transcript_text: str | None = None,
    avg_amplitude: float | None = None,
    avg_frequency: float | None = None,
    avg_char_rate: float | None = None,
    is_excited: bool = False,
    transcription_status: str = "pending",
):
    voice_message = VoiceMessages(
        channel_id=channel_id,
        user_id=user_id,
        client_message_id=client_message_id,
        audio_path=audio_path,
        audio_duration_ms=audio_duration_ms,
        transcript_text=transcript_text,
        avg_amplitude=avg_amplitude,
        avg_frequency=avg_frequency,
        avg_char_rate=avg_char_rate,
        is_excited=is_excited,
        transcription_status=transcription_status,
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
        .order_by(VoiceMessages.created_at.asc(), VoiceMessages.id.asc())
    )
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return result.all()


async def select_transcript_voice_messages_by_channel(
    db: AsyncSession,
    channel_id: int,
    *,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int | None = None,
):
    query = (
        select(VoiceMessages, Users)
        .join(Users, Users.id == VoiceMessages.user_id)
        .where(
            (VoiceMessages.channel_id == channel_id)
            & (VoiceMessages.transcript_text.is_not(None))
            & (VoiceMessages.transcript_text != "")
        )
        .order_by(VoiceMessages.created_at.desc(), VoiceMessages.id.desc())
    )
    if start_time is not None:
        query = query.where(VoiceMessages.created_at >= start_time)
    if end_time is not None:
        query = query.where(VoiceMessages.created_at <= end_time)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    rows = list(result.all())
    rows.reverse()
    return rows


async def update_voice_message_transcript(
    db: AsyncSession,
    voice_message_id: int,
    *,
    transcript_text: str | None,
    transcription_status: str | None = None,
):
    record = await select_voice_message_by_id(db, voice_message_id)
    if not record:
        return None
    record.transcript_text = transcript_text
    if transcription_status is not None:
        record.transcription_status = transcription_status
    await db.commit()
    await db.refresh(record)
    return record


async def update_voice_message_analysis(
    db: AsyncSession,
    voice_message_id: int,
    *,
    avg_amplitude: float | None,
    avg_frequency: float | None,
    avg_char_rate: float | None,
    is_excited: bool,
):
    record = await select_voice_message_by_id(db, voice_message_id)
    if not record:
        return None
    record.avg_amplitude = avg_amplitude
    record.avg_frequency = avg_frequency
    record.avg_char_rate = avg_char_rate
    record.is_excited = is_excited
    await db.commit()
    await db.refresh(record)
    return record


async def update_voice_message_transcription_state(
    db: AsyncSession,
    voice_message_id: int,
    *,
    transcription_status: str,
):
    record = await select_voice_message_by_id(db, voice_message_id)
    if not record:
        return None
    record.transcription_status = transcription_status
    await db.commit()
    await db.refresh(record)
    return record


async def select_user_channel_voice_profile(
    db: AsyncSession,
    *,
    channel_id: int,
    user_id: str,
):
    result = await db.execute(
        select(UserChannelVoiceProfile).where(
            (UserChannelVoiceProfile.channel_id == channel_id)
            & (UserChannelVoiceProfile.user_id == user_id)
        )
    )
    return result.scalar_one_or_none()


async def create_or_get_user_channel_voice_profile(
    db: AsyncSession,
    *,
    channel_id: int,
    user_id: str,
):
    profile = await select_user_channel_voice_profile(db, channel_id=channel_id, user_id=user_id)
    if profile:
        return profile

    profile = UserChannelVoiceProfile(channel_id=channel_id, user_id=user_id)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_user_channel_voice_profile(
    db: AsyncSession,
    *,
    channel_id: int,
    user_id: str,
    baseline_avg_amplitude: float,
    baseline_avg_frequency: float,
    baseline_avg_char_rate: float,
    baseline_sample_count: int,
):
    profile = await create_or_get_user_channel_voice_profile(db, channel_id=channel_id, user_id=user_id)
    profile.baseline_avg_amplitude = baseline_avg_amplitude
    profile.baseline_avg_frequency = baseline_avg_frequency
    profile.baseline_avg_char_rate = baseline_avg_char_rate
    profile.baseline_sample_count = baseline_sample_count
    await db.commit()
    await db.refresh(profile)
    return profile
