#!/usr/bin/env python3
"""
YouTube Token Management Utility

Simple command-line utility to manage YouTube API tokens.
"""

import sys
import os
from audiobook_agent.audiobook_helper import (
    check_youtube_token_status,
    force_youtube_reauth,
    validate_youtube_credentials_standalone
)

def print_usage():
    print("YouTube Token Manager")
    print("=" * 30)
    print("Usage: python youtube_token_manager.py [command]")
    print("")
    print("Commands:")
    print("  status    - Check current token status")
    print("  validate  - Validate credentials with detailed report")
    print("  reauth    - Force re-authentication (clears existing token)")
    print("  help      - Show this help message")

def main():
    if len(sys.argv) != 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "status":
        print("Checking YouTube token status...")
        status = check_youtube_token_status()

        print(f"Status: {status['status']}")
        print(f"Message: {status['message']}")
        print(f"Valid: {status['valid']}")

        if status.get('expiry'):
            print(f"Expires: {status['expiry']}")

        if status.get('minutes_until_expiry') is not None:
            print(f"Minutes until expiry: {status['minutes_until_expiry']:.1f}")

    elif command == "validate":
        print("Validating YouTube credentials...")
        validate_youtube_credentials_standalone()

    elif command == "reauth":
        print("Forcing YouTube re-authentication...")
        success = force_youtube_reauth()

        if success:
            print("SUCCESS: Re-authentication prepared. Next YouTube operation will trigger login.")
        else:
            print("ERROR: Failed to clear credentials.")

    elif command == "help":
        print_usage()

    else:
        print(f"❌ Unknown command: {command}")
        print_usage()
        sys.exit(1)

if __name__ == "__main__":
    main()