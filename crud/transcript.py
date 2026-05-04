from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.transcript import TranscriptSegments, TranscriptSessions, TranscriptSessionStatus


async def create_transcript_session(db: AsyncSession, *, channel_id: int, started_by: str):
    session = TranscriptSessions(channel_id=channel_id, started_by=started_by)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def select_transcript_session(db: AsyncSession, session_id: int):
    result = await db.execute(select(TranscriptSessions).where(TranscriptSessions.id == session_id))
    return result.scalar_one_or_none()


async def update_transcript_session_status(
    db: AsyncSession,
    session_id: int,
    *,
    status: TranscriptSessionStatus,
    ended_at: datetime | None = None,
    last_error: str | None = None,
):
    session = await select_transcript_session(db, session_id)
    if not session:
        return None
    session.status = status
    if ended_at is not None:
        session.ended_at = ended_at
    if last_error is not None:
        session.last_error = last_error
    await db.commit()
    await db.refresh(session)
    return session


async def create_transcript_segment(
    db: AsyncSession,
    *,
    session_id: int,
    user_id: str,
    seq_no: int,
    start_ms: int,
    end_ms: int,
    text: str,
    is_final: bool = True,
    words: list[dict] | None = None,
):
    segment = TranscriptSegments(
        session_id=session_id,
        user_id=user_id,
        seq_no=seq_no,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        is_final=is_final,
        words=words,
    )
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    return segment


async def select_transcript_segments(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(TranscriptSegments)
        .where(TranscriptSegments.session_id == session_id)
        .order_by(TranscriptSegments.seq_no.asc(), TranscriptSegments.id.asc())
    )
    return result.scalars().all()


async def count_transcript_segments(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(func.count(TranscriptSegments.id)).where(TranscriptSegments.session_id == session_id)
    )
    return result.scalar() or 0
