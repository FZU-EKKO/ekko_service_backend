import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import users, domain, channel, email, upload, voice_message, channel_analysis
from utils.exception_handler import register_exception_handler
from utils.file_storage import UPLOAD_ROOT, ensure_upload_dirs
from utils.voice_stream_segmenter import voice_stream_segmenter

ekko = FastAPI()
logger = logging.getLogger("ekko.voice_stream")

register_exception_handler(ekko)
ensure_upload_dirs()

ekko.include_router(users.ekko)
ekko.include_router(domain.ekko)
ekko.include_router(channel.ekko)
ekko.include_router(channel_analysis.ekko)
ekko.include_router(email.ekko)
ekko.include_router(upload.ekko)
ekko.include_router(voice_message.ekko)

ekko.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")


async def voice_stream_timeout_worker() -> None:
    while True:
        await asyncio.sleep(0.2)
        expired = await voice_stream_segmenter.sweep_expired()
        for emission in expired:
            try:
                await voice_message.persist_expired_stream_emission(emission)
            except Exception:
                logger.exception("voice_stream_timeout_persist_failed session=%s", emission.session_key)


@ekko.on_event("startup")
async def startup_voice_stream_worker() -> None:
    ekko.state.voice_stream_timeout_task = asyncio.create_task(voice_stream_timeout_worker())


@ekko.on_event("shutdown")
async def shutdown_voice_stream_worker() -> None:
    task = getattr(ekko.state, "voice_stream_timeout_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


origins=[
    "*"
]
ekko.add_middleware(
    CORSMiddleware,
    allow_origins=origins,    #允许的源
    allow_credentials=True,   #允许携带cookie
    allow_methods=["*"],      #允许的请求方法
    allow_headers=["*"],      #允许的请求头
)


