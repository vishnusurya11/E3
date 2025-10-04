#!/usr/bin/env python3
"""
Test the publish_date type handling fix for YouTube uploads.
"""

import sys
import os
from datetime import datetime

def test_publish_date_type_handling():
    """Test the fixed publish_date handling logic."""

    print("Testing publish_date type handling fix")
    print("=" * 40)

    # Test different types that might come from database
    test_cases = [
        ("String format", "20250930160000"),
        ("Integer format", 20250930160000),
        ("Future date string", "20251231120000"),
        ("Past date string", "20240101120000"),
        ("Invalid length string", "2025093016"),
        ("None value", None),
        ("Empty string", ""),
    ]

    for test_name, publish_date in test_cases:
        print(f"\n{test_name}: {publish_date} (type: {type(publish_date)})")

        try:
            # Simulate the logic from our fix
            youtube_publish_time = None

            if publish_date:
                from datetime import datetime, timezone, timedelta

                # Handle different types of publish_date
                if isinstance(publish_date, int):
                    publish_date_str = str(publish_date)
                    print(f"   Converted integer to string: {publish_date_str}")
                elif isinstance(publish_date, str):
                    publish_date_str = publish_date
                    print(f"   Already a string: {publish_date_str}")
                else:
                    publish_date_str = str(publish_date)
                    print(f"   Converted {type(publish_date)} to string: {publish_date_str}")

                # Validate string format and length
                if len(publish_date_str) != 14:
                    print(f"   ERROR: Invalid length {len(publish_date_str)}, expected 14")
                    raise ValueError(f"Invalid date format: expected 14 characters, got {len(publish_date_str)}")

                # Parse the publish date
                dt_pacific = datetime.strptime(publish_date_str, '%Y%m%d%H%M%S')
                print(f"   Parsed successfully: {dt_pacific}")

                # Convert to YouTube format
                youtube_publish_time = dt_pacific.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                print(f"   YouTube format: {youtube_publish_time}")

                # Check if future date
                now_pacific = datetime.now()
                is_future = dt_pacific > now_pacific
                print(f"   Is future date: {is_future}")

                if not is_future:
                    youtube_publish_time = None
                    print(f"   Past date - will upload immediately")

            else:
                print(f"   Empty or None - will upload immediately")

            result = "SCHEDULED" if youtube_publish_time else "IMMEDIATE"
            print(f"   RESULT: {result}")

        except Exception as e:
            print(f"   EXCEPTION: {type(e).__name__}: {e}")
            print(f"   RESULT: IMMEDIATE (due to error)")

if __name__ == "__main__":
    test_publish_date_type_handling()