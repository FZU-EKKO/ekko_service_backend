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
    except Exception as e:
        print(f"获取缓存失败: {e}")
        return None


async def get_json_cache(key: str):
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        print(f"获取 JSON 缓存失败: {e}")
        return None


async def set_cache(key: str, value: Any, expire: int = 60 * 2):
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        await redis_client.set(key, value, expire)
        return True
    except Exception as e:
        print(f"设置缓存失败: {e}")
        return False
