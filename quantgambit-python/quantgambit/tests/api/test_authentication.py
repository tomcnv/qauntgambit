"""Unit tests for API authentication and authorization.

Feature: backtesting-api-integration
Requirements: All

Tests:
- Missing token scenarios
- Invalid token scenarios
- Tenant isolation
- User claims extraction
"""

import os
import time
import pytest
from unittest.mock import patch

from quantgambit.auth.jwt_auth import (
    build_auth_dependency,
    build_auth_dependency_with_claims,
    verify_tenant_access,
    UserClaims,
    create_test_token,
    _verify_jwt,
    _enforce_scopes,
)
from fastapi import HTTPException


class TestUserClaims:
    """Tests for UserClaims dataclass."""
    
    def test_user_claims_basic(self):
        """Test basic UserClaims creation."""
        claims = UserClaims(tenant_id="tenant-1")
        assert claims.tenant_id == "tenant-1"
        assert claims.user_id is None
        assert claims.scopes == []
        assert claims.raw_claims == {}
    
    def test_user_claims_full(self):
        """Test UserClaims with all fields."""
        claims = UserClaims(
            tenant_id="tenant-1",
            user_id="user-1",
            scopes=["read", "write"],
            raw_claims={"custom": "value"},
        )
        assert claims.tenant_id == "tenant-1"
        assert claims.user_id == "user-1"
        assert claims.scopes == ["read", "write"]
        assert claims.raw_claims == {"custom": "value"}
    
    def test_has_scope_true(self):
        """Test has_scope returns True for existing scope."""
        claims = UserClaims(tenant_id="t1", scopes=["read", "write"])
        assert claims.has_scope("read") is True
        assert claims.has_scope("write") is True
    
    def test_has_scope_false(self):
        """Test has_scope returns False for missing scope."""
        claims = UserClaims(tenant_id="t1", scopes=["read"])
        assert claims.has_scope("write") is False
        assert claims.has_scope("admin") is False


class TestCreateTestToken:
    """Tests for create_test_token utility."""
    
    def test_create_test_token_default(self):
        """Test creating a test token with defaults."""
        token = create_test_token()
        assert isinstance(token, str)
        assert token.count(".") == 2  # JWT has 3 parts
    
    def test_create_test_token_custom(self):
        """Test creating a test token with custom values."""
        token = create_test_token(
            tenant_id="custom-tenant",
            user_id="custom-user",
            scopes=["read", "write"],
        )
        assert isinstance(token, str)
        
        # Verify the token can be decoded
        claims = _verify_jwt(token)
        assert claims["tenant_id"] == "custom-tenant"
        assert claims["user_id"] == "custom-user"
        assert "read" in claims["scope"]
        assert "write" in claims["scope"]
    
    def test_create_test_token_expired(self):
        """Test creating an expired token."""
        token = create_test_token(exp_offset=-3600)  # Expired 1 hour ago
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_jwt(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "token_expired"


class TestVerifyJWT:
    """Tests for JWT verification."""
    
    def test_verify_jwt_valid(self):
        """Test verifying a valid JWT."""
        token = create_test_token(tenant_id="test-tenant")
        claims = _verify_jwt(token)
        assert claims["tenant_id"] == "test-tenant"
    
    def test_verify_jwt_invalid_format(self):
        """Test verifying a token with invalid format."""
        with pytest.raises(HTTPException) as exc_info:
            _verify_jwt("not-a-jwt")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "invalid_token_format"
    
    def test_verify_jwt_invalid_signature(self):
        """Test verifying a token with invalid signature."""
        token = create_test_token()
        # Tamper with the signature by using a different valid base64 string
        # This creates a properly formatted but incorrect signature
        parts = token.split(".")
        # Use a valid base64url string that decodes to different bytes
        parts[2] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        tampered_token = ".".join(parts)
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_jwt(tampered_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "invalid_signature"
    
    def test_verify_jwt_expired(self):
        """Test verifying an expired token."""
        token = create_test_token(exp_offset=-1)  # Expired 1 second ago
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_jwt(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "token_expired"


class TestEnforceScopes:
    """Tests for scope enforcement."""
    
    def test_enforce_scopes_no_required(self):
        """Test that no scopes required passes."""
        with patch.dict(os.environ, {"AUTH_REQUIRED_SCOPES": ""}):
            # Should not raise
            _enforce_scopes({"scope": "read write"})
    
    def test_enforce_scopes_has_required(self):
        """Test that having required scopes passes."""
        with patch.dict(os.environ, {"AUTH_REQUIRED_SCOPES": "read"}):
            # Should not raise
            _enforce_scopes({"scope": "read write"})
    
    def test_enforce_scopes_missing_required(self):
        """Test that missing required scopes fails."""
        with patch.dict(os.environ, {"AUTH_REQUIRED_SCOPES": "admin"}):
            with pytest.raises(HTTPException) as exc_info:
                _enforce_scopes({"scope": "read write"})
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "missing_scopes"
    
    def test_enforce_scopes_list_format(self):
        """Test scope enforcement with list format."""
        with patch.dict(os.environ, {"AUTH_REQUIRED_SCOPES": "read"}):
            # Should not raise
            _enforce_scopes({"scopes": ["read", "write"]})


class TestVerifyTenantAccess:
    """Tests for tenant access verification."""
    
    def test_verify_tenant_access_same_tenant(self):
        """Test that same tenant passes."""
        claims = UserClaims(tenant_id="tenant-1")
        # Should not raise
        verify_tenant_access(claims, "tenant-1")
    
    def test_verify_tenant_access_different_tenant(self):
        """Test that different tenant fails."""
        claims = UserClaims(tenant_id="tenant-1")
        
        with pytest.raises(HTTPException) as exc_info:
            verify_tenant_access(claims, "tenant-2")
        assert exc_info.value.status_code == 403
        assert "different tenant" in str(exc_info.value.detail)


class TestBuildAuthDependency:
    """Tests for build_auth_dependency."""
    
    @pytest.mark.asyncio
    async def test_auth_disabled(self):
        """Test that auth disabled mode passes without token."""
        with patch.dict(os.environ, {"AUTH_MODE": "none"}):
            auth_dep = build_auth_dependency()
            result = await auth_dep(authorization=None)
            assert result is None
    
    @pytest.mark.asyncio
    async def test_auth_missing_token(self):
        """Test that missing token fails in JWT mode."""
        with patch.dict(os.environ, {"AUTH_MODE": "jwt"}):
            auth_dep = build_auth_dependency()
            
            with pytest.raises(HTTPException) as exc_info:
                await auth_dep(authorization=None)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "missing_bearer_token"
    
    @pytest.mark.asyncio
    async def test_auth_invalid_header(self):
        """Test that invalid auth header fails."""
        with patch.dict(os.environ, {"AUTH_MODE": "jwt"}):
            auth_dep = build_auth_dependency()
            
            with pytest.raises(HTTPException) as exc_info:
                await auth_dep(authorization="Basic abc123")
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "missing_bearer_token"
    
    @pytest.mark.asyncio
    async def test_auth_valid_token(self):
        """Test that valid token passes."""
        with patch.dict(os.environ, {"AUTH_MODE": "jwt", "AUTH_REQUIRED_SCOPES": ""}):
            auth_dep = build_auth_dependency()
            token = create_test_token()
            
            result = await auth_dep(authorization=f"Bearer {token}")
            assert result is None


class TestBuildAuthDependencyWithClaims:
    """Tests for build_auth_dependency_with_claims."""
    
    @pytest.mark.asyncio
    async def test_auth_disabled_returns_default_claims(self):
        """Test that auth disabled mode returns default claims."""
        with patch.dict(os.environ, {"AUTH_MODE": "none", "DEFAULT_TENANT_ID": "default-tenant"}):
            auth_dep = build_auth_dependency_with_claims()
            claims = await auth_dep(authorization=None)
            
            assert isinstance(claims, UserClaims)
            assert claims.tenant_id == "default-tenant"
            assert claims.user_id == "anonymous"
    
    @pytest.mark.asyncio
    async def test_auth_returns_claims_from_token(self):
        """Test that valid token returns claims."""
        with patch.dict(os.environ, {"AUTH_MODE": "jwt", "AUTH_REQUIRED_SCOPES": ""}):
            auth_dep = build_auth_dependency_with_claims()
            token = create_test_token(
                tenant_id="my-tenant",
                user_id="my-user",
                scopes=["read", "write"],
            )
            
            claims = await auth_dep(authorization=f"Bearer {token}")
            
            assert isinstance(claims, UserClaims)
            assert claims.tenant_id == "my-tenant"
            assert claims.user_id == "my-user"
            assert "read" in claims.scopes
            assert "write" in claims.scopes
    
    @pytest.mark.asyncio
    async def test_auth_missing_token_fails(self):
        """Test that missing token fails in JWT mode."""
        with patch.dict(os.environ, {"AUTH_MODE": "jwt"}):
            auth_dep = build_auth_dependency_with_claims()
            
            with pytest.raises(HTTPException) as exc_info:
                await auth_dep(authorization=None)
            assert exc_info.value.status_code == 401


class TestTenantIsolation:
    """Integration tests for tenant isolation."""
    
    def test_tenant_isolation_same_tenant(self):
        """Test that same tenant can access resources."""
        claims = UserClaims(tenant_id="tenant-a", user_id="user-1")
        
        # Should not raise
        verify_tenant_access(claims, "tenant-a")
    
    def test_tenant_isolation_different_tenant(self):
        """Test that different tenant cannot access resources."""
        claims = UserClaims(tenant_id="tenant-a", user_id="user-1")
        
        with pytest.raises(HTTPException) as exc_info:
            verify_tenant_access(claims, "tenant-b")
        
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert detail["error"] == "authorization_error"
        assert "different tenant" in detail["message"]
    
    def test_tenant_isolation_error_format(self):
        """Test that tenant isolation error has correct format."""
        claims = UserClaims(tenant_id="tenant-a")
        
        with pytest.raises(HTTPException) as exc_info:
            verify_tenant_access(claims, "tenant-b")
        
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert "error" in detail
        assert "message" in detail
        assert "details" in detail
        assert detail["details"]["resource_tenant_id"] == "tenant-b"
