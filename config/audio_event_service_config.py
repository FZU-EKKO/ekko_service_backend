from config.env import get_bool_env, get_env, get_float_env, get_int_env


AUDIO_EVENT_ENABLED = get_bool_env("EKKO_AUDIO_EVENT_ENABLED", default=True)
AUDIO_EVENT_REMOTE_URL = get_env("EKKO_AUDIO_EVENT_REMOTE_URL", default="")
AUDIO_EVENT_REMOTE_TOKEN = get_env("EKKO_AUDIO_EVENT_REMOTE_TOKEN", default="")
AUDIO_EVENT_REMOTE_TIMEOUT_SECONDS = get_int_env("EKKO_AUDIO_EVENT_REMOTE_TIMEOUT_SECONDS", default=15)
AUDIO_EVENT_REMOTE_TOP_K = get_int_env("EKKO_AUDIO_EVENT_REMOTE_TOP_K", default=8)
AUDIO_EVENT_ENFORCE_FILTER = get_env("EKKO_AUDIO_EVENT_ENFORCE_FILTER", default="true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AUDIO_EVENT_MIN_SPEECH_SCORE = get_float_env("EKKO_AUDIO_EVENT_MIN_SPEECH_SCORE", default=0.35)
