import json
from typing import Any

import redis.asyncio as redis

from config.env import get_env, get_int_env


REDIS_HOST = get_env("EKKO_REDIS_HOST", default="127.0.0.1")
REDIS_PASSWORD = get_env("EKKO_REDIS_PASSWORD")
REDIS_PORT = get_int_env("EKKO_REDIS_PORT", default=6379)
REDIS_DB = get_int_env("EKKO_REDIS_DB", default=0)


redis_client = redis.Redis(
    host=REDIS_HOST,
    password=REDIS_PASSWORD,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
)


async def get_cache(key: str):
    try:
        return await redis_client.get(key)
    except Exception as exc:
        print(f"Failed to get cache: {exc}")
        return None


async def get_json_cache(key: str):
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as exc:
        print(f"Failed to get JSON cache: {exc}")
        return None


async def set_cache(key: str, value: Any, expire: int = 60 * 2):
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        await redis_client.set(key, value, expire)
        return True
    except Exception as exc:
        print(f"Failed to set cache: {exc}")
        return False


async def delete_cache(key: str):
    try:
        await redis_client.delete(key)
        return True
    except Exception as exc:
        print(f"Failed to delete cache: {exc}")
        return False


async def push_json_list(key: str, value: Any, expire: int = 60 * 30):
    try:
        await redis_client.rpush(key, json.dumps(value, ensure_ascii=False))
        await redis_client.expire(key, expire)
        return True
    except Exception as exc:
        print(f"Failed to push JSON list cache: {exc}")
        return False


async def incr_cache(key: str, expire: int = 60 * 30):
    try:
        value = await redis_client.incr(key)
        await redis_client.expire(key, expire)
        return int(value)
    except Exception as exc:
        print(f"Failed to increment cache: {exc}")
        return None


async def get_json_list(key: str, start: int = 0, end: int = -1):
    try:
        rows = await redis_client.lrange(key, start, end)
        return [json.loads(item) for item in rows]
    except Exception as exc:
        print(f"Failed to get JSON list cache: {exc}")
        return []
