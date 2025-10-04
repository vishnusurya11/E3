#!/usr/bin/env python3
"""
MASTER CLI - Combined Audiobook and Gutenberg Automation

Runs both audiobook and gutenberg CLIs in sequence every 5 minutes.
Provides unified automation for the complete E3 pipeline.
"""

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# Import automation functions
import sys
sys.path.append('audiobook_agent')
sys.path.append('gutenberg_agent')

from audiobook_cli import run_audiobook_automation
from gutenberg_cli import run_gutenberg_automation


# Configuration
LOOP_INTERVAL_MINUTES = 5


def setup_logging():
    """Setup rotating log handler for master automation."""
    logger = logging.getLogger('master')
    logger.setLevel(logging.INFO)

    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)

    handler = TimedRotatingFileHandler(
        'logs/master.log',
        when='D',           # Daily rotation
        interval=1,         # Every 1 day
        backupCount=10      # Keep 10 days
    )

    # Pipe-separated format
    formatter = logging.Formatter('%(asctime)s|%(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def log_and_print(system, status, message):
    """Log to file and print to terminal with consistent format."""
    timestamp = datetime.now().isoformat()
    log_msg = f"MASTER|{system}|{status}|{message}"

    # Print to terminal
    print(f"{timestamp}|{log_msg}")

    # Log to file
    logger.info(log_msg)


# Initialize logger
logger = setup_logging()


def main():
    """
    Master CLI - runs both audiobook and gutenberg automation in sequence.
    """
    print("MASTER CLI - AUDIOBOOK + GUTENBERG AUTOMATION")
    print(f"Running every {LOOP_INTERVAL_MINUTES} minutes")
    print(f"Working directory: {os.getcwd()}")
    print("Press Ctrl+C to stop")
    print("=" * 70)

    run_count = 0
    try:
        while True:
            run_count += 1
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[Master Run #{run_count}] {timestamp}")
            print("#" * 70)

            try:
                # Step 1: Run Audiobook CLI automation
                log_and_print("AUDIOBOOK", "STARTING", "Running audiobook automation")
                print("=== AUDIOBOOK AUTOMATION ===")

                audiobook_success = run_audiobook_automation()

                if audiobook_success:
                    log_and_print("AUDIOBOOK", "SUCCESS", "Audiobook automation completed successfully")
                else:
                    log_and_print("AUDIOBOOK", "ERROR", "Audiobook automation failed")

                print()

                # Step 2: Run Gutenberg CLI automation
                log_and_print("GUTENBERG", "STARTING", "Running gutenberg automation")
                print("=== GUTENBERG AUTOMATION ===")

                gutenberg_success = run_gutenberg_automation()

                if gutenberg_success:
                    log_and_print("GUTENBERG", "SUCCESS", "Gutenberg automation completed successfully")
                else:
                    log_and_print("GUTENBERG", "ERROR", "Gutenberg automation failed")

                print()

                # Overall result
                if audiobook_success and gutenberg_success:
                    print(f"SUCCESS: Master Run #{run_count} - Both systems completed successfully")
                    logger.info(f"MASTER|AUTOMATION|RUN_{run_count}|SUCCESS|Both systems completed")
                else:
                    print(f"PARTIAL: Master Run #{run_count} - Some systems failed")
                    logger.info(f"MASTER|AUTOMATION|RUN_{run_count}|PARTIAL|Some systems failed")

            except KeyboardInterrupt:
                raise  # Re-raise to break out of loop
            except Exception as e:
                print(f"ERROR: Master Run #{run_count} failed: {str(e)}")
                logger.error(f"MASTER|AUTOMATION|RUN_{run_count}|ERROR|Master automation failed: {str(e)}")

            print(f"Waiting {LOOP_INTERVAL_MINUTES} minutes until next run...")
            logger.info(f"MASTER|AUTOMATION|RUN_{run_count}|WAITING|Next run in {LOOP_INTERVAL_MINUTES} minutes")
            print("#" * 70)

            # Sleep for specified interval
            time.sleep(LOOP_INTERVAL_MINUTES * 60)

    except KeyboardInterrupt:
        print(f"\nMaster automation stopped by user after {run_count} runs")
        logger.info(f"MASTER|AUTOMATION|STOPPED|User stopped automation after {run_count} runs")
        print("Goodbye!")


if __name__ == "__main__":
    main()