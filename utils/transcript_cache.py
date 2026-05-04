from __future__ import annotations

from datetime import datetime

from config.cache_config import get_json_cache, get_json_list, incr_cache, push_json_list, redis_client, set_cache
from models.transcript import TranscriptSessionStatus


TRANSCRIPT_CACHE_EXPIRE_SECONDS = 60 * 60


def session_meta_key(session_id: int) -> str:
    return f"ekko:transcript:session:{session_id}:meta"


def partial_key(session_id: int, user_id: str) -> str:
    return f"ekko:transcript:session:{session_id}:user:{user_id}:partial"


def partial_users_key(session_id: int) -> str:
    return f"ekko:transcript:session:{session_id}:partial_users"


def segments_key(session_id: int) -> str:
    return f"ekko:transcript:session:{session_id}:segments"


def next_seq_key(session_id: int) -> str:
    return f"ekko:transcript:session:{session_id}:next_seq"


def active_streams_key(session_id: int) -> str:
    return f"ekko:transcript:session:{session_id}:active_streams"


async def set_session_meta(session_id: int, *, status: str, channel_id: int | None = None, last_error: str | None = None) -> None:
    payload = {
        "status": status,
        "updated_at": datetime.now().isoformat(),
    }
    if channel_id is not None:
        payload["channel_id"] = channel_id
    if last_error:
        payload["last_error"] = last_error
    await set_cache(session_meta_key(session_id), payload, expire=TRANSCRIPT_CACHE_EXPIRE_SECONDS)


async def set_partial(session_id: int, user_id: str, payload: dict) -> None:
    await set_cache(partial_key(session_id, user_id), payload, expire=60)
    await redis_client.sadd(partial_users_key(session_id), user_id)
    await redis_client.expire(partial_users_key(session_id), TRANSCRIPT_CACHE_EXPIRE_SECONDS)


async def clear_partial(session_id: int, user_id: str) -> None:
    await set_cache(partial_key(session_id, user_id), {}, expire=5)
    await redis_client.srem(partial_users_key(session_id), user_id)


async def push_final_segment(session_id: int, payload: dict) -> None:
    await push_json_list(segments_key(session_id), payload, expire=TRANSCRIPT_CACHE_EXPIRE_SECONDS)


async def next_sequence_number(session_id: int) -> int | None:
    return await incr_cache(next_seq_key(session_id), expire=TRANSCRIPT_CACHE_EXPIRE_SECONDS)


async def get_live_state(session_id: int) -> dict:
    meta = await get_json_cache(session_meta_key(session_id)) or {}
    user_ids = []
    try:
        user_ids = list(await redis_client.smembers(partial_users_key(session_id)))
    except Exception:
        user_ids = []

    partials: dict[str, dict] = {}
    for user_id in user_ids:
        payload = await get_json_cache(partial_key(session_id, user_id))
        if payload:
            partials[user_id] = payload

    segments = await get_json_list(segments_key(session_id), 0, -1)
    return {
        "meta": meta,
        "partials": partials,
        "segments": segments,
    }


async def decrement_active_streams(session_id: int) -> int:
    remaining = await redis_client.decr(active_streams_key(session_id))
    if remaining < 0:
        await redis_client.set(active_streams_key(session_id), 0, ex=TRANSCRIPT_CACHE_EXPIRE_SECONDS)
        return 0
    return int(remaining)


async def increment_active_streams(session_id: int) -> None:
    await redis_client.incr(active_streams_key(session_id))
    await redis_client.expire(active_streams_key(session_id), TRANSCRIPT_CACHE_EXPIRE_SECONDS)
