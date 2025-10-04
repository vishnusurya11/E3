#!/usr/bin/env python3
"""
Test YouTube credential management functionality.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from audiobook_agent.audiobook_helper import check_youtube_token_status

def create_test_credentials(minutes_until_expiry=60):
    """Create test credentials file for testing."""
    future_time = datetime.now(timezone.utc) + timedelta(minutes=minutes_until_expiry)

    test_credentials = {
        "token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "universe_domain": "googleapis.com",
        "account": "",
        "expiry": future_time.isoformat()
    }

    with open("youtube_credentials.json", "w") as f:
        json.dump(test_credentials, f, indent=2)

    print(f"Created test credentials expiring in {minutes_until_expiry} minutes")

def test_credential_status():
    """Test various credential scenarios."""

    print("=" * 50)
    print("Testing YouTube Credential Management")
    print("=" * 50)

    # Test 1: Missing credentials
    if os.path.exists("youtube_credentials.json"):
        os.remove("youtube_credentials.json")

    print("\n1. Testing missing credentials:")
    status = check_youtube_token_status()
    print(f"   Status: {status['status']}")
    print(f"   Message: {status['message']}")

    # Test 2: Valid credentials (60 minutes left)
    print("\n2. Testing valid credentials:")
    create_test_credentials(60)
    status = check_youtube_token_status()
    print(f"   Status: {status['status']}")
    print(f"   Message: {status['message']}")
    print(f"   Minutes until expiry: {status.get('minutes_until_expiry', 'N/A'):.1f}")

    # Test 3: Expiring soon credentials (3 minutes left)
    print("\n3. Testing credentials expiring soon:")
    create_test_credentials(3)
    status = check_youtube_token_status()
    print(f"   Status: {status['status']}")
    print(f"   Message: {status['message']}")
    print(f"   Minutes until expiry: {status.get('minutes_until_expiry', 'N/A'):.1f}")

    # Test 4: Expired credentials
    print("\n4. Testing expired credentials:")
    create_test_credentials(-30)  # 30 minutes ago
    status = check_youtube_token_status()
    print(f"   Status: {status['status']}")
    print(f"   Message: {status['message']}")

    # Cleanup
    if os.path.exists("youtube_credentials.json"):
        os.remove("youtube_credentials.json")

    print("\n" + "=" * 50)
    print("Test completed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    test_credential_status()