from __future__ import annotations

import base64
import json
import logging
from urllib import request
from urllib.error import HTTPError, URLError

from config.audio_event_service_config import (
    AUDIO_EVENT_ENABLED,
    AUDIO_EVENT_ENFORCE_FILTER,
    AUDIO_EVENT_REMOTE_TIMEOUT_SECONDS,
    AUDIO_EVENT_REMOTE_TOKEN,
    AUDIO_EVENT_REMOTE_TOP_K,
    AUDIO_EVENT_REMOTE_URL,
)
from utils.network import should_bypass_proxy


logger = logging.getLogger("ekko.audio_event_classifier")


def classify_audio_event_bytes(audio_bytes: bytes, *, audio_format: str = "wav") -> dict | None:
    if not AUDIO_EVENT_ENABLED:
        return None
    if not AUDIO_EVENT_REMOTE_URL:
        return None
    if not audio_bytes:
        raise ValueError("Audio payload is empty")

    payload = json.dumps(
        {
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "audio_format": audio_format,
            "top_k": AUDIO_EVENT_REMOTE_TOP_K,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if AUDIO_EVENT_REMOTE_TOKEN:
        headers["Authorization"] = f"Bearer {AUDIO_EVENT_REMOTE_TOKEN}"

    req = request.Request(
        AUDIO_EVENT_REMOTE_URL,
        data=payload,
        headers=headers,
        method="POST",
    )
    opener = request.build_opener(request.ProxyHandler({})) if should_bypass_proxy(AUDIO_EVENT_REMOTE_URL) else request.build_opener()

    logger.info(
        "audio_event_classify request url=%s bytes=%s format=%s",
        AUDIO_EVENT_REMOTE_URL,
        len(audio_bytes),
        audio_format,
    )

    try:
        with opener.open(req, timeout=AUDIO_EVENT_REMOTE_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.error(
            "audio_event_classify http_error url=%s status=%s body=%s",
            AUDIO_EVENT_REMOTE_URL,
            exc.code,
            error_body,
        )
        raise RuntimeError(f"Audio event HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        logger.error(
            "audio_event_classify connection_failed url=%s reason=%s",
            AUDIO_EVENT_REMOTE_URL,
            exc.reason,
        )
        raise RuntimeError(f"Audio event connection failed: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error(
            "audio_event_classify invalid_json url=%s body=%s",
            AUDIO_EVENT_REMOTE_URL,
            body,
        )
        raise RuntimeError(f"Audio event service returned invalid JSON: {body}") from exc

    logger.info(
        "audio_event_classify success dominant=%s speech=%.4f should_drop=%s",
        data.get("dominant_label"),
        float(data.get("speech_score") or 0.0),
        data.get("should_drop"),
    )
    return data


def should_drop_audio_event(classification: dict | None) -> bool:
    if not classification:
        return False
    is_speech = bool(classification.get("is_speech"))
    should_drop = bool(classification.get("should_drop"))
    if should_drop:
        return True
    return AUDIO_EVENT_ENFORCE_FILTER and not is_speech
