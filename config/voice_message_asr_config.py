from config.env import get_env, get_int_env


VOICE_MESSAGE_ASR_LANGUAGE = get_env("EKKO_ASR_LANGUAGE", default="zh")
VOICE_MESSAGE_ASR_REMOTE_URL = get_env("EKKO_ASR_REMOTE_URL", default="")
VOICE_MESSAGE_ASR_REMOTE_TOKEN = get_env("EKKO_ASR_REMOTE_TOKEN", default="")
VOICE_MESSAGE_ASR_REMOTE_TIMEOUT_SECONDS = get_int_env("EKKO_ASR_REMOTE_TIMEOUT_SECONDS", default=30)
