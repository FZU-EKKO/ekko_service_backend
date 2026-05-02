from fastapi_mail import ConnectionConfig
from config.env import get_env, get_int_env


conf = ConnectionConfig(
    MAIL_USERNAME=get_env("EKKO_MAIL_USERNAME"),
    MAIL_PASSWORD=get_env("EKKO_MAIL_PASSWORD"),
    MAIL_FROM=get_env("EKKO_MAIL_FROM"),
    MAIL_PORT=get_int_env("EKKO_MAIL_PORT", default=587),
    MAIL_SERVER=get_env("EKKO_MAIL_SERVER", default="smtp.qq.com"),
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)
