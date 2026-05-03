from config.env import get_env, get_int_env


ASR_PROVIDER = get_env("EKKO_ASR_PROVIDER", default="remote")
ASR_LANGUAGE = get_env("EKKO_ASR_LANGUAGE", default="zh")
ASR_REMOTE_URL = get_env("EKKO_ASR_REMOTE_URL", default="")
ASR_REMOTE_TOKEN = get_env("EKKO_ASR_REMOTE_TOKEN", default="")
ASR_REMOTE_TIMEOUT_SECONDS = get_int_env("EKKO_ASR_REMOTE_TIMEOUT_SECONDS", default=30)
ASR_ENERGY_THRESHOLD = get_int_env("EKKO_ASR_ENERGY_THRESHOLD", default=450)
ASR_SILENCE_MS = get_int_env("EKKO_ASR_SILENCE_MS", default=700)
ASR_MAX_UTTERANCE_MS = get_int_env("EKKO_ASR_MAX_UTTERANCE_MS", default=6000)
ASR_MIN_UTTERANCE_MS = get_int_env("EKKO_ASR_MIN_UTTERANCE_MS", default=500)
ASR_PROMPT_CHARS = get_int_env("EKKO_ASR_PROMPT_CHARS", default=128)
