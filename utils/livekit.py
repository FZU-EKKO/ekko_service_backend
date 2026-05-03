import base64
import hashlib
import hmac
import json
import time

from config.livekit_config import (
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_TOKEN_EXPIRE_SECONDS,
    get_livekit_public_url,
    livekit_is_configured,
)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_room_name(domain_id: str, channel_id: int) -> str:
    return f"ekko-domain-{domain_id}-channel-{channel_id}"


def create_livekit_access_token(
    *,
    identity: str,
    room_name: str,
    participant_name: str,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
) -> str:
    if not livekit_is_configured():
        raise ValueError("LiveKit configuration is incomplete")

    now = int(time.time())
    payload = {
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


def get_livekit_connection_info(*, identity: str, room_name: str, participant_name: str) -> dict:
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
