"""
Websocket connect helper with DNS fallback.

Problem:
- On some dev networks / DNS configurations, Python's libc resolver may fail
  to resolve certain websocket hostnames (e.g., stream.bybit.com) while other
  related hostnames (e.g., api.bybit.com) still resolve.
- This breaks the ingest pipeline even though connectivity is otherwise OK.

Approach:
- Try websockets.connect(uri) normally.
- If name resolution fails (socket.gaierror), resolve the hostname via aiodns
  against well-known public resolvers and connect using a pre-connected socket.
- Keep TLS SNI / Host header aligned to the original hostname so certificates
  still validate.

This only changes behavior on resolution failure; the happy path is unchanged.
"""

from __future__ import annotations

import os
import socket
import ssl
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import aiodns


@dataclass(frozen=True)
class WsDnsFallbackConfig:
    enabled: bool = True
    nameservers: tuple[str, ...] = ("8.8.8.8", "1.1.1.1")
    timeout_sec: float = 2.0
    tries: int = 1


def _dns_fallback_config_from_env() -> WsDnsFallbackConfig:
    enabled = os.getenv("WS_DNS_FALLBACK_ENABLED", "true").lower() in {"1", "true", "yes"}
    raw = os.getenv("WS_DNS_FALLBACK_NAMESERVERS", "").strip()
    if raw:
        nameservers = tuple([item.strip() for item in raw.split(",") if item.strip()])
    else:
        nameservers = ("8.8.8.8", "1.1.1.1")
    timeout_sec = os.getenv("WS_DNS_FALLBACK_TIMEOUT_SEC", "").strip()
    tries = os.getenv("WS_DNS_FALLBACK_TRIES", "").strip()
    try:
        timeout_val = float(timeout_sec) if timeout_sec else 2.0
    except ValueError:
        timeout_val = 2.0
    try:
        tries_val = int(tries) if tries else 1
    except ValueError:
        tries_val = 1
    return WsDnsFallbackConfig(enabled=enabled, nameservers=nameservers, timeout_sec=timeout_val, tries=tries_val)


async def _resolve_a(host: str, cfg: WsDnsFallbackConfig) -> list[str]:
    resolver = aiodns.DNSResolver(
        nameservers=list(cfg.nameservers),
        timeout=cfg.timeout_sec,
        tries=cfg.tries,
    )
    # Prefer IPv4; websockets + asyncio socket connect logic here is IPv4-only.
    result = await resolver.gethostbyname(host, socket.AF_INET)
    return list(getattr(result, "addresses", []) or [])


async def ws_connect_with_dns_fallback(uri: str, *, logger=None, **kwargs):
    """
    Connect to a websocket URI with DNS fallback for name resolution failures.

    kwargs are passed through to websockets.connect (ping_interval, ping_timeout, etc.)
    """
    import websockets  # local import: optional dependency in some deployments

    try:
        return await websockets.connect(uri, **kwargs)
    except socket.gaierror as e:
        cfg = _dns_fallback_config_from_env()
        if not cfg.enabled:
            raise

        parsed = urlparse(uri)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        if not host:
            raise

        ips: list[str] = []
        try:
            ips = await _resolve_a(host, cfg)
        except Exception:
            # If fallback resolution also fails, re-raise original.
            raise e

        if not ips:
            raise e

        # Connect to the first resolved IP. If this becomes an issue,
        # we can iterate over IPs with retries.
        ip = ips[0]

        if logger:
            try:
                logger.warning(
                    "ws_dns_fallback_used",
                    extra={"host": host, "ip": ip, "nameservers": list(cfg.nameservers)},
                )
            except Exception:
                pass

        loop = __import__("asyncio").get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, (ip, port))
        except Exception:
            sock.close()
            raise

        # Ensure TLS uses SNI for the original hostname.
        if parsed.scheme == "wss":
            ssl_ctx = kwargs.pop("ssl", None)
            if ssl_ctx is None or ssl_ctx is True:
                ssl_ctx = ssl.create_default_context()
            kwargs["ssl"] = ssl_ctx
            kwargs.setdefault("server_hostname", host)

        # Pass the connected socket so websockets doesn't perform DNS resolution.
        kwargs["sock"] = sock
        return await websockets.connect(uri, **kwargs)

