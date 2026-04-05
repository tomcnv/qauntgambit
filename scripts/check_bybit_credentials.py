#!/usr/bin/env python3
"""Check Bybit credentials from secrets store."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "quantgambit-python"))

from quantgambit.storage.secrets import get_exchange_credentials, get_secrets_provider

secret_id = 'deeptrader/dev/11111111-1111-1111-1111-111111111111/bybit/fb213790-5ba6-4637-bccc-25e3d68d4c0c'

print(f"Looking for secret_id: {secret_id}")
print()

provider = get_secrets_provider()
print(f"Secrets dir: {provider.secrets_dir}")
print(f"Environment: {provider.environment}")
print(f"Full path: {provider._full_secrets_path}")
print()

file_path = provider._build_file_path(secret_id)
print(f"Expected file: {file_path}")
print(f"File exists: {file_path.exists()}")
print()

creds = get_exchange_credentials(secret_id)
if creds:
    print(f"✅ Credentials loaded successfully!")
    print(f"API Key: {creds.api_key[:8]}..." if creds.api_key else "API Key: None")
    print(f"Secret Key: {creds.secret_key[:8]}..." if creds.secret_key else "Secret Key: None")
    print(f"Passphrase: {creds.passphrase}")
else:
    print("❌ Credentials not found!")
