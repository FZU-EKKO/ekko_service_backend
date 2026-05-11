from __future__ import annotations

import asyncio
import logging
import re

from config.db_config import AsyncSessionLocal
from crud import voice_message
from utils.voice_message_excitement import analyze_and_persist_voice_message_excitement
from utils.voice_message_transcriber import transcribe_uploaded_audio


logger = logging.getLogger("ekko.voice_message_transcription_queue")

TRANSCRIPTION_PENDING = "pending"
TRANSCRIPTION_PROCESSING = "processing"
TRANSCRIPTION_DONE = "done"
TRANSCRIPTION_FAILED = "failed"
TRANSCRIPTION_DROPPED = "dropped"

ACTIVE_TRANSCRIPTION_STATUSES = [
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
]
FINAL_TRANSCRIPTION_STATUSES = [
    TRANSCRIPTION_DONE,
    TRANSCRIPTION_FAILED,
    TRANSCRIPTION_DROPPED,
]
UNRECOGNIZED_SPEECH_TEXT = "[unrecognized speech]"
MAX_TRANSCRIPTION_ERROR_LENGTH = 500

_queue: asyncio.Queue[int | None] | None = None
_worker_task: asyncio.Task[None] | None = None
_enqueued_ids: set[int] = set()


def _normalize_transcript_text(transcript_text: str | None) -> str | None:
    normalized = (transcript_text or "").strip()
    return normalized or None


def _is_unrecognized_speech(transcript_text: str | None) -> bool:
    normalized = _normalize_transcript_text(transcript_text)
    return bool(normalized and normalized.casefold() == UNRECOGNIZED_SPEECH_TEXT.casefold())


def _trim_error_message(message: str) -> str:
    normalized = re.sub(r"\s+", " ", str(message or "").strip())
    if len(normalized) <= MAX_TRANSCRIPTION_ERROR_LENGTH:
        return normalized
    return normalized[: MAX_TRANSCRIPTION_ERROR_LENGTH - 3] + "..."


async def enqueue_voice_message_transcription(voice_message_id: int) -> bool:
    global _queue
    if _queue is None:
        return False
    if voice_message_id in _enqueued_ids:
        return False
    _enqueued_ids.add(voice_message_id)
    await _queue.put(voice_message_id)
    return True


async def initialize_voice_message_transcription_queue() -> None:
    global _queue, _worker_task
    if _queue is None:
        _queue = asyncio.Queue()
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_voice_message_transcription_worker_loop())
    await _restore_pending_voice_message_transcriptions()


async def shutdown_voice_message_transcription_queue() -> None:
    global _queue, _worker_task
    if _queue is not None:
        await _queue.put(None)
    if _worker_task is not None:
        await _worker_task
    _queue = None
    _worker_task = None
    _enqueued_ids.clear()


async def _restore_pending_voice_message_transcriptions() -> None:
    async with AsyncSessionLocal() as db:
        records = await voice_message.select_voice_messages_by_transcription_statuses(
            db,
            statuses=ACTIVE_TRANSCRIPTION_STATUSES,
        )
    for record in records:
        await enqueue_voice_message_transcription(record.id)
    if records:
        logger.info("restored_pending_voice_message_transcriptions count=%s", len(records))


async def _voice_message_transcription_worker_loop() -> None:
    assert _queue is not None
    while True:
        voice_message_id = await _queue.get()
        if voice_message_id is None:
            _queue.task_done()
            break

        try:
            await _process_voice_message_transcription(voice_message_id)
        except Exception:
            logger.exception("voice_message_transcription_worker_failed id=%s", voice_message_id)
        finally:
            _enqueued_ids.discard(voice_message_id)
            _queue.task_done()


async def _process_voice_message_transcription(voice_message_id: int) -> None:
    async with AsyncSessionLocal() as db:
        record = await voice_message.select_voice_message_by_id(db, voice_message_id)
        if not record:
            return
        if record.transcription_status == TRANSCRIPTION_DONE:
            return
        if record.transcription_status == TRANSCRIPTION_DROPPED:
            return

        record = await voice_message.update_voice_message_transcription_state(
            db,
            voice_message_id,
            transcription_status=TRANSCRIPTION_PROCESSING,
        )
        if not record:
            return
        audio_path = record.audio_path
        channel_id = record.channel_id
        user_id = record.user_id

    try:
        result = await asyncio.to_thread(transcribe_uploaded_audio, audio_path)
        transcript_text = _normalize_transcript_text(result.get("text"))
    except Exception as exc:
        error_message = _trim_error_message(str(exc) or repr(exc))
        async with AsyncSessionLocal() as db:
            await voice_message.update_voice_message_transcription_state(
                db,
                voice_message_id,
                transcription_status=TRANSCRIPTION_FAILED,
            )
        logger.warning("voice_message_transcription_failed id=%s detail=%s", voice_message_id, error_message)
        return

    if _is_unrecognized_speech(transcript_text):
        async with AsyncSessionLocal() as db:
            await voice_message.update_voice_message_transcription_state(
                db,
                voice_message_id,
                transcription_status=TRANSCRIPTION_DROPPED,
            )
        logger.info("voice_message_transcription_dropped id=%s reason=unrecognized_speech", voice_message_id)
        return

    async with AsyncSessionLocal() as db:
        updated = await voice_message.update_voice_message_transcript(
            db,
            voice_message_id,
            transcript_text=transcript_text,
            transcription_status=TRANSCRIPTION_DONE,
        )
        if not updated:
            return
        try:
            await analyze_and_persist_voice_message_excitement(
                db,
                voice_message_id=updated.id,
                channel_id=channel_id,
                user_id=user_id,
                relative_audio_path=audio_path,
            )
        except Exception as exc:
            logger.warning(
                "voice_message_excitement_analysis_failed id=%s path=%s detail=%s",
                updated.id,
                updated.audio_path,
                exc,
            )

    logger.info("voice_message_transcription_done id=%s text_chars=%s", voice_message_id, len(transcript_text or ""))
