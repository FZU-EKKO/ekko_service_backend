import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import users, domain, channel, email, upload, voice_message, channel_analysis
from utils.exception_handler import register_exception_handler
from utils.file_storage import UPLOAD_ROOT, ensure_upload_dirs

ekko = FastAPI()
logger = logging.getLogger("ekko")

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


