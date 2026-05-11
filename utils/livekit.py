import base64
import hashlib
import hmac
import json
import logging
import time
from urllib import parse
from urllib import request
from urllib.error import HTTPError, URLError

from config.livekit_config import (
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_TOKEN_EXPIRE_SECONDS,
    get_livekit_internal_url,
    get_livekit_public_url,
    livekit_is_configured,
)

logger = logging.getLogger("ekko.livekit")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_room_name(domain_id: str, channel_id: int) -> str:
    return f"ekko-domain-{domain_id}-channel-{channel_id}"


def _create_livekit_token(
    *,
    payload: dict,
) -> str:
    if not livekit_is_configured():
        raise ValueError("LiveKit configuration is incomplete")

    header = {"alg": "HS256", "typ": "JWT"}
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(
        LIVEKIT_API_SECRET.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def create_livekit_access_token(
    *,
    identity: str,
    room_name: str,
    participant_name: str,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
) -> str:
    now = int(time.time())
    return _create_livekit_token(
        payload={
            "iss": LIVEKIT_API_KEY,
            "sub": identity,
            "nbf": now,
            "exp": now + LIVEKIT_TOKEN_EXPIRE_SECONDS,
            "name": participant_name,
            "video": {
                "room": room_name,
                "roomJoin": True,
                "canPublish": can_publish,
                "canSubscribe": can_subscribe,
                "canPublishData": can_publish_data,
            },
            "metadata": "",
        }
    )


def create_livekit_server_token() -> str:
    now = int(time.time())
    return _create_livekit_token(
        payload={
            "iss": LIVEKIT_API_KEY,
            "sub": "ekko-backend",
            "nbf": now,
            "exp": now + LIVEKIT_TOKEN_EXPIRE_SECONDS,
            "video": {
                "roomCreate": True,
                "roomAdmin": True,
                "roomList": True,
            },
            "metadata": "",
        }
    )


def _internal_livekit_http_base() -> str:
    internal_url = get_livekit_internal_url().strip()
    if not internal_url:
        raise ValueError("LiveKit internal URL is not configured")

    parsed = parse.urlparse(internal_url)
    if parsed.scheme not in {"ws", "wss", "http", "https"}:
        raise ValueError(f"Unsupported LiveKit internal URL scheme: {parsed.scheme}")

    http_scheme = "https" if parsed.scheme in {"wss", "https"} else "http"
    return parse.urlunparse((http_scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def ensure_livekit_room(*, room_name: str) -> None:
    if not livekit_is_configured():
        raise ValueError("LiveKit configuration is incomplete")

    endpoint = f"{_internal_livekit_http_base()}/twirp/livekit.RoomService/CreateRoom"
    payload = json.dumps({"name": room_name}, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {create_livekit_server_token()}",
    }
    req = request.Request(endpoint, data=payload, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=10) as resp:
            resp.read()
        logger.info("livekit_room_ensured room=%s via=%s", room_name, endpoint)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        already_exists = exc.code == 409 or "already exists" in body.lower()
        if already_exists:
            logger.info("livekit_room_exists room=%s via=%s", room_name, endpoint)
            return
        logger.error("livekit_room_create_failed room=%s status=%s body=%s", room_name, exc.code, body)
        raise RuntimeError(f"LiveKit room create failed: HTTP {exc.code}") from exc
    except URLError as exc:
        logger.error("livekit_internal_connect_failed room=%s endpoint=%s reason=%s", room_name, endpoint, exc.reason)
        raise RuntimeError(f"LiveKit internal connection failed: {exc.reason}") from exc


def get_livekit_connection_info(*, identity: str, room_name: str, participant_name: str) -> dict:
    ensure_livekit_room(room_name=room_name)
    token = create_livekit_access_token(
        identity=identity,
        room_name=room_name,
        participant_name=participant_name,
    )
    return {
        "livekit_url": get_livekit_public_url(),
        "token": token,
        "room_name": room_name,
        "participant_identity": identity,
        "participant_name": participant_name,
    }
