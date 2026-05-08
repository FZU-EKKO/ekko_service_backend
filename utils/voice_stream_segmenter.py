from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

import webrtcvad

from config.voice_stream_vad_config import (
    STREAM_VAD_FRAME_MS,
    STREAM_VAD_INACTIVITY_MS,
    STREAM_VAD_MIN_SPEECH_MS,
    STREAM_VAD_MODE,
    STREAM_VAD_PRE_SPEECH_MS,
    STREAM_VAD_SAMPLE_RATE,
    STREAM_VAD_START_FRAMES,
)


BYTES_PER_SAMPLE = 2
FRAME_BYTES = STREAM_VAD_SAMPLE_RATE * STREAM_VAD_FRAME_MS // 1000 * BYTES_PER_SAMPLE
PRE_SPEECH_FRAMES = max(0, STREAM_VAD_PRE_SPEECH_MS // STREAM_VAD_FRAME_MS)
INACTIVITY_FRAMES = max(1, STREAM_VAD_INACTIVITY_MS // STREAM_VAD_FRAME_MS)
MIN_SPEECH_FRAMES = max(1, STREAM_VAD_MIN_SPEECH_MS // STREAM_VAD_FRAME_MS)


@dataclass
class StreamSentence:
    pcm_bytes: bytes
    speech_ms: int


@dataclass
class ExpiredStreamEmission:
    session_key: str
    user_id: str
    channel_id: int
    stream_id: str
    next_sequence: int
    sentences: list[StreamSentence]


@dataclass
class StreamSessionState:
    user_id: str
    channel_id: int
    stream_id: str
    vad: webrtcvad.Vad = field(default_factory=lambda: webrtcvad.Vad(STREAM_VAD_MODE))
    pending_bytes: bytearray = field(default_factory=bytearray)
    pre_speech_frames: deque[bytes] = field(default_factory=lambda: deque(maxlen=PRE_SPEECH_FRAMES))
    active_frames: list[bytes] = field(default_factory=list)
    triggered: bool = False
    speech_run_frames: int = 0
    inactivity_frames: int = 0
    last_ingest_at: float = field(default_factory=monotonic)
    emitted_sequence: int = 0

    def buffered_ms(self) -> int:
        pending_frames = len(self.pending_bytes) // FRAME_BYTES
        active_frames = len(self.active_frames)
        return (pending_frames + active_frames) * STREAM_VAD_FRAME_MS


class VoiceStreamSegmenter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, StreamSessionState] = {}

    async def ingest(
        self,
        *,
        session_key: str,
        user_id: str,
        channel_id: int,
        stream_id: str,
        pcm_bytes: bytes,
        is_final: bool,
    ) -> tuple[list[StreamSentence], bool, int]:
        async with self._lock:
            state = self._sessions.setdefault(
                session_key,
                StreamSessionState(user_id=user_id, channel_id=channel_id, stream_id=stream_id),
            )
            state.last_ingest_at = monotonic()
            emitted = self._append_and_segment(state, pcm_bytes)
            if is_final:
                emitted.extend(self._flush(state))
                self._sessions.pop(session_key, None)
                return emitted, False, 0
            return emitted, True, state.buffered_ms()

    async def sweep_expired(self) -> list[ExpiredStreamEmission]:
        now = monotonic()
        expired: list[ExpiredStreamEmission] = []
        async with self._lock:
            for session_key, state in list(self._sessions.items()):
                if state.buffered_ms() <= 0:
                    continue
                idle_ms = int((now - state.last_ingest_at) * 1000)
                if idle_ms < STREAM_VAD_INACTIVITY_MS:
                    continue
                sentences = self._flush(state)
                if not sentences:
                    self._sessions.pop(session_key, None)
                    continue
                expired.append(
                    ExpiredStreamEmission(
                        session_key=session_key,
                        user_id=state.user_id,
                        channel_id=state.channel_id,
                        stream_id=state.stream_id,
                        next_sequence=state.emitted_sequence,
                        sentences=sentences,
                    )
                )
                state.emitted_sequence += len(sentences)
                self._sessions.pop(session_key, None)
        return expired

    def _append_and_segment(self, state: StreamSessionState, pcm_bytes: bytes) -> list[StreamSentence]:
        emitted: list[StreamSentence] = []
        state.pending_bytes.extend(pcm_bytes)
        while len(state.pending_bytes) >= FRAME_BYTES:
            frame = bytes(state.pending_bytes[:FRAME_BYTES])
            del state.pending_bytes[:FRAME_BYTES]
            is_speech = state.vad.is_speech(frame, STREAM_VAD_SAMPLE_RATE)
            if not state.triggered:
                state.pre_speech_frames.append(frame)
                if is_speech:
                    state.speech_run_frames += 1
                    if state.speech_run_frames >= STREAM_VAD_START_FRAMES:
                        state.triggered = True
                        state.active_frames = list(state.pre_speech_frames)
                        state.inactivity_frames = 0
                else:
                    state.speech_run_frames = 0
                continue

            state.active_frames.append(frame)
            if is_speech:
                state.inactivity_frames = 0
            else:
                state.inactivity_frames += 1
                if state.inactivity_frames >= INACTIVITY_FRAMES:
                    sentence = self._finalize_sentence(state)
                    if sentence is not None:
                        emitted.append(sentence)
        return emitted

    def _flush(self, state: StreamSessionState) -> list[StreamSentence]:
        emitted: list[StreamSentence] = []
        if state.pending_bytes:
            state.pending_bytes.clear()
        sentence = self._finalize_sentence(state)
        if sentence is not None:
            emitted.append(sentence)
        return emitted

    def _finalize_sentence(self, state: StreamSessionState) -> StreamSentence | None:
        if not state.active_frames:
            state.triggered = False
            state.speech_run_frames = 0
            state.inactivity_frames = 0
            state.pre_speech_frames.clear()
            return None

        frames = list(state.active_frames)
        speech_frame_count = len(frames)
        state.active_frames = []
        state.triggered = False
        state.speech_run_frames = 0
        state.inactivity_frames = 0
        state.pre_speech_frames.clear()

        if speech_frame_count < MIN_SPEECH_FRAMES:
            return None
        return StreamSentence(
            pcm_bytes=b"".join(frames),
            speech_ms=speech_frame_count * STREAM_VAD_FRAME_MS,
        )


voice_stream_segmenter = VoiceStreamSegmenter()
