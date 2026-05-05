from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.channel import ChannelMembers, Channels, ChannelType
from models.user_channel_voice_profile import UserChannelVoiceProfile
from models.voice_message import VoiceMessages


async def select_channel_id(db: AsyncSession, channel_id: int):
    result = await db.execute(select(Channels).where(Channels.id == channel_id))
    return result.scalar_one_or_none()


async def select_channel_member(db: AsyncSession, channel_id: int, member_id: str):
    result = await db.execute(
        select(ChannelMembers).where(
            (ChannelMembers.channel_id == channel_id) & (ChannelMembers.member_id == member_id)
        )
    )
    return result.scalar_one_or_none()


async def create_channel(
    db: AsyncSession,
    *,
    domain_id: str,
    create_id: str,
    channel_name: str,
    description: str | None,
    max_capacity: int,
    channel_type: ChannelType,
):
    channel = Channels(
        domain_id=domain_id,
        create_id=create_id,
        channel_name=channel_name,
        description=description,
        max_capacity=max_capacity,
        channel_type=channel_type,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def select_channels_by_domain(
    db: AsyncSession,
    domain_id: str,
    *,
    offset: int | None = None,
    limit: int | None = None,
):
    total_result = await db.execute(select(func.count(Channels.id)).where(Channels.domain_id == domain_id))
    total = total_result.scalar() or 0

    query = select(Channels).where(Channels.domain_id == domain_id).order_by(Channels.id.asc())
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return total, result.scalars().all()


async def update_channel(db: AsyncSession, channel_id: int, payload: dict):
    if not payload:
        return await select_channel_id(db, channel_id)
    result = await db.execute(update(Channels).where(Channels.id == channel_id).values(**payload))
    await db.commit()
    if result.rowcount == 0:
        return None
    return await select_channel_id(db, channel_id)


async def delete_channel(db: AsyncSession, channel_id: int):
    current_channel = await select_channel_id(db, channel_id)
    if not current_channel:
        return False
    await db.execute(delete(VoiceMessages).where(VoiceMessages.channel_id == channel_id))
    await db.execute(delete(UserChannelVoiceProfile).where(UserChannelVoiceProfile.channel_id == channel_id))
    await db.execute(delete(ChannelMembers).where(ChannelMembers.channel_id == channel_id))
    await db.delete(current_channel)
    await db.commit()
    return True


async def join_channel(
    db: AsyncSession,
    *,
    channel: Channels,
    member_id: str,
):
    if await select_channel_member(db, channel.id, member_id):
        return None
    member = ChannelMembers(
        channel_id=channel.id,
        member_id=member_id,
        last_active_time=datetime.now(),
    )
    db.add(member)
    channel.current_voice_count += 1
    await db.commit()
    await db.refresh(member)
    await db.refresh(channel)
    return member


async def leave_channel(
    db: AsyncSession,
    *,
    channel: Channels,
    member_id: str,
):
    member = await select_channel_member(db, channel.id, member_id)
    if not member:
        return False
    await db.delete(member)
    channel.current_voice_count = max(0, channel.current_voice_count - 1)
    await db.commit()
    return True


async def count_channel_members(db: AsyncSession, channel_id: int):
    result = await db.execute(
        select(func.count(ChannelMembers.member_id)).where(ChannelMembers.channel_id == channel_id)
    )
    return result.scalar() or 0


async def select_channel_members(
    db: AsyncSession,
    channel_id: int,
    *,
    offset: int | None = None,
    limit: int | None = None,
):
    total = await count_channel_members(db, channel_id)
    query = select(ChannelMembers).where(ChannelMembers.channel_id == channel_id)
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return total, result.scalars().all()


async def update_channel_member_state(
    db: AsyncSession,
    *,
    channel_id: int,
    member_id: str,
    microphone_state: bool | None = None,
    speaker_state: bool | None = None,
):
    member = await select_channel_member(db, channel_id, member_id)
    if not member:
        return None

    if microphone_state is not None:
        member.microphone_state = microphone_state
    if speaker_state is not None:
        member.speaker_state = speaker_state
    member.last_active_time = datetime.now()

    await db.commit()
    await db.refresh(member)
    return member
