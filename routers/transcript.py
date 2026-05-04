import asyncio
import json
from datetime import datetime

import websockets
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.asr_config import ASR_LANGUAGE, ASR_REMOTE_TOKEN, ASR_REMOTE_WS_URL
from config.cache_config import get_cache, set_cache
from config.db_config import AsyncSessionLocal, get_db
from crud import channel, transcript, users
from models.transcript import TranscriptSessionStatus
from models.users import Users
from schemas.transcript import (
    TranscriptPacketRequest,
    TranscriptSegmentsResponse,
    TranscriptSessionCreateRequest,
    TranscriptSessionFinishRequest,
    TranscriptSessionInfo,
    TranscriptLiveStateResponse,
    TranscriptSegmentInfo,
)
from utils.auth import get_current_user
from utils.transcript_cache import (
    clear_partial,
    decrement_active_streams,
    get_live_state,
    increment_active_streams,
    next_sequence_number,
    next_seq_key,
    push_final_segment,
    set_partial,
    set_session_meta,
)
from utils.response import success_response
from utils.transcript_runtime import transcript_runtime


ekko = APIRouter(prefix="/api/transcripts", tags=["transcripts"])

async def _get_user_from_token(token: str):
    async with AsyncSessionLocal() as db:
        return await users.get_user_by_token(db, token)


async def _seed_seq_counter_if_needed(session_id: int) -> None:
    existing = await get_cache(next_seq_key(session_id))
    if existing is not None:
        return
    async with AsyncSessionLocal() as db:
        count = await transcript.count_transcript_segments(db, session_id)
    await set_cache(next_seq_key(session_id), count, expire=60 * 60)


async def _mark_session_processing(session_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await transcript.update_transcript_session_status(
            db,
            session_id,
            status=TranscriptSessionStatus.Processing,
            ended_at=datetime.now(),
        )
    await set_session_meta(session_id, status=TranscriptSessionStatus.Processing.value)


async def _maybe_complete_streaming_session(session_id: int) -> None:
    try:
        remaining = await decrement_active_streams(session_id)
    except Exception:
        remaining = 0

    if remaining > 0:
        return

    async with AsyncSessionLocal() as db:
        current_session = await transcript.select_transcript_session(db, session_id)
        if not current_session or current_session.status == TranscriptSessionStatus.Failed:
            return
        await transcript.update_transcript_session_status(
            db,
            session_id,
            status=TranscriptSessionStatus.Completed,
            ended_at=current_session.ended_at or datetime.now(),
        )
    await set_session_meta(session_id, status=TranscriptSessionStatus.Completed.value)


async def _persist_final_segment(session_id: int, event: dict) -> dict:
    user_id = str(event["user_id"])
    seq_no = await next_sequence_number(session_id)
    if seq_no is None:
        raise RuntimeError("Failed to allocate transcript sequence number")

    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "seq_no": seq_no,
        "start_ms": int(event.get("start_ms", 0)),
        "end_ms": int(event.get("end_ms", 0)),
        "text": str(event.get("text", "")).strip(),
        "words": event.get("words") if isinstance(event.get("words"), list) else None,
        "is_final": True,
    }

    async with AsyncSessionLocal() as db:
        segment = await transcript.create_transcript_segment(
            db,
            session_id=session_id,
            user_id=user_id,
            seq_no=seq_no,
            start_ms=payload["start_ms"],
            end_ms=payload["end_ms"],
            text=payload["text"],
            is_final=True,
            words=payload["words"],
        )

    payload["id"] = segment.id
    await clear_partial(session_id, user_id)
    await push_final_segment(session_id, payload)
    return payload


async def _stream_events_between_client_and_asr(websocket: WebSocket, session_id: int, user_id: str) -> None:
    if not ASR_REMOTE_WS_URL:
        raise RuntimeError("EKKO_ASR_REMOTE_WS_URL is not configured")

    upstream_url = ASR_REMOTE_WS_URL
    headers = {}
    if ASR_REMOTE_TOKEN:
        headers["Authorization"] = f"Bearer {ASR_REMOTE_TOKEN}"

    await _seed_seq_counter_if_needed(session_id)
    await increment_active_streams(session_id)

    stream_closed = False

    async with websockets.connect(upstream_url, additional_headers=headers, proxy=None) as asr_ws:
        await asr_ws.send(
            json.dumps(
                {
                    "type": "start_session",
                    "session_id": session_id,
                    "user_id": user_id,
                    "sample_rate": 16000,
                    "channels": 1,
                    "sample_width": 2,
                    "language": ASR_LANGUAGE,
                }
            )
        )

        async def frontend_to_asr() -> None:
            nonlocal stream_closed
            try:
                while True:
                    message = await websocket.receive_text()
                    payload = json.loads(message)
                    message_type = str(payload.get("type", "")).strip()
                    if message_type == "audio_chunk":
                        await asr_ws.send(json.dumps(payload))
                        continue
                    if message_type == "end_stream":
                        await _mark_session_processing(session_id)
                        await asr_ws.send(json.dumps({"type": "end_stream"}))
                        return
            except WebSocketDisconnect:
                if not stream_closed:
                    await _mark_session_processing(session_id)
                    try:
                        await asr_ws.send(json.dumps({"type": "end_stream"}))
                    except Exception:
                        return

        async def asr_to_frontend() -> None:
            nonlocal stream_closed
            while True:
                raw = await asr_ws.recv()
                event = json.loads(raw)
                event_type = str(event.get("type", "")).strip()

                if event_type == "partial_result":
                    partial_payload = {
                        "text": event.get("text", ""),
                        "words": event.get("words", []),
                        "start_ms": event.get("start_ms", 0),
                        "end_ms": event.get("end_ms", 0),
                        "revision": event.get("revision", 0),
                    }
                    await set_partial(session_id, user_id, partial_payload)
                    await websocket.send_json(event)
                    continue

                if event_type == "final_result":
                    stored = await _persist_final_segment(session_id, event)
                    event["seq_no"] = stored["seq_no"]
                    event["id"] = stored["id"]
                    await websocket.send_json(event)
                    continue

                if event_type == "stream_closed":
                    stream_closed = True
                    await websocket.send_json(event)
                    await _maybe_complete_streaming_session(session_id)
                    return

                if event_type == "error":
                    async with AsyncSessionLocal() as db:
                        await transcript.update_transcript_session_status(
                            db,
                            session_id,
                            status=TranscriptSessionStatus.Failed,
                            last_error=str(event.get("detail", "ASR stream error")),
                        )
                    await set_session_meta(
                        session_id,
                        status=TranscriptSessionStatus.Failed.value,
                        last_error=str(event.get("detail", "ASR stream error")),
                    )
                    await websocket.send_json(event)
                    return

                await websocket.send_json(event)

        await asyncio.gather(frontend_to_asr(), asr_to_frontend())


@ekko.post("/sessions")
async def create_session(
    req: TranscriptSessionCreateRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_channel = await channel.select_channel_id(db, req.channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel not found")

    created = await transcript.create_transcript_session(db, channel_id=req.channel_id, started_by=user.id)
    await transcript_runtime.register_session(created.id)
    await set_session_meta(created.id, status=TranscriptSessionStatus.Active.value, channel_id=req.channel_id)
    return success_response(
        message="Transcript session created",
        data=TranscriptSessionInfo.model_validate(created),
    )


@ekko.websocket("/ws/{session_id}")
async def transcript_stream(websocket: WebSocket, session_id: int, token: str = Query(...)):
    user = await _get_user_from_token(token)
    if not user:
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        current_session = await transcript.select_transcript_session(db, session_id)
        if not current_session:
            await websocket.close(code=4404)
            return
        if current_session.status != TranscriptSessionStatus.Active:
            await websocket.close(code=4409, reason="Transcript session is not active")
            return

    await websocket.accept()

    try:
        await _stream_events_between_client_and_asr(websocket, session_id, user.id)
    except WebSocketDisconnect:
        await _maybe_complete_streaming_session(session_id)
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            await transcript.update_transcript_session_status(
                db,
                session_id,
                status=TranscriptSessionStatus.Failed,
                last_error=str(exc),
            )
        await set_session_meta(session_id, status=TranscriptSessionStatus.Failed.value, last_error=str(exc))
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
        await _maybe_complete_streaming_session(session_id)
        await websocket.close(code=1011)


@ekko.post("/sessions/{session_id}/packets")
async def submit_packet(
    session_id: int,
    req: TranscriptPacketRequest,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    _ = user
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")
    return success_response(
        message="Transcript session fetched",
        data=TranscriptSessionInfo.model_validate(current_session),
    )


@ekko.get("/sessions/{session_id}/live_state")
async def get_live_transcript_state(
    session_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    current_session = await transcript.select_transcript_session(db, session_id)
    if not current_session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transcript session not found")

    state = await get_live_state(session_id)
    return success_response(
        message="Transcript live state fetched",
        data=TranscriptLiveStateResponse(**state),
    )


@ekko.get("/sessions/{session_id}/segments")
async def get_segments(
    session_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
