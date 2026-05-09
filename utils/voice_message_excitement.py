from __future__ import annotations

import re
import wave
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from scipy.signal import find_peaks, hilbert, resample_poly

from config.voice_message_analysis_config import (
    VOICE_MESSAGE_EXCITEMENT_AMPLITUDE_WEIGHT,
    VOICE_MESSAGE_EXCITEMENT_CHAR_RATE_WEIGHT,
    VOICE_MESSAGE_EXCITEMENT_PEAK_RATE_WEIGHT,
)
from crud import voice_message
from utils.voice_message_transcriber import resolve_uploaded_audio_path


HILBERT_SAMPLE_RATE = 16000
MIN_EVALUATION_SENTENCES = 10
MIN_COMPOSITE_METRICS = 2
MAX_BASELINE_SENTENCES = 500
METRIC_FULL_SCORE_RATIO = 1.8
COMPOSITE_EXCITEMENT_THRESHOLD = 0.68
PEAK_SMOOTHING_WINDOW_MS = 40
PEAK_MIN_DISTANCE_MS = 120


@dataclass(slots=True)
class VoiceFeatureSummary:
    avg_amplitude: float
    avg_frequency: float
    avg_char_rate: float | None = None


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


def _voice_feature_summary(samples) -> VoiceFeatureSummary:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for voice excitement analysis") from exc

    analytic_signal = hilbert(samples)
    envelope = np.abs(analytic_signal)
    absolute_amplitude = np.abs(samples)

    valid_amplitude = absolute_amplitude[np.isfinite(absolute_amplitude)]
    valid_envelope = envelope[np.isfinite(envelope)]
    if valid_amplitude.size == 0:
        raise RuntimeError("unable to compute valid amplitude values")

    smoothing_window = max(1, int((PEAK_SMOOTHING_WINDOW_MS / 1000.0) * HILBERT_SAMPLE_RATE))
    smoothing_kernel = np.ones(smoothing_window, dtype=np.float64) / smoothing_window
    smoothed_envelope = np.convolve(valid_envelope, smoothing_kernel, mode="same")

    threshold = max(
        float(smoothed_envelope.mean() + (smoothed_envelope.std() * 0.5)),
        float(np.percentile(smoothed_envelope, 75)),
    )
    min_peak_distance = max(1, int((PEAK_MIN_DISTANCE_MS / 1000.0) * HILBERT_SAMPLE_RATE))
    peaks, _ = find_peaks(smoothed_envelope, height=threshold, distance=min_peak_distance)
    duration_seconds = valid_amplitude.size / HILBERT_SAMPLE_RATE
    peak_rate = float(peaks.size / duration_seconds) if duration_seconds > 0 else 0.0

    return VoiceFeatureSummary(
        avg_amplitude=float(valid_amplitude.mean()),
        avg_frequency=peak_rate,
    )


def analyze_uploaded_audio(relative_audio_path: str) -> VoiceFeatureSummary:
    resolved_path = resolve_uploaded_audio_path(relative_audio_path)
    samples = _decode_audio_to_mono_pcm(str(resolved_path))
    return _voice_feature_summary(samples)


def _compute_char_rate(*, transcript_text: str | None, audio_duration_ms: int) -> float | None:
    normalized_text = re.sub(r"[\s\W_]+", "", transcript_text or "", flags=re.UNICODE)
    if not normalized_text or audio_duration_ms <= 0:
        return None
    duration_seconds = audio_duration_ms / 1000.0
    if duration_seconds <= 0:
        return None
    return len(normalized_text) / duration_seconds


def _metric_ratio_score(current_value: float | None, historical_value: float, *, full_score_ratio: float) -> float | None:
    if current_value is None or historical_value <= 0:
        return None
    ratio = current_value / historical_value
    if ratio <= 1.0:
        return 0.0
    normalized = (ratio - 1.0) / max(full_score_ratio - 1.0, 1e-6)
    return max(0.0, min(normalized, 1.0))


def _composite_excitation_score(
    *,
    amplitude_score: float | None,
    peak_rate_score: float | None,
    char_rate_score: float | None,
) -> tuple[float, int]:
    weighted_scores = [
        (amplitude_score, VOICE_MESSAGE_EXCITEMENT_AMPLITUDE_WEIGHT),
        (peak_rate_score, VOICE_MESSAGE_EXCITEMENT_PEAK_RATE_WEIGHT),
        (char_rate_score, VOICE_MESSAGE_EXCITEMENT_CHAR_RATE_WEIGHT),
    ]
    available = [(score, weight) for score, weight in weighted_scores if score is not None]
    if not available:
        return 0.0, 0

    total_weight = sum(weight for _, weight in available)
    composite = sum(score * weight for score, weight in available) / total_weight
    return composite, len(available)


async def analyze_and_persist_voice_message_excitement(
    db: AsyncSession,
    *,
    voice_message_id: int,
    channel_id: int,
    user_id: str,
    relative_audio_path: str,
):
    feature_summary = analyze_uploaded_audio(relative_audio_path)
    record = await voice_message.select_voice_message_by_id(db, voice_message_id)
    if not record:
        raise RuntimeError(f"voice message {voice_message_id} not found")

    feature_summary.avg_char_rate = _compute_char_rate(
        transcript_text=record.transcript_text,
        audio_duration_ms=record.audio_duration_ms,
    )
    profile = await voice_message.create_or_get_user_channel_voice_profile(
        db,
        channel_id=channel_id,
        user_id=user_id,
    )

    should_evaluate = profile.total_sentence_count >= MIN_EVALUATION_SENTENCES
    is_excited = False
    if should_evaluate:
        amplitude_score = _metric_ratio_score(
            feature_summary.avg_amplitude,
            profile.historical_avg_amplitude,
            full_score_ratio=METRIC_FULL_SCORE_RATIO,
        )
        peak_rate_score = _metric_ratio_score(
            feature_summary.avg_frequency,
            profile.historical_avg_frequency,
            full_score_ratio=METRIC_FULL_SCORE_RATIO,
        )
        char_rate_score = _metric_ratio_score(
            feature_summary.avg_char_rate,
            profile.historical_avg_char_rate,
            full_score_ratio=METRIC_FULL_SCORE_RATIO,
        )
        composite_score, metric_count = _composite_excitation_score(
            amplitude_score=amplitude_score,
            peak_rate_score=peak_rate_score,
            char_rate_score=char_rate_score,
        )
        is_excited = metric_count >= MIN_COMPOSITE_METRICS and composite_score >= COMPOSITE_EXCITEMENT_THRESHOLD

    next_total_sentence_count = profile.total_sentence_count + 1
    next_baseline_sentence_count = profile.baseline_sentence_count
    next_historical_avg_amplitude = profile.historical_avg_amplitude
    next_historical_avg_frequency = profile.historical_avg_frequency
    next_historical_avg_char_rate = profile.historical_avg_char_rate
    next_char_rate_sample_count = profile.char_rate_sample_count

    if profile.baseline_sentence_count < MAX_BASELINE_SENTENCES:
        next_baseline_sentence_count = profile.baseline_sentence_count + 1
        next_historical_avg_amplitude = (
            (profile.historical_avg_amplitude * profile.baseline_sentence_count) + feature_summary.avg_amplitude
        ) / next_baseline_sentence_count
        next_historical_avg_frequency = (
            (profile.historical_avg_frequency * profile.baseline_sentence_count) + feature_summary.avg_frequency
        ) / next_baseline_sentence_count
        if feature_summary.avg_char_rate is not None:
            next_char_rate_sample_count = profile.char_rate_sample_count + 1
            next_historical_avg_char_rate = (
                (profile.historical_avg_char_rate * profile.char_rate_sample_count) + feature_summary.avg_char_rate
            ) / next_char_rate_sample_count

    await voice_message.update_voice_message_analysis(
        db,
        voice_message_id,
        avg_amplitude=feature_summary.avg_amplitude,
        avg_frequency=feature_summary.avg_frequency,
        avg_char_rate=feature_summary.avg_char_rate,
        is_excited=is_excited,
    )
    await voice_message.update_user_channel_voice_profile(
        db,
        channel_id=channel_id,
        user_id=user_id,
        historical_avg_amplitude=next_historical_avg_amplitude,
        historical_avg_frequency=next_historical_avg_frequency,
        historical_avg_char_rate=next_historical_avg_char_rate,
        char_rate_sample_count=next_char_rate_sample_count,
        total_sentence_count=next_total_sentence_count,
        baseline_sentence_count=next_baseline_sentence_count,
    )
