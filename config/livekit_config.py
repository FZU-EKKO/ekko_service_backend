from config.env import get_env, get_int_env


LIVEKIT_INTERNAL_URL = get_env("EKKO_LIVEKIT_INTERNAL_URL", default="")
LIVEKIT_PUBLIC_URL = get_env("EKKO_LIVEKIT_PUBLIC_URL", default="")
LIVEKIT_URL = get_env("EKKO_LIVEKIT_URL", default="")
LIVEKIT_API_KEY = get_env("EKKO_LIVEKIT_API_KEY", default="")
LIVEKIT_API_SECRET = get_env("EKKO_LIVEKIT_API_SECRET", default="")
LIVEKIT_TOKEN_EXPIRE_SECONDS = get_int_env(
    "EKKO_LIVEKIT_TOKEN_EXPIRE_SECONDS",
    default=3600,
)


def get_livekit_internal_url() -> str:
    return LIVEKIT_INTERNAL_URL or LIVEKIT_URL


def get_livekit_public_url() -> str:
    return LIVEKIT_PUBLIC_URL or LIVEKIT_URL or LIVEKIT_INTERNAL_URL


def livekit_is_configured() -> bool:
    return bool(get_livekit_public_url() and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)
