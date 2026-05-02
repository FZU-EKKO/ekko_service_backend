from fastapi import APIRouter, HTTPException, Query
from fastapi_mail import MessageType
from pydantic import NameEmail

from config import cache_config
from config.env import get_int_env
from schemas.email import Email
from utils import email
from utils.random_string import gen_random_string
from utils.response import success_response


ekko = APIRouter(prefix="/api/email", tags=["email"])


@ekko.post("/send")
async def send_email(_email: Email):
    subtype = MessageType.plain if _email.subtype == "plain" else MessageType.html
    await email.send_email(
        subject=_email.subject,
        body=_email.body,
        recipients=_email.recipients,
        subtype=subtype,
    )
    return success_response(message="邮件发送成功")


@ekko.get("/send/get_verify_code")
async def get_verify_code(
    email_addr: str = Query(..., alias="email"),
    name: str = Query("user", alias="name"),
):
    verify_code = gen_random_string(
        get_int_env("EKKO_VERIFY_CODE_LENGTH", default=6),
        False,
    )
    cached = await cache_config.set_cache(
        email_addr,
        verify_code,
        get_int_env("EKKO_VERIFY_EXPIRE_TIME", default=120),
    )
    if not cached:
        raise HTTPException(status_code=500, detail="验证码缓存失败")

    await email.send_email(
        subject="ekko验证码",
        body=f"您的验证码为: {verify_code}",
        recipients=[NameEmail(name=name, email=email_addr)],
        subtype=MessageType.plain,
    )
    return success_response(message="验证码发送成功，请注意查收")
