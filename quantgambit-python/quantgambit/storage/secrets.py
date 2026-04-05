"""Secrets Provider - Exchange credentials loader (AWS + local).

This module mirrors the encryption scheme used by the Node.js backend
(deeptrader-backend/services/secretsProvider.js) to enable the Python
runtime to securely fetch exchange credentials without passing them
through Redis or environment variables.

Security Design:
- Credentials are encrypted at rest using AES-256-GCM
- Key is derived from a master password using scrypt
- Only the secret_id (path reference) is passed through the message queue
- Runtime decrypts credentials only when needed for live trading

AWS parity:
- In production, the Node backend stores credentials in AWS Secrets Manager
  at the secret name/path `deeptrader/<env>/<userId>/<exchange>/<credentialId>`.
- The runtime needs to read those secrets in AWS as well. Set `SECRETS_PROVIDER=aws`
  in ECS to enable that backend. Local dev remains file-based by default.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from quantgambit.observability.logger import log_info, log_warning, log_error


@dataclass
class ExchangeCredentials:
    """Exchange API credentials."""
    api_key: str
    secret_key: str
    passphrase: Optional[str] = None  # Required for OKX

    def to_dict(self) -> dict:
        result = {
            "api_key": self.api_key,
            "secret_key": self.secret_key,
        }
        if self.passphrase:
            result["passphrase"] = self.passphrase
        return result


class SecretsProvider:
    """Fetch exchange credentials from AWS or local secrets store.
    
    Provider selection:
    - `SECRETS_PROVIDER=aws` (or `secretsmanager`) -> AWS Secrets Manager
    - otherwise -> local encrypted keystore (deeptrader-backend/.secrets/<env>)
    """

    # Default paths - can be overridden via environment
    # Path: secrets.py -> storage -> quantgambit -> quantgambit-python -> deeptrader-new
    DEFAULT_SECRETS_DIR = Path(__file__).parent.parent.parent.parent / "deeptrader-backend" / ".secrets"
    DEFAULT_ENVIRONMENT = "dev"
    SALT = b"deeptrader-salt"
    
    def __init__(
        self,
        secrets_dir: Optional[Path] = None,
        environment: Optional[str] = None,
        master_password: Optional[str] = None,
    ):
        """Initialize the secrets provider.
        
        Args:
            secrets_dir: Base directory for secrets (default: deeptrader-backend/.secrets)
            environment: Environment subdirectory (default: dev)
            master_password: Master password for decryption (default: from env or dev key)
        """
        raw_provider = (os.getenv("SECRETS_PROVIDER") or os.getenv("SECRETS_BACKEND") or "local").strip().lower()
        # Normalize a few common values.
        if raw_provider in {"aws", "aws_secrets_manager", "secretsmanager", "secrets-manager"}:
            self.provider = "aws"
        else:
            self.provider = "local"

        self.environment = environment or os.getenv("DEEPTRADER_ENV", self.DEFAULT_ENVIRONMENT)

        # AWS Secrets Manager mode
        self._aws_client = None
        if self.provider == "aws":
            # Lazy import: keeps local dev lightweight even if boto3 isn't installed.
            import boto3  # type: ignore

            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
            self._aws_client = boto3.client("secretsmanager", region_name=region) if region else boto3.client("secretsmanager")
            log_info(
                "secrets_provider_init",
                provider="aws",
                environment=self.environment,
                region=region or "default",
            )
            return

        # Local encrypted keystore mode
        self.secrets_dir = secrets_dir or Path(os.getenv("SECRETS_DIR", str(self.DEFAULT_SECRETS_DIR)))
        self.master_password = master_password or os.getenv("SECRETS_MASTER_PASSWORD", "dev-master-key-change-in-prod")
        
        # Derive encryption key using scrypt (same as Node.js)
        self._encryption_key = hashlib.scrypt(
            self.master_password.encode("utf-8"),
            salt=self.SALT,
            n=2**14,  # scrypt default N
            r=8,      # scrypt default r
            p=1,      # scrypt default p
            dklen=32, # 256-bit key
        )
        
        self._full_secrets_path = self.secrets_dir / self.environment
        log_info("secrets_provider_init", provider="local", secrets_dir=str(self._full_secrets_path), environment=self.environment)

    def _sanitize_secret_id(self, secret_id: str) -> str:
        """Convert secret_id to filesystem-safe filename (same as Node.js)."""
        return secret_id.replace("/", "__")

    def _build_file_path(self, secret_id: str) -> Path:
        """Build the full path to an encrypted secrets file."""
        safe_name = self._sanitize_secret_id(secret_id)
        return self._full_secrets_path / f"{safe_name}.enc"

    def _decrypt(self, encrypted_data: dict) -> dict:
        """Decrypt data using AES-256-GCM (same as Node.js).
        
        The encrypted data format is:
        {
            "iv": base64 encoded IV,
            "data": base64 encoded ciphertext,
            "tag": base64 encoded auth tag
        }
        """
        try:
            iv = base64.b64decode(encrypted_data["iv"])
            ciphertext = base64.b64decode(encrypted_data["data"])
            tag = base64.b64decode(encrypted_data["tag"])
            
            # AES-GCM expects ciphertext + tag concatenated
            aesgcm = AESGCM(self._encryption_key)
            ciphertext_with_tag = ciphertext + tag
            
            plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            log_error("secrets_decrypt_failed", error=str(exc))
            raise ValueError(f"Failed to decrypt credentials: {exc}")

    def get_credentials(self, secret_id: str) -> Optional[ExchangeCredentials]:
        """Fetch and decrypt credentials by secret_id.
        
        Args:
            secret_id: The secret identifier (e.g., deeptrader/dev/tenant/exchange/credential_id)
            
        Returns:
            ExchangeCredentials if found and decrypted, None otherwise
        """
        if not secret_id:
            log_warning("secrets_get_no_id", message="No secret_id provided")
            return None

        if self.provider == "aws":
            return self._get_credentials_from_aws(secret_id)
            
        file_path = self._build_file_path(secret_id)
        
        if not file_path.exists():
            log_warning(
                "secrets_file_not_found",
                secret_id=secret_id,
                path=str(file_path),
            )
            return None
        
        try:
            with open(file_path, "r") as f:
                encrypted_data = json.load(f)
            
            decrypted = self._decrypt(encrypted_data)
            
            credentials = ExchangeCredentials(
                api_key=decrypted.get("apiKey", ""),
                secret_key=decrypted.get("secretKey", ""),
                passphrase=decrypted.get("passphrase"),
            )
            
            # Mask key for logging
            masked_key = credentials.api_key[:8] + "..." if credentials.api_key else "N/A"
            log_info(
                "secrets_loaded",
                secret_id=secret_id,
                api_key_prefix=masked_key,
                has_passphrase=bool(credentials.passphrase),
            )
            
            return credentials
            
        except json.JSONDecodeError as exc:
            log_error(
                "secrets_json_error",
                secret_id=secret_id,
                error=str(exc),
            )
            return None
        except Exception as exc:
            log_error(
                "secrets_load_failed",
                secret_id=secret_id,
                error=str(exc),
            )
            return None

    def _get_credentials_from_aws(self, secret_id: str) -> Optional[ExchangeCredentials]:
        """Fetch credentials from AWS Secrets Manager.

        The Node backend stores a JSON string in `SecretString`, typically like:
          {"apiKey":"...","secretKey":"...","passphrase":"..."}
        """
        if not self._aws_client:
            log_error("secrets_aws_client_missing", secret_id=secret_id)
            return None
        try:
            resp = self._aws_client.get_secret_value(SecretId=secret_id)
        except Exception as exc:
            # Avoid importing botocore exceptions just for name checks.
            name = exc.__class__.__name__
            if name in {"ResourceNotFoundException"}:
                log_warning("secrets_aws_not_found", secret_id=secret_id)
                return None
            log_error("secrets_aws_get_failed", secret_id=secret_id, error=str(exc))
            return None

        secret_str = resp.get("SecretString")
        if not secret_str:
            log_warning("secrets_aws_empty", secret_id=secret_id)
            return None
        try:
            data = json.loads(secret_str)
        except Exception as exc:
            log_error("secrets_aws_json_error", secret_id=secret_id, error=str(exc))
            return None

        # Support both camelCase and snake_case.
        api_key = data.get("apiKey") or data.get("api_key") or ""
        secret_key = data.get("secretKey") or data.get("secret_key") or ""
        passphrase = data.get("passphrase") or data.get("passPhrase") or data.get("pass_phrase")

        masked_key = api_key[:8] + "..." if api_key else "N/A"
        log_info(
            "secrets_loaded",
            provider="aws",
            secret_id=secret_id,
            api_key_prefix=masked_key,
            has_passphrase=bool(passphrase),
        )
        return ExchangeCredentials(api_key=api_key, secret_key=secret_key, passphrase=passphrase)

    def credentials_exist(self, secret_id: str) -> bool:
        """Check if credentials file exists for a secret_id."""
        if not secret_id:
            return False
        if self.provider == "aws":
            # Best-effort existence check without raising.
            if not self._aws_client:
                return False
            try:
                self._aws_client.describe_secret(SecretId=secret_id)
                return True
            except Exception:
                return False
        file_path = self._build_file_path(secret_id)
        return file_path.exists()
    
    # Alias for backward compatibility
    def get_exchange_credentials(self, secret_id: str) -> Optional[ExchangeCredentials]:
        """Alias for get_credentials()."""
        return self.get_credentials(secret_id)


# Global singleton instance (lazy initialized)
_provider: Optional[SecretsProvider] = None


def get_secrets_provider() -> SecretsProvider:
    """Get or create the global secrets provider instance."""
    global _provider
    if _provider is None:
        _provider = SecretsProvider()
    return _provider


def get_exchange_credentials(secret_id: str) -> Optional[ExchangeCredentials]:
    """Convenience function to get credentials using the global provider."""
    return get_secrets_provider().get_credentials(secret_id)

