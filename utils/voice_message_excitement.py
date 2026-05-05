from __future__ import annotations

import math
import wave
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from scipy.signal import hilbert, resample_poly

from crud import voice_message
from utils.voice_message_transcriber import resolve_uploaded_audio_path


HILBERT_SAMPLE_RATE = 16000
MIN_EVALUATION_SENTENCES = 10
MAX_BASELINE_SENTENCES = 500
EXCITEMENT_MULTIPLIER = 1.5


@dataclass(slots=True)
class VoiceFeatureSummary:
    avg_amplitude: float
    avg_frequency: float


def _decode_audio_to_mono_pcm(audio_path: str):
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for voice excitement analysis") from exc

    try:
        with wave.open(audio_path, "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            pcm = wav_file.readframes(frame_count)
    except wave.Error as exc:
        raise RuntimeError(f"uploaded audio is not a valid wav file: {exc}") from exc

    if not pcm:
        raise RuntimeError("decoded audio is empty")
    if sample_width != 2:
        raise RuntimeError("voice excitement analysis only supports 16-bit PCM wav")

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if sample_rate != HILBERT_SAMPLE_RATE:
        samples = resample_poly(samples, HILBERT_SAMPLE_RATE, sample_rate)
    if samples.size < 4:
        raise RuntimeError("decoded audio is too short for excitement analysis")
    return samples


def _hilbert_summary(samples) -> VoiceFeatureSummary:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for voice excitement analysis") from exc

    analytic_signal = hilbert(samples)
    amplitude = np.abs(analytic_signal)
    phase = np.unwrap(np.angle(analytic_signal))
    instantaneous_frequency = np.diff(phase) * (HILBERT_SAMPLE_RATE / (2.0 * math.pi))

    valid_amplitude = amplitude[np.isfinite(amplitude)]
    valid_frequency = np.abs(instantaneous_frequency[np.isfinite(instantaneous_frequency)])
    if valid_amplitude.size == 0:
        raise RuntimeError("unable to compute valid amplitude values")
    if valid_frequency.size == 0:
        raise RuntimeError("unable to compute valid frequency values")

    return VoiceFeatureSummary(
        avg_amplitude=float(valid_amplitude.mean()),
        avg_frequency=float(valid_frequency.mean()),
    )


def analyze_uploaded_audio(relative_audio_path: str) -> VoiceFeatureSummary:
    resolved_path = resolve_uploaded_audio_path(relative_audio_path)
    samples = _decode_audio_to_mono_pcm(str(resolved_path))
    return _hilbert_summary(samples)


def _is_metric_excited(current_value: float, historical_value: float) -> bool:
    return historical_value > 0 and current_value > historical_value * EXCITEMENT_MULTIPLIER


async def analyze_and_persist_voice_message_excitement(
    db: AsyncSession,
    *,
    voice_message_id: int,
    channel_id: int,
    user_id: str,
    relative_audio_path: str,
):
    feature_summary = analyze_uploaded_audio(relative_audio_path)
    profile = await voice_message.create_or_get_user_channel_voice_profile(
        db,
        channel_id=channel_id,
        user_id=user_id,
    )

    should_evaluate = profile.total_sentence_count >= MIN_EVALUATION_SENTENCES
    is_excited = False
    if should_evaluate:
        is_excited = (
            _is_metric_excited(feature_summary.avg_amplitude, profile.historical_avg_amplitude)
            or _is_metric_excited(feature_summary.avg_frequency, profile.historical_avg_frequency)
        )

    next_total_sentence_count = profile.total_sentence_count + 1
    next_baseline_sentence_count = profile.baseline_sentence_count
    next_historical_avg_amplitude = profile.historical_avg_amplitude
    next_historical_avg_frequency = profile.historical_avg_frequency

    if profile.baseline_sentence_count < MAX_BASELINE_SENTENCES:
        next_baseline_sentence_count = profile.baseline_sentence_count + 1
        next_historical_avg_amplitude = (
            (profile.historical_avg_amplitude * profile.baseline_sentence_count) + feature_summary.avg_amplitude
        ) / next_baseline_sentence_count
        next_historical_avg_frequency = (
            (profile.historical_avg_frequency * profile.baseline_sentence_count) + feature_summary.avg_frequency
        ) / next_baseline_sentence_count

    await voice_message.update_voice_message_analysis(
        db,
        voice_message_id,
        avg_amplitude=feature_summary.avg_amplitude,
        avg_frequency=feature_summary.avg_frequency,
        is_excited=is_excited,
    )
    await voice_message.update_user_channel_voice_profile(
        db,
        channel_id=channel_id,
        user_id=user_id,
        historical_avg_amplitude=next_historical_avg_amplitude,
        historical_avg_frequency=next_historical_avg_frequency,
        total_sentence_count=next_total_sentence_count,
        baseline_sentence_count=next_baseline_sentence_count,
    )
