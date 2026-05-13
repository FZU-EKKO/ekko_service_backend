from __future__ import annotations

from pathlib import Path

from utils.file_storage import BASE_DIR, UPLOAD_ROOT


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
