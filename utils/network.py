from __future__ import annotations

import ipaddress
from urllib import parse


def should_bypass_proxy(url: str) -> bool:
    hostname = (parse.urlparse(url).hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return address.is_loopback or address.is_private or address.is_link_local
    except ValueError:
        return False
