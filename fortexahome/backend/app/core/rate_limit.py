from __future__ import annotations

import ipaddress

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()


def _trusted_proxy(remote: str) -> bool:
    configured = settings.trusted_proxy_ips_list
    if remote in configured:
        return True
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    for item in configured:
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            continue
    # A API fica vinculada apenas à rede interna do Docker/loopback.
    return address.is_private or address.is_loopback


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request) -> str:
    remote = get_remote_address(request)
    if not _trusted_proxy(remote):
        return remote

    real_ip = _valid_ip(request.headers.get("x-real-ip", ""))
    if real_ip:
        return real_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        for part in forwarded.split(","):
            candidate = _valid_ip(part)
            if candidate:
                return candidate
    return remote


limiter = Limiter(key_func=client_ip, enabled=settings.RATE_LIMIT_ENABLED, default_limits=[])
