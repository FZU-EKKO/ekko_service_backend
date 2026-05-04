from __future__ import annotations

import asyncio
import audioop
import base64
from dataclasses import dataclass, field
from datetime import datetime

from config.asr_config import (
    ASR_ENERGY_THRESHOLD,
    ASR_MAX_UTTERANCE_MS,
    ASR_MIN_UTTERANCE_MS,
    ASR_PROMPT_CHARS,
    ASR_PROVIDER,
    ASR_SILENCE_MS,
)
from config.db_config import AsyncSessionLocal
from crud import transcript
from models.transcript import TranscriptSessionStatus
from utils.asr_provider import build_asr_provider


@dataclass
class AsrTask:
    session_id: int
    user_id: str
    seq_no: int
    start_ms: int
    end_ms: int
    sample_rate: int
    channels: int
    sample_width: int
    pcm_bytes: bytes
    prompt_text: str


@dataclass
class UserStreamState:
    stream_offset_ms: int = 0
    utterance_start_ms: int | None = None
    speech_buffer: bytearray = field(default_factory=bytearray)
    speech_duration_ms: int = 0
    trailing_silence_ms: int = 0
    prompt_text: str = ""
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2


class TranscriptRuntime:
    def __init__(self):
        self._queue: asyncio.Queue[AsrTask | None] = asyncio.Queue()
        self._provider = build_asr_provider(ASR_PROVIDER)
        self._worker_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._streams: dict[tuple[int, str], UserStreamState] = {}
        self._next_seq_no: dict[int, int] = {}
        self._pending_counts: dict[int, int] = {}
        self._accepting_packets: dict[int, bool] = {}

    async def start(self):
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run_worker())

    async def stop(self):
        if self._worker_task is None:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None

    async def register_session(self, session_id: int):
        async with self._lock:
            self._accepting_packets[session_id] = True
            self._next_seq_no.setdefault(session_id, 1)
            self._pending_counts.setdefault(session_id, 0)

    async def submit_packet(
        self,
        *,
        session_id: int,
        user_id: str,
        audio_base64: str,
        sample_rate: int,
        channels: int,
        sample_width: int,
    ):
        pcm_bytes = base64.b64decode(audio_base64)
        if not pcm_bytes:
            return

        packet_duration_ms = self._compute_duration_ms(
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        if packet_duration_ms <= 0:
            return

        async with self._lock:
            if not self._accepting_packets.get(session_id, False):
                raise ValueError("Transcript session is not accepting packets")

            key = (session_id, user_id)
            state = self._streams.setdefault(key, UserStreamState())
            is_speech = self._is_speech(pcm_bytes=pcm_bytes, sample_width=sample_width)

            if is_speech and state.utterance_start_ms is None:
                state.utterance_start_ms = state.stream_offset_ms
                state.speech_buffer.clear()
                state.speech_duration_ms = 0
                state.trailing_silence_ms = 0
                state.sample_rate = sample_rate
                state.channels = channels
                state.sample_width = sample_width

            if state.utterance_start_ms is not None:
                state.speech_buffer.extend(pcm_bytes)
                state.speech_duration_ms += packet_duration_ms
                state.sample_rate = sample_rate
                state.channels = channels
                state.sample_width = sample_width
                if is_speech:
                    state.trailing_silence_ms = 0
                else:
                    state.trailing_silence_ms += packet_duration_ms

                should_flush = (
                    state.trailing_silence_ms >= ASR_SILENCE_MS
                    or state.speech_duration_ms >= ASR_MAX_UTTERANCE_MS
                )
                if should_flush:
                    await self._flush_state_locked(
                        session_id=session_id,
                        user_id=user_id,
                        state=state,
                        sample_rate=sample_rate,
                        channels=channels,
                        sample_width=sample_width,
                    )

            state.stream_offset_ms += packet_duration_ms

    async def finish_session(self, session_id: int):
        async with self._lock:
            self._accepting_packets[session_id] = False
            for (current_session_id, user_id), state in list(self._streams.items()):
                if current_session_id != session_id:
                    continue
                await self._flush_state_locked(
                    session_id=session_id,
                    user_id=user_id,
                    state=state,
                    sample_rate=state.sample_rate,
                    channels=state.channels,
                    sample_width=state.sample_width,
                    force=True,
                )

        async with AsyncSessionLocal() as db:
            await transcript.update_transcript_session_status(
                db,
                session_id,
                status=TranscriptSessionStatus.Processing,
                ended_at=datetime.now(),
            )

        await self._maybe_complete_session(session_id)

    async def _flush_state_locked(
        self,
        *,
        session_id: int,
        user_id: str,
        state: UserStreamState,
        sample_rate: int,
        channels: int,
        sample_width: int,
        force: bool = False,
    ):
        if state.utterance_start_ms is None:
            return
        if not force and state.speech_duration_ms < ASR_MIN_UTTERANCE_MS:
            if state.trailing_silence_ms >= ASR_SILENCE_MS:
                state.utterance_start_ms = None
                state.speech_buffer = bytearray()
                state.speech_duration_ms = 0
                state.trailing_silence_ms = 0
            return
        pcm_bytes = bytes(state.speech_buffer)
        if not pcm_bytes:
            state.utterance_start_ms = None
            state.speech_duration_ms = 0
            state.trailing_silence_ms = 0
            return

        seq_no = self._next_seq_no.get(session_id, 1)
        self._next_seq_no[session_id] = seq_no + 1
        end_ms = state.utterance_start_ms + state.speech_duration_ms
        task = AsrTask(
            session_id=session_id,
            user_id=user_id,
            seq_no=seq_no,
            start_ms=state.utterance_start_ms,
            end_ms=end_ms,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            pcm_bytes=pcm_bytes,
            prompt_text=state.prompt_text[-ASR_PROMPT_CHARS:],
        )
        self._pending_counts[session_id] = self._pending_counts.get(session_id, 0) + 1
        await self._queue.put(task)

        state.utterance_start_ms = None
        state.speech_buffer = bytearray()
        state.speech_duration_ms = 0
        state.trailing_silence_ms = 0

    async def _run_worker(self):
        while True:
            task = await self._queue.get()
            if task is None:
                break

            try:
                result = await self._provider.transcribe_pcm16(
                    pcm_bytes=task.pcm_bytes,
                    sample_rate=task.sample_rate,
                    channels=task.channels,
                    sample_width=task.sample_width,
                    prompt_text=task.prompt_text,
                )
                if result.text.strip():
                    async with AsyncSessionLocal() as db:
                        await transcript.create_transcript_segment(
                            db,
                            session_id=task.session_id,
                            user_id=task.user_id,
                            seq_no=task.seq_no,
                            start_ms=task.start_ms,
                            end_ms=task.end_ms,
                            text=result.text.strip(),
                            is_final=True,
                            words=result.words,
                        )
                    async with self._lock:
                        state = self._streams.setdefault((task.session_id, task.user_id), UserStreamState())
                        state.prompt_text = f"{state.prompt_text} {result.text.strip()}".strip()
            except Exception as exc:
                async with AsyncSessionLocal() as db:
                    await transcript.update_transcript_session_status(
                        db,
                        task.session_id,
                        status=TranscriptSessionStatus.Failed,
                        last_error=str(exc),
                    )
            finally:
                async with self._lock:
                    self._pending_counts[task.session_id] = max(
                        0,
                        self._pending_counts.get(task.session_id, 0) - 1,
                    )
                await self._maybe_complete_session(task.session_id)

    async def _maybe_complete_session(self, session_id: int):
        async with self._lock:
            accepting = self._accepting_packets.get(session_id, True)
            pending = self._pending_counts.get(session_id, 0)
            if accepting or pending > 0:
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

    @staticmethod
    def _is_speech(*, pcm_bytes: bytes, sample_width: int) -> bool:
        return audioop.rms(pcm_bytes, sample_width) >= ASR_ENERGY_THRESHOLD

    @staticmethod
    def _compute_duration_ms(*, pcm_bytes: bytes, sample_rate: int, channels: int, sample_width: int) -> int:
        frame_width = channels * sample_width
        if frame_width <= 0 or sample_rate <= 0:
            return 0
        frames = len(pcm_bytes) / frame_width
        return int(frames / sample_rate * 1000)


transcript_runtime = TranscriptRuntime()
