import os

from dotenv import load_dotenv


load_dotenv()


def get_env(*names: str, default=None):
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def get_int_env(*names: str, default: int) -> int:
    value = get_env(*names, default=None)
    if value is None:
        return default
    return int(value)


def get_float_env(*names: str, default: float) -> float:
    value = get_env(*names, default=None)
    if value is None:
        return default
    return float(value)


def get_bool_env(*names: str, default: bool = False) -> bool:
    value = get_env(*names, default=None)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
