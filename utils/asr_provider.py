from __future__ import annotations

import asyncio
import base64
import io
import json
from urllib import request
from urllib.error import HTTPError, URLError
import wave
from dataclasses import dataclass
from typing import Protocol

from config.asr_config import ASR_LANGUAGE, ASR_REMOTE_TIMEOUT_SECONDS, ASR_REMOTE_TOKEN, ASR_REMOTE_URL


@dataclass
class AsrResult:
    text: str
    words: list[dict] | None = None


class AsrProvider(Protocol):
    async def transcribe_pcm16(
        self,
        *,
        pcm_bytes: bytes,
        sample_rate: int,
        channels: int,
        sample_width: int,
        prompt_text: str = "",
    ) -> AsrResult: ...


def _build_wav_bytes(*, pcm_bytes: bytes, sample_rate: int, channels: int, sample_width: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return stream.getvalue()


class RemoteAsrProvider:
    """Call a remote ASR HTTP service and normalize the response to AsrResult."""

    def __init__(self):
        if not ASR_REMOTE_URL:
            raise ValueError("EKKO_ASR_REMOTE_URL is required when using remote ASR provider")

    def _build_payload(
        self,
        *,
        pcm_bytes: bytes,
        sample_rate: int,
        channels: int,
        sample_width: int,
        prompt_text: str,
    ) -> bytes:
        wav_bytes = _build_wav_bytes(
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        payload = {
            "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
            "audio_format": "wav",
            "language": ASR_LANGUAGE,
            "prompt_text": prompt_text,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width": sample_width,
        }
        return json.dumps(payload).encode("utf-8")

    def _send_request(self, payload: bytes) -> AsrResult:
        headers = {"Content-Type": "application/json"}
        if ASR_REMOTE_TOKEN:
            headers["Authorization"] = f"Bearer {ASR_REMOTE_TOKEN}"

        req = request.Request(
            ASR_REMOTE_URL,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=ASR_REMOTE_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Remote ASR HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Remote ASR connection failed: {exc.reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Remote ASR response is not valid JSON") from exc

        text = str(data.get("text", "")).strip()
        if not text:
            raise RuntimeError("Remote ASR response missing 'text'")
        words = data.get("words")
        return AsrResult(
            text=text,
            words=words if isinstance(words, list) else None,
        )

    async def transcribe_pcm16(
        self,
        *,
        pcm_bytes: bytes,
        sample_rate: int,
        channels: int,
        sample_width: int,
        prompt_text: str = "",
    ) -> AsrResult:
        payload = self._build_payload(
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            prompt_text=prompt_text,
        )
        return await asyncio.to_thread(self._send_request, payload)


def build_asr_provider(provider_name: str) -> AsrProvider:
    name = provider_name.strip().lower()
    if name == "remote":
        return RemoteAsrProvider()
    raise ValueError(f"Unsupported ASR provider: {provider_name}")
