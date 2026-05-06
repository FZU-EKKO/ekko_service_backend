import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.db_config import get_db
from crud import channel, domain, voice_message
from models.channel import ChannelType
from models.users import Users
from schemas.voice_message import VoiceMessageInfo, VoiceMessagePage, VoiceMessageUserInfo
from utils.auth import get_current_user
from utils.file_storage import save_voice_message_upload
from utils.voice_message_excitement import analyze_and_persist_voice_message_excitement
from utils.response import success_response
from utils.voice_message_transcriber import transcribe_uploaded_audio


ekko = APIRouter(prefix="/api/voice-messages", tags=["voice_messages"])
logger = logging.getLogger("ekko.voice_messages")


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
        audio_format=record.audio_format,
        mime_type=record.mime_type,
        file_size=record.file_size,
        transcript_text=record.transcript_text,
        waveform=record.waveform,
        avg_amplitude=record.avg_amplitude,
        avg_frequency=record.avg_frequency,
        avg_char_rate=record.avg_char_rate,
        is_excited=record.is_excited,
        created_at=record.created_at,
        updated_at=record.updated_at,
        user=VoiceMessageUserInfo(
            id=sender.id,
            nick_name=sender.nick_name,
            avatar=sender.avatar,
        ),
    )


def _parse_waveform(raw_waveform: str | None) -> list[int] | None:
    if not raw_waveform:
        return None
    try:
        payload = json.loads(raw_waveform)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid waveform payload") from exc

    if not isinstance(payload, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Waveform must be an array")

    normalized: list[int] = []
    for item in payload[:256]:
        if not isinstance(item, int):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Waveform values must be integers")
        normalized.append(max(0, min(100, item)))
    return normalized


@ekko.post("/upload")
async def upload_voice_message(
    channel_id: Annotated[int, Form(...)],
    duration_ms: Annotated[int, Form(...)],
    file: Annotated[UploadFile, File(...)],
    client_message_id: Annotated[str | None, Form()] = None,
    transcript_text: Annotated[str | None, Form()] = None,
    waveform: Annotated[str | None, Form()] = None,
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

    waveform_payload = _parse_waveform(waveform)
    saved = await save_voice_message_upload(file, channel_id=channel_id)
    created = await voice_message.create_voice_message(
        db,
        channel_id=channel_id,
        user_id=user.id,
        client_message_id=client_message_id,
        audio_path=saved["path"],
        audio_duration_ms=duration_ms,
        audio_format=saved["audio_format"],
        mime_type=saved["mime_type"],
        file_size=saved["file_size"],
        transcript_text=(transcript_text or "").strip() or None,
        waveform=waveform_payload,
    )
    if not created.transcript_text:
        try:
            result = transcribe_uploaded_audio(created.audio_path)
            created = await voice_message.update_voice_message_transcript(
                db,
                created.id,
                transcript_text=result["text"] or None,
            ) or created
        except Exception as exc:
            logger.warning(
                "voice_message_auto_transcribe_failed id=%s path=%s format=%s detail=%s",
                created.id,
                created.audio_path,
                created.audio_format,
                exc,
            )
    try:
        await analyze_and_persist_voice_message_excitement(
            db,
            voice_message_id=created.id,
            channel_id=created.channel_id,
            user_id=created.user_id,
            relative_audio_path=created.audio_path,
        )
        created = await voice_message.select_voice_message_by_id(db, created.id) or created
    except Exception as exc:
        logger.warning(
            "voice_message_excitement_analysis_failed id=%s path=%s format=%s detail=%s",
            created.id,
            created.audio_path,
            created.audio_format,
            exc,
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
    if record.transcript_text:
        sender = await _get_sender(db, record.user_id)
        return success_response(
            message="Voice message transcript fetched",
            data=_build_voice_message_info(record, sender),
        )

    try:
        result = transcribe_uploaded_audio(record.audio_path)
    except FileNotFoundError as exc:
        logger.warning(
            "voice_message_transcribe file_missing id=%s path=%s format=%s",
            voice_message_id,
            record.audio_path,
            record.audio_format,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning(
            "voice_message_transcribe bad_request id=%s path=%s format=%s detail=%s",
            voice_message_id,
            record.audio_path,
            record.audio_format,
            exc,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception(
            "voice_message_transcribe upstream_failed id=%s path=%s format=%s detail=%s",
            voice_message_id,
            record.audio_path,
            record.audio_format,
            exc,
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    updated = await voice_message.update_voice_message_transcript(
        db,
        voice_message_id,
        transcript_text=result["text"] or None,
    )
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Voice message does not exist")

    try:
        await analyze_and_persist_voice_message_excitement(
            db,
            voice_message_id=updated.id,
            channel_id=updated.channel_id,
            user_id=updated.user_id,
            relative_audio_path=updated.audio_path,
        )
        updated = await voice_message.select_voice_message_by_id(db, updated.id) or updated
    except Exception as exc:
        logger.warning(
            "voice_message_excitement_reanalysis_failed id=%s path=%s format=%s detail=%s",
            updated.id,
            updated.audio_path,
            updated.audio_format,
            exc,
        )

    sender = await _get_sender(db, updated.user_id)
    return success_response(
        message="Voice message transcribed",
        data=_build_voice_message_info(updated, sender),
    )
