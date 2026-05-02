from config.env import get_env, get_int_env


LIVEKIT_URL = get_env("EKKO_LIVEKIT_URL", default="")
LIVEKIT_API_KEY = get_env("EKKO_LIVEKIT_API_KEY", default="")
LIVEKIT_API_SECRET = get_env("EKKO_LIVEKIT_API_SECRET", default="")
LIVEKIT_TOKEN_EXPIRE_SECONDS = get_int_env(
    "EKKO_LIVEKIT_TOKEN_EXPIRE_SECONDS",
    default=3600,
)


def livekit_is_configured() -> bool:
    return bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)
