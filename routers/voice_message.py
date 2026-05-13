import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from config.voice_message_asr_config import VOICE_MESSAGE_ASR_CALLBACK_TOKEN
from crud import channel, domain, voice_message
from models.channel import ChannelType
from models.users import Users
from schemas.voice_message import (
    VoiceMessageInfo,
    VoiceMessagePage,
    VoiceMessageTranscriptionCallbackRequest,
    VoiceMessageUserInfo,
)
from utils.auth import get_current_user
from utils.audio_event_classifier import classify_audio_event_bytes, should_drop_audio_event
from utils.file_storage import save_voice_message_bytes
from utils.response import success_response
from utils.voice_message_excitement import analyze_and_persist_voice_message_excitement
from utils.voice_message_status import (
    TRANSCRIPTION_DONE,
    TRANSCRIPTION_DROPPED,
    TRANSCRIPTION_FAILED,
    TRANSCRIPTION_PENDING,
    TRANSCRIPTION_PROCESSING,
)
from utils.voice_message_transcription_queue import (
    enqueue_voice_message_transcription,
)


ekko = APIRouter(prefix="/api/voice-messages", tags=["voice_messages"])
logger = logging.getLogger("ekko.voice_messages")
UNRECOGNIZED_SPEECH_TEXT = "[unrecognized speech]"


def _summarize_audio_event(classification: dict | None) -> str:
    if not classification:
        return "audio_event=disabled"

    top_labels = classification.get("top_labels")
    if isinstance(top_labels, list):
        top_summary = ",".join(
            f"{item.get('label')}:{float(item.get('score') or 0.0):.3f}"
            for item in top_labels[:3]
            if isinstance(item, dict)
        )
    else:
        top_summary = ""

    return (
        "audio_event="
        f"dominant={classification.get('dominant_label')} "
        f"is_speech={bool(classification.get('is_speech'))} "
        f"should_drop={bool(classification.get('should_drop'))} "
        f"speech={float(classification.get('speech_score') or 0.0):.4f} "
        f"breathing={float(classification.get('breathing_score') or 0.0):.4f} "
        f"noise={float(classification.get('noise_score') or 0.0):.4f} "
        f"top=[{top_summary}]"
    )


def _classify_sentence_wav_bytes(
    *,
    wav_bytes: bytes,
    channel_id: int,
    user_id: str,
    speech_ms: int,
    log_prefix: str,
) -> tuple[bool, dict | None]:
    classification = None
    try:
        classification = classify_audio_event_bytes(wav_bytes, audio_format="wav")
    except Exception as exc:
        logger.warning(
            "%s_audio_event_classify_failed channel_id=%s user_id=%s detail=%s",
            log_prefix,
            channel_id,
            user_id,
            exc,
        )

    dropped = should_drop_audio_event(classification)
    logger.info(
        "%s_%s channel_id=%s user_id=%s speech_ms=%s %s",
        log_prefix,
        "dropped_by_audio_event" if dropped else "allowed_by_audio_event",
        channel_id,
        user_id,
        speech_ms,
        _summarize_audio_event(classification),
    )
    return dropped, classification


async def _assert_channel_access(db: AsyncSession, *, channel_id: int, user_id: str):
    current_channel = await channel.select_channel_id(db, channel_id)
    if not current_channel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Channel does not exist")

    member = await domain.select_domain_members(db, current_channel.domain_id, user_id)
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You are not a member of this domain")

    if current_channel.channel_type == ChannelType.Text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Text channel does not support voice messages")

    return current_channel


async def _assert_voice_message_access(db: AsyncSession, *, voice_message_id: int, user_id: str):
    record = await voice_message.select_voice_message_by_id(db, voice_message_id)
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Voice message does not exist")
    await _assert_channel_access(db, channel_id=record.channel_id, user_id=user_id)
    return record


async def _get_sender(db: AsyncSession, user_id: str) -> Users:
    result = await db.execute(select(Users).where(Users.id == user_id))
    return result.scalar_one()


def _build_voice_message_info(record, sender: Users) -> VoiceMessageInfo:
    return VoiceMessageInfo(
        id=record.id,
        channel_id=record.channel_id,
        user_id=record.user_id,
        client_message_id=record.client_message_id,
        audio_path=record.audio_path,
        audio_duration_ms=record.audio_duration_ms,
        transcript_text=record.transcript_text,
        avg_amplitude=record.avg_amplitude,
        avg_frequency=record.avg_frequency,
        avg_char_rate=record.avg_char_rate,
        is_excited=record.is_excited,
        transcription_status=record.transcription_status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        user=VoiceMessageUserInfo(
            id=sender.id,
            nick_name=sender.nick_name,
            avatar=sender.avatar,
        ),
    )


def _normalize_transcript_text(transcript_text: str | None) -> str | None:
    normalized = (transcript_text or "").strip()
    return normalized or None


def _is_unrecognized_speech(transcript_text: str | None) -> bool:
    normalized = _normalize_transcript_text(transcript_text)
    return bool(normalized and normalized.casefold() == UNRECOGNIZED_SPEECH_TEXT.casefold())


async def _analyze_voice_message_excitement(db: AsyncSession, record) -> None:
    try:
        await analyze_and_persist_voice_message_excitement(
            db,
            voice_message_id=record.id,
            channel_id=record.channel_id,
            user_id=record.user_id,
            relative_audio_path=record.audio_path,
        )
    except Exception as exc:
        logger.warning(
            "voice_message_excitement_analysis_failed id=%s path=%s detail=%s",
            record.id,
            record.audio_path,
            exc,
        )


@ekko.post("/upload")
async def upload_voice_message(
    channel_id: Annotated[int, Form(...)],
    duration_ms: Annotated[int, Form(...)],
    file: Annotated[UploadFile, File(...)],
    client_message_id: Annotated[str | None, Form()] = None,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if duration_ms <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="duration_ms must be positive")

    await _assert_channel_access(db, channel_id=channel_id, user_id=user.id)

    existing = None
    if client_message_id:
        existing = await voice_message.get_voice_message_by_client_id(
            db,
            channel_id=channel_id,
            user_id=user.id,
            client_message_id=client_message_id,
        )
    if existing:
        info = _build_voice_message_info(existing, user)
        return success_response(message="Voice message already uploaded", data=info)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".wav":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unsupported audio extension")

    normalized_content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if normalized_content_type not in {"audio/wav", "audio/wave", "audio/x-wav"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unsupported audio content type")

    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Uploaded audio file is empty")

    dropped, _classification = _classify_sentence_wav_bytes(
        wav_bytes=payload,
        channel_id=channel_id,
        user_id=user.id,
        speech_ms=duration_ms,
        log_prefix="voice_message_upload",
    )
    if dropped:
        return success_response(message="Voice message dropped by audio event filter", data=None)

    saved = save_voice_message_bytes(
        payload,
        channel_id=channel_id,
        suffix=suffix,
        mime_type=normalized_content_type or file.content_type or "audio/wav",
    )
    created = await voice_message.create_voice_message(
        db,
        channel_id=channel_id,
        user_id=user.id,
        client_message_id=client_message_id,
        audio_path=saved["path"],
        audio_duration_ms=duration_ms,
        transcript_text=None,
        transcription_status=TRANSCRIPTION_PENDING,
    )
    if created.transcription_status == TRANSCRIPTION_PENDING:
        try:
            queued = await enqueue_voice_message_transcription(
                created.id,
                audio_bytes=payload,
                audio_format=suffix.lstrip("."),
            )
        except Exception as exc:
            logger.warning("voice_message_transcription_enqueue_failed id=%s detail=%s", created.id, exc)
            queued = False
        if not queued:
            logger.warning(
                "voice_message_transcription_enqueue_skipped id=%s status=%s",
                created.id,
                created.transcription_status,
            )
    return success_response(
        message="Voice message uploaded",
        data=_build_voice_message_info(created, user),
    )


@ekko.get("/channel/{channel_id}")
async def list_voice_messages_by_channel(
    channel_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_channel_access(db, channel_id=channel_id, user_id=user.id)
    total = await voice_message.count_voice_messages_by_channel(db, channel_id)
    rows = await voice_message.select_voice_messages_by_channel(
        db,
        channel_id,
    )
    payload = [
        _build_voice_message_info(record, sender)
        for record, sender in rows
    ]
    return success_response(
        message="Voice messages fetched",
        data=VoiceMessagePage(total=total, voice_messages=payload),
    )


@ekko.post("/{voice_message_id}/transcribe")
async def transcribe_voice_message(
    voice_message_id: int,
    user: Users = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await _assert_voice_message_access(db, voice_message_id=voice_message_id, user_id=user.id)
    if record.transcription_status == TRANSCRIPTION_DONE and record.transcript_text:
        sender = await _get_sender(db, record.user_id)
        return success_response(
            message="Voice message transcript fetched",
            data=_build_voice_message_info(record, sender),
        )
    if record.transcription_status in {TRANSCRIPTION_DROPPED, TRANSCRIPTION_FAILED}:
        record = await voice_message.update_voice_message_transcription_state(
            db,
            voice_message_id,
            transcription_status=TRANSCRIPTION_PENDING,
        ) or record
    try:
        queued = await enqueue_voice_message_transcription(voice_message_id)
    except Exception as exc:
        logger.warning("voice_message_transcription_reenqueue_failed id=%s detail=%s", voice_message_id, exc)
        queued = False
    if not queued and record.transcription_status not in {TRANSCRIPTION_PENDING, TRANSCRIPTION_PROCESSING}:
        logger.warning(
            "voice_message_transcription_reenqueue_skipped id=%s status=%s",
            voice_message_id,
            record.transcription_status,
        )
    latest = await voice_message.select_voice_message_by_id(db, voice_message_id) or record
    sender = await _get_sender(db, latest.user_id)
    return success_response(
        message="Voice message transcription queued",
        data=_build_voice_message_info(latest, sender),
    )


@ekko.post("/internal/transcription-callback")
async def update_voice_message_transcription_callback(
    body: VoiceMessageTranscriptionCallbackRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    expected = f"Bearer {VOICE_MESSAGE_ASR_CALLBACK_TOKEN}"
    if not VOICE_MESSAGE_ASR_CALLBACK_TOKEN or authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    record = await voice_message.select_voice_message_by_id(db, body.voice_message_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice message does not exist")

    transcript_value = _normalize_transcript_text(body.transcript_text)
    if body.transcription_status == TRANSCRIPTION_DONE:
        if _is_unrecognized_speech(transcript_value):
            body.transcription_status = TRANSCRIPTION_DROPPED
            transcript_value = None
        else:
            record = await voice_message.update_voice_message_transcript(
                db,
                body.voice_message_id,
                transcript_text=transcript_value,
                transcription_status=TRANSCRIPTION_DONE,
            )
            if record:
                await _analyze_voice_message_excitement(db, record)
            return success_response(message="Voice message transcription callback applied", data=None)

    if body.transcription_status == TRANSCRIPTION_DROPPED:
        await voice_message.update_voice_message_transcript(
            db,
            body.voice_message_id,
            transcript_text=None,
            transcription_status=TRANSCRIPTION_DROPPED,
        )
    elif body.transcription_status == TRANSCRIPTION_FAILED:
        await voice_message.update_voice_message_transcription_state(
            db,
            body.voice_message_id,
            transcription_status=TRANSCRIPTION_FAILED,
        )
    elif body.transcription_status == TRANSCRIPTION_PROCESSING:
        await voice_message.update_voice_message_transcription_state(
            db,
            body.voice_message_id,
            transcription_status=TRANSCRIPTION_PROCESSING,
        )
    elif body.transcription_status == TRANSCRIPTION_PENDING:
        await voice_message.update_voice_message_transcription_state(
            db,
            body.voice_message_id,
            transcription_status=TRANSCRIPTION_PENDING,
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported transcription status")

    return success_response(message="Voice message transcription callback applied", data=None)
