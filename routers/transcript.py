from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import channel, transcript
from models.transcript import TranscriptSessionStatus
from models.users import Users
from schemas.transcript import (
    TranscriptPacketRequest,
    TranscriptSegmentsResponse,
    TranscriptSessionCreateRequest,
    TranscriptSessionFinishRequest,
    TranscriptSessionInfo,
    TranscriptSegmentInfo,
)
from utils.auth import get_current_user
from utils.response import success_response
from utils.transcript_runtime import transcript_runtime


ekko = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


@ekko.post("/sessions") #创建会话
async def create_session(
    req: TranscriptSessionCreateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Create one transcript session bound to a voice channel.
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel not found")

    created = await transcript.create_transcript_session(db, channel_id=req.channel_id, started_by=user.id)
    await transcript_runtime.register_session(created.id)
    return success_response(
        message="Transcript session created",
        data=TranscriptSessionInfo.model_validate(created),
    )


@ekko.post("/sessions/{session_id}/packets")
async def submit_packet(
    session_id: int,
    req: TranscriptPacketRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Accept one frontend audio packet and hand it to the runtime buffer.
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")
    if current_session.status != TranscriptSessionStatus.Active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Transcript session is not active")

    try:
        await transcript_runtime.submit_packet(
            session_id=session_id,
            user_id=user.id,
            audio_base64=req.audio_base64,
            sample_rate=req.sample_rate,
            channels=req.channels,
            sample_width=req.sample_width,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return success_response(
        message="Audio packet accepted",
        data={"session_id": session_id, "sequence": req.sequence},
    )


@ekko.post("/sessions/{session_id}/finish")
async def finish_session(
    session_id: int,
    req: TranscriptSessionFinishRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Stop accepting new packets and flush buffered speech to ASR.
    _ = req
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")
    if current_session.started_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the session owner can finish the session")
    if current_session.status not in (TranscriptSessionStatus.Active, TranscriptSessionStatus.Processing):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Transcript session is already finalized")

    await transcript_runtime.finish_session(session_id)
    await db.refresh(current_session)
    return success_response(
        message="Transcript session finishing",
        data=TranscriptSessionInfo.model_validate(current_session),
    )


@ekko.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query the session status so frontend can poll progress.
    _ = user
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")
    return success_response(
        message="Transcript session fetched",
        data=TranscriptSessionInfo.model_validate(current_session),
    )


@ekko.get("/sessions/{session_id}/segments")
async def get_segments(
    session_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Read finalized transcript segments already persisted in MySQL.
    _ = user
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")

    rows = await transcript.select_transcript_segments(db, session_id)
    return success_response(
        message="Transcript segments fetched",
        data=TranscriptSegmentsResponse(
            total=len(rows),
            segments=[TranscriptSegmentInfo.model_validate(item) for item in rows],
        ),
    )
