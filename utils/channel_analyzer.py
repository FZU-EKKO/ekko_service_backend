from __future__ import annotations

import json
import logging
from datetime import datetime
from urllib import error, request

from config.channel_analysis_config import (
    CHANNEL_ANALYSIS_MAX_CHARS,
    CHANNEL_ANALYSIS_MAX_MESSAGES,
    CHANNEL_ANALYSIS_REMOTE_TIMEOUT_SECONDS,
    CHANNEL_ANALYSIS_REMOTE_TOKEN,
    CHANNEL_ANALYSIS_REMOTE_URL,
)
from crud import voice_message
from utils.network import should_bypass_proxy


logger = logging.getLogger("ekko.channel_analyzer")


def _format_created_at(value: datetime) -> str:
    return value.strftime("%H:%M")


def build_channel_conversation_text(rows: list[tuple]) -> tuple[str, int, bool]:
    selected_rows = list(rows[-CHANNEL_ANALYSIS_MAX_MESSAGES:])
    snippets: list[str] = []
    truncated = len(rows) > len(selected_rows)

    for record, sender in selected_rows:
        transcript_text = str(record.transcript_text or "").strip()
        if not transcript_text:
            continue
        snippets.append(f"[{_format_created_at(record.created_at)}] {sender.nick_name}: {transcript_text}")

    if not snippets:
        return "", 0, truncated

    conversation_text = "\n".join(snippets)
    if len(conversation_text) <= CHANNEL_ANALYSIS_MAX_CHARS:
        return conversation_text, len(snippets), truncated

    truncated = True
    trimmed_snippets: list[str] = []
    total_chars = 0
    for snippet in reversed(snippets):
        next_chars = len(snippet) + (1 if trimmed_snippets else 0)
        if total_chars + next_chars > CHANNEL_ANALYSIS_MAX_CHARS:
            break
        trimmed_snippets.append(snippet)
        total_chars += next_chars

    trimmed_snippets.reverse()
    return "\n".join(trimmed_snippets), len(trimmed_snippets), truncated


def _call_remote_analysis_service(*, channel_id: int, conversation_text: str, prompt: str) -> dict:
    if not CHANNEL_ANALYSIS_REMOTE_URL:
        raise ValueError("EKKO_ANALYSIS_REMOTE_URL is not configured")

    payload = json.dumps(
        {
            "channel_id": channel_id,
            "conversation_text": conversation_text,
            "prompt": prompt,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if CHANNEL_ANALYSIS_REMOTE_TOKEN:
        headers["Authorization"] = f"Bearer {CHANNEL_ANALYSIS_REMOTE_TOKEN}"

    req = request.Request(
        CHANNEL_ANALYSIS_REMOTE_URL,
        data=payload,
        headers=headers,
        method="POST",
    )
    logger.info(
        "channel_analysis request url=%s channel_id=%s prompt_chars=%s input_chars=%s",
        CHANNEL_ANALYSIS_REMOTE_URL,
        channel_id,
        len(prompt or ""),
        len(conversation_text or ""),
    )
    opener = request.build_opener(request.ProxyHandler({})) if should_bypass_proxy(CHANNEL_ANALYSIS_REMOTE_URL) else request.build_opener()

    try:
        with opener.open(req, timeout=CHANNEL_ANALYSIS_REMOTE_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        logger.warning(
            "channel_analysis http_error url=%s channel_id=%s status=%s body=%s",
            CHANNEL_ANALYSIS_REMOTE_URL,
            channel_id,
            exc.code,
            error_body,
        )
        raise RuntimeError(f"Analysis HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        logger.warning(
            "channel_analysis connection_failed url=%s channel_id=%s reason=%s",
            CHANNEL_ANALYSIS_REMOTE_URL,
            channel_id,
            exc.reason,
        )
        raise RuntimeError(f"Analysis connection failed: {exc.reason}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning(
            "channel_analysis invalid_json_response url=%s channel_id=%s body=%s",
            CHANNEL_ANALYSIS_REMOTE_URL,
            channel_id,
            body,
        )
        raise RuntimeError(f"Analysis returned invalid JSON: {body}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Analysis returned unexpected payload: {parsed!r}")
    return parsed


async def analyze_channel_conversation(
    *,
    db,
    channel_id: int,
    prompt: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict:
    if start_time and end_time and start_time > end_time:
        raise ValueError("start_time must be earlier than or equal to end_time")

    rows = await voice_message.select_transcript_voice_messages_by_channel(
        db,
        channel_id,
        start_time=start_time,
        end_time=end_time,
        limit=CHANNEL_ANALYSIS_MAX_MESSAGES,
    )
    conversation_text, source_count, truncated = build_channel_conversation_text(rows)
    if not conversation_text:
        if start_time or end_time:
            raise ValueError("No transcript text is available for this channel in the selected time range")
        raise ValueError("No transcript text is available for this channel yet")

    result = _call_remote_analysis_service(
        channel_id=channel_id,
        conversation_text=conversation_text,
        prompt=(prompt or "").strip(),
    )
    report = str(result.get("report", "") or "").strip()
    if not report:
        raise RuntimeError(f"Analysis returned empty report: {result!r}")

    return {
        "report": report,
        "prompt": (prompt or "").strip(),
        "source_count": source_count,
        "truncated": bool(truncated or result.get("truncated", False)),
        "start_time": start_time,
        "end_time": end_time,
    }
