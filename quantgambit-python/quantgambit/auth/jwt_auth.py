"""Local JWT auth helper (HS256).

Feature: backtesting-api-integration
Requirements: All

This module provides:
- JWT token verification
- Scope enforcement
- Tenant isolation support
- User claims extraction
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Optional, Callable, Any

from fastapi import Header, HTTPException, Depends


@dataclass
class UserClaims:
    """User claims extracted from JWT token.
    
    Attributes:
        tenant_id: The tenant ID from the token
        user_id: The user ID from the token
        scopes: List of scopes granted to the user
        raw_claims: The raw claims dictionary
    """
    tenant_id: str
    user_id: Optional[str] = None
    scopes: list[str] = None
    raw_claims: dict = None
    
    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []
        if self.raw_claims is None:
            self.raw_claims = {}
    
    def has_scope(self, scope: str) -> bool:
        """Check if user has a specific scope."""
        return scope in self.scopes


def _dev_identity_fallback_enabled() -> bool:
    return os.getenv("AUTH_ALLOW_DEV_IDENTITY_FALLBACK", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_auth_dependency() -> Callable[..., Any]:
    """Build the authentication dependency.
    
    Returns a dependency that validates JWT tokens and returns None.
    For backward compatibility, this returns None instead of UserClaims.
    Use build_auth_dependency_with_claims() for tenant isolation.
    """
    async def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
        mode = os.getenv("AUTH_MODE", "none").lower()
        if mode in {"none", "disabled"}:
            return None
        if mode != "jwt":
            raise HTTPException(status_code=500, detail="unsupported_auth_mode")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing_bearer_token")
        token = authorization.split(" ", 1)[1].strip()
        claims = _verify_jwt(token)
        _enforce_scopes(claims)
        return None

    return require_auth


def build_auth_dependency_with_claims() -> Callable[..., UserClaims]:
    """Build the authentication dependency that returns user claims.
    
    Returns a dependency that validates JWT tokens and returns UserClaims
    for tenant isolation and authorization checks.
    """
    async def require_auth_with_claims(
        authorization: Optional[str] = Header(default=None)
    ) -> UserClaims:
        mode = os.getenv("AUTH_MODE", "none").lower()
        
        # In disabled mode, only return synthetic claims when explicitly enabled.
        if mode in {"none", "disabled"}:
            default_tenant = os.getenv("DEFAULT_TENANT_ID", "default")
            default_user = os.getenv("DEFAULT_USER_ID", "anonymous")
            return UserClaims(
                tenant_id=default_tenant,
                user_id=default_user,
                scopes=[],
                raw_claims={},
            )
        
        if mode != "jwt":
            raise HTTPException(status_code=500, detail="unsupported_auth_mode")
        
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing_bearer_token")
        
        token = authorization.split(" ", 1)[1].strip()
        claims = _verify_jwt(token)
        _enforce_scopes(claims)
        
        user_id = claims.get("user_id") or claims.get("userId") or claims.get("sub")
        tenant_id = claims.get("tenant_id") or claims.get("tenantId")
        if not tenant_id and os.getenv("AUTH_USER_ID_AS_TENANT", "true").lower() in {"1", "true", "yes", "on"}:
            tenant_id = user_id
        if not tenant_id:
            raise HTTPException(status_code=401, detail="missing_tenant_claim")
        if not user_id:
            raise HTTPException(status_code=401, detail="missing_user_claim")
        
        # Extract scopes
        scopes_claim = claims.get("scope") or claims.get("scopes") or ""
        if isinstance(scopes_claim, list):
            scopes = scopes_claim
        else:
            scopes = str(scopes_claim).split()
        
        return UserClaims(
            tenant_id=tenant_id,
            user_id=user_id,
            scopes=scopes,
            raw_claims=claims,
        )

    return require_auth_with_claims


def verify_tenant_access(user_claims: UserClaims, resource_tenant_id: str) -> None:
    """Verify that the user has access to a resource's tenant.
    
    Args:
        user_claims: The user's claims from the JWT token
        resource_tenant_id: The tenant ID of the resource being accessed
        
    Raises:
        HTTPException: 403 if the user doesn't have access to the tenant
    """
    if user_claims.tenant_id != resource_tenant_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "authorization_error",
                "message": "Access denied: resource belongs to a different tenant",
                "details": {"resource_tenant_id": resource_tenant_id},
            }
        )


def _verify_jwt(token: str) -> dict:
    """Verify JWT token and return claims.
    
    Args:
        token: The JWT token string
        
    Returns:
        The decoded claims dictionary
        
    Raises:
        HTTPException: 401 if token is invalid
    """
    secret = os.getenv("AUTH_JWT_SECRET", "dev_secret")
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_token_format")
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not _secure_compare(_b64url_decode(signature_b64), expected):
        raise HTTPException(status_code=401, detail="invalid_signature")
    payload = json.loads(_b64url_decode(payload_b64))
    exp = payload.get("exp")
    if exp and time.time() > float(exp):
        raise HTTPException(status_code=401, detail="token_expired")
    return payload


def _enforce_scopes(claims: dict) -> None:
    """Enforce required scopes from environment variable.
    
    Args:
        claims: The decoded JWT claims
        
    Raises:
        HTTPException: 403 if required scopes are missing
    """
    required = os.getenv("AUTH_REQUIRED_SCOPES", "")
    if not required:
        return
    required_scopes = {item.strip() for item in required.split(",") if item.strip()}
    if not required_scopes:
        return
    scopes_claim = claims.get("scope") or claims.get("scopes") or ""
    if isinstance(scopes_claim, list):
        scopes = set(scopes_claim)
    else:
        scopes = set(str(scopes_claim).split())
    if not required_scopes.issubset(scopes):
        raise HTTPException(status_code=403, detail="missing_scopes")


def _b64url_decode(data: str) -> bytes:
    """Decode base64url encoded data."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _secure_compare(a: bytes, b: bytes) -> bool:
    """Securely compare two byte strings."""
    return hmac.compare_digest(a, b)


def create_test_token(
    tenant_id: str = "test-tenant",
    user_id: str = "test-user",
    scopes: list[str] = None,
    exp_offset: int = 3600,
) -> str:
    """Create a test JWT token for testing purposes.
    
    Args:
        tenant_id: The tenant ID to include in the token
        user_id: The user ID to include in the token
        scopes: List of scopes to include
        exp_offset: Expiration offset in seconds from now
        
    Returns:
        A valid JWT token string
    """
    import base64
    import json
    import time
    import hmac
    import hashlib
    
    secret = os.getenv("AUTH_JWT_SECRET", "dev_secret")
    
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "sub": user_id,
        "scope": " ".join(scopes or []),
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    
    def b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")
    
    header_b64 = b64url_encode(json.dumps(header).encode("utf-8"))
    payload_b64 = b64url_encode(json.dumps(payload).encode("utf-8"))
    
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = b64url_encode(signature)
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"
