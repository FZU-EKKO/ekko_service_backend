from __future__ import annotations

import asyncio
import base64
import json
import logging
from urllib import request
from urllib.error import HTTPError, URLError

from config.db_config import AsyncSessionLocal
from config.voice_message_asr_config import (
    VOICE_MESSAGE_ASR_CALLBACK_TOKEN,
    VOICE_MESSAGE_ASR_CALLBACK_URL,
    VOICE_MESSAGE_ASR_LANGUAGE,
    VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
    VOICE_MESSAGE_ASR_RESTORE_INTERVAL_SECONDS,
    VOICE_MESSAGE_ASR_REMOTE_TIMEOUT_SECONDS,
    VOICE_MESSAGE_ASR_REMOTE_TOKEN,
)
from crud import voice_message
from utils.network import should_bypass_proxy
from utils.voice_message_status import (
    ACTIVE_TRANSCRIPTION_STATUSES,
)
from utils.voice_message_transcriber import resolve_audio_format, resolve_uploaded_audio_path


logger = logging.getLogger("ekko.voice_message_transcription_queue")

_restore_task: asyncio.Task[None] | None = None


def _open_json_request(*, url: str, payload: dict, headers: dict[str, str]) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    opener = request.build_opener(request.ProxyHandler({})) if should_bypass_proxy(url) else request.build_opener()
    with opener.open(req, timeout=VOICE_MESSAGE_ASR_REMOTE_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _enqueue_remote_transcription(
    *,
    voice_message_id: int,
    audio_bytes: bytes,
    audio_format: str,
) -> bool:
    if not VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL:
        raise ValueError("EKKO_ASR_REMOTE_QUEUE_URL is not configured")
    if not VOICE_MESSAGE_ASR_CALLBACK_URL:
        raise ValueError("EKKO_ASR_CALLBACK_URL is not configured")
    if not VOICE_MESSAGE_ASR_CALLBACK_TOKEN:
        raise ValueError("EKKO_ASR_CALLBACK_TOKEN is not configured")
    if not audio_bytes:
        raise ValueError("Uploaded audio file is empty")

    headers = {"Content-Type": "application/json"}
    if VOICE_MESSAGE_ASR_REMOTE_TOKEN:
        headers["Authorization"] = f"Bearer {VOICE_MESSAGE_ASR_REMOTE_TOKEN}"

    payload = {
        "voice_message_id": voice_message_id,
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_format": audio_format,
        "language": VOICE_MESSAGE_ASR_LANGUAGE,
        "callback_url": VOICE_MESSAGE_ASR_CALLBACK_URL,
        "callback_token": VOICE_MESSAGE_ASR_CALLBACK_TOKEN,
    }

    logger.info(
        "voice_message_transcription_enqueue request url=%s id=%s format=%s bytes=%s",
        VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
        voice_message_id,
        audio_format,
        len(audio_bytes),
    )
    try:
        data = _open_json_request(
            url=VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
            payload=payload,
            headers=headers,
        )
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.error(
            "voice_message_transcription_enqueue http_error url=%s id=%s status=%s body=%s",
            VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
            voice_message_id,
            exc.code,
            error_body,
        )
        raise RuntimeError(f"ASR enqueue HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        logger.error(
            "voice_message_transcription_enqueue connection_failed url=%s id=%s reason=%s",
            VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
            voice_message_id,
            exc.reason,
        )
        raise RuntimeError(f"ASR enqueue connection failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        logger.error(
            "voice_message_transcription_enqueue invalid_json_response url=%s id=%s",
            VOICE_MESSAGE_ASR_REMOTE_QUEUE_URL,
            voice_message_id,
        )
        raise RuntimeError("ASR enqueue returned invalid JSON") from exc

    queued = bool(data.get("queued"))
    logger.info(
        "voice_message_transcription_enqueue success id=%s queued=%s",
        voice_message_id,
        queued,
    )
    return queued


async def enqueue_voice_message_transcription(
    voice_message_id: int,
    *,
    audio_bytes: bytes | None = None,
    audio_format: str | None = None,
) -> bool:
    if audio_bytes is None:
        audio_bytes, resolved_format = await _load_audio_by_id(voice_message_id)
        audio_format = audio_format or resolved_format
    elif not audio_format:
        raise ValueError("audio_format is required when audio_bytes is provided")

    return await asyncio.to_thread(
        _enqueue_remote_transcription,
        voice_message_id=voice_message_id,
        audio_bytes=audio_bytes,
        audio_format=str(audio_format or "wav"),
    )


async def _load_audio_by_id(voice_message_id: int) -> tuple[bytes, str]:
    async with AsyncSessionLocal() as db:
        record = await voice_message.select_voice_message_by_id(db, voice_message_id)
        if not record:
            raise FileNotFoundError(f"Voice message {voice_message_id} does not exist")
        relative_path = record.audio_path

    resolved_path = resolve_uploaded_audio_path(relative_path)
    audio_bytes = await asyncio.to_thread(resolved_path.read_bytes)
    return audio_bytes, resolve_audio_format(resolved_path)


async def initialize_voice_message_transcription_queue() -> None:
    global _restore_task
    await _restore_pending_voice_message_transcriptions()
    if _restore_task is None or _restore_task.done():
        _restore_task = asyncio.create_task(_restore_pending_loop())


async def shutdown_voice_message_transcription_queue() -> None:
    global _restore_task
    if _restore_task is None:
        return
    _restore_task.cancel()
    try:
        await _restore_task
    except asyncio.CancelledError:
        pass
    _restore_task = None


async def _restore_pending_voice_message_transcriptions() -> None:
    async with AsyncSessionLocal() as db:
        records = await voice_message.select_voice_messages_by_transcription_statuses(
            db,
            statuses=ACTIVE_TRANSCRIPTION_STATUSES,
        )

    restored = 0
    for record in records:
        try:
            queued = await enqueue_voice_message_transcription(record.id)
        except Exception:
            logger.exception("restore_pending_voice_message_transcription_failed id=%s", record.id)
            continue
        if queued:
            restored += 1

    if records:
        logger.info(
            "restored_pending_voice_message_transcriptions total=%s queued=%s",
            len(records),
            restored,
        )


async def _restore_pending_loop() -> None:
    interval = max(5, VOICE_MESSAGE_ASR_RESTORE_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(interval)
        try:
            await _restore_pending_voice_message_transcriptions()
        except Exception:
            logger.exception("restore_pending_voice_message_transcriptions_loop_failed")
