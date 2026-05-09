from __future__ import annotations

import base64
import ipaddress
import json
import logging
from pathlib import Path
from urllib import parse
from urllib import request
from urllib.error import HTTPError, URLError

from config.voice_message_asr_config import (
    VOICE_MESSAGE_ASR_LANGUAGE,
    VOICE_MESSAGE_ASR_REMOTE_TIMEOUT_SECONDS,
    VOICE_MESSAGE_ASR_REMOTE_TOKEN,
    VOICE_MESSAGE_ASR_REMOTE_URL,
)
from utils.file_storage import BASE_DIR, UPLOAD_ROOT


logger = logging.getLogger("ekko.voice_message_transcriber")


def resolve_uploaded_audio_path(relative_path: str) -> Path:
    target_path = BASE_DIR.joinpath(*Path(relative_path.lstrip("/")).parts)
    resolved_target = target_path.resolve()
    resolved_root = UPLOAD_ROOT.resolve()
    if resolved_target != resolved_root and resolved_root not in resolved_target.parents:
        raise ValueError("Invalid uploaded audio path")
    if not resolved_target.is_file():
        raise FileNotFoundError("Uploaded audio file does not exist")
    return resolved_target


def resolve_audio_format(audio_path: Path) -> str:
    suffix = audio_path.suffix.lower().lstrip(".")
    if not suffix:
        return "wav"
    return suffix


def should_bypass_proxy(url: str) -> bool:
    hostname = (parse.urlparse(url).hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return (
            address.is_loopback
            or address.is_private
            or address.is_link_local
        )
    except ValueError:
        return False


def _transcribe_audio_bytes(*, audio_bytes: bytes, audio_format: str, source_label: str) -> dict:
    if not VOICE_MESSAGE_ASR_REMOTE_URL:
        raise ValueError("EKKO_ASR_REMOTE_URL is not configured")
    if not audio_bytes:
        raise ValueError("Uploaded audio file is empty")

    payload = json.dumps(
        {
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "audio_format": audio_format,
            "language": VOICE_MESSAGE_ASR_LANGUAGE,
            "prompt_text": "",
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if VOICE_MESSAGE_ASR_REMOTE_TOKEN:
        headers["Authorization"] = f"Bearer {VOICE_MESSAGE_ASR_REMOTE_TOKEN}"

    req = request.Request(
        VOICE_MESSAGE_ASR_REMOTE_URL,
        data=payload,
        headers=headers,
        method="POST",
    )

    logger.info(
        "voice_message_transcribe request url=%s source=%s format=%s bytes=%s",
        VOICE_MESSAGE_ASR_REMOTE_URL,
        source_label,
        audio_format,
        len(audio_bytes),
    )

    opener = request.build_opener(request.ProxyHandler({})) if should_bypass_proxy(VOICE_MESSAGE_ASR_REMOTE_URL) else request.build_opener()

    try:
        with opener.open(req, timeout=VOICE_MESSAGE_ASR_REMOTE_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.error(
            "voice_message_transcribe http_error url=%s source=%s status=%s body=%s",
            VOICE_MESSAGE_ASR_REMOTE_URL,
            source_label,
            exc.code,
            error_body,
        )
        raise RuntimeError(f"ASR HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        logger.error(
            "voice_message_transcribe connection_failed url=%s source=%s format=%s reason=%s",
            VOICE_MESSAGE_ASR_REMOTE_URL,
            source_label,
            audio_format,
            exc.reason,
        )
        raise RuntimeError(f"ASR connection failed: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error(
            "voice_message_transcribe invalid_json_response url=%s source=%s format=%s body=%s",
            VOICE_MESSAGE_ASR_REMOTE_URL,
            source_label,
            audio_format,
            body,
        )
        raise RuntimeError(f"ASR returned invalid JSON: {body}") from exc

    text = str(data.get("text", "")).strip()
    logger.info(
        "voice_message_transcribe success source=%s format=%s text_chars=%s",
        source_label,
        audio_format,
        len(text),
    )
    return {
        "text": text,
        "words": data.get("words") if isinstance(data.get("words"), list) else None,
    }


def transcribe_audio_bytes(*, audio_bytes: bytes, audio_format: str, source_label: str = "memory") -> dict:
    return _transcribe_audio_bytes(audio_bytes=audio_bytes, audio_format=audio_format, source_label=source_label)


def transcribe_uploaded_audio(relative_path: str) -> dict:
    resolved_path = resolve_uploaded_audio_path(relative_path)
    audio_format = resolve_audio_format(resolved_path)
    audio_bytes = resolved_path.read_bytes()
    return _transcribe_audio_bytes(
        audio_bytes=audio_bytes,
        audio_format=audio_format,
        source_label=f"{relative_path} -> {resolved_path}",
    )
