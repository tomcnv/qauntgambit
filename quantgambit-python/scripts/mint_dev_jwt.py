#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Dict


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _sign(message: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()


def mint_jwt(claims: Dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = _b64url(_sign(signing_input, secret))
    return f"{header_b64}.{payload_b64}.{signature}"


def main() -> int:
    secret = os.getenv("AUTH_JWT_SECRET", "dev_secret")
    tenant_id = os.getenv("AUTH_TENANT_ID", "t1")
    bot_id = os.getenv("AUTH_BOT_ID", "b1")
    scopes = os.getenv("AUTH_SCOPES", "bot:read bot:control backtest:read")
    ttl_sec = int(os.getenv("AUTH_TTL_SEC", "3600"))
    now = int(time.time())
    claims = {
        "sub": "dev-user",
        "tenant_id": tenant_id,
        "bot_id": bot_id,
        "scope": scopes,
        "iat": now,
        "exp": now + ttl_sec,
    }
    token = mint_jwt(claims, secret)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
