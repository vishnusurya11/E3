#!/usr/bin/env python3
"""
GUTENBERG CLI - Project Gutenberg Processing Automation

Runs every 5 minutes to check for scheduled Gutenberg processing tasks.
Manages weekly metadata loading and future book selection processes.
"""

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import pytz

from gutenberg_helper import add_gutenberg_event, get_latest_step_event, should_run_metadata_load, load_catalog_to_database, process_books_from_csv
from gutenberg_bulk_downloader import run_bulk_download_as_function


# Configuration
CONTINUOUS_MODE = True  # Set to False for single run
LOOP_INTERVAL_MINUTES = 5  # Configurable interval


def setup_logging():
    """Setup rotating log handler for automation."""
    logger = logging.getLogger('gutenberg')
    logger.setLevel(logging.INFO)

    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)

    handler = TimedRotatingFileHandler(
        'logs/gutenberg.log',
        when='D',           # Daily rotation
        interval=1,         # Every 1 day
        backupCount=10      # Keep 10 days
    )

    # Pipe-separated format
    formatter = logging.Formatter('%(asctime)s|%(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def log_and_print(step_name, status, message):
    """Log to file and print to terminal with consistent format."""
    timestamp = datetime.now().isoformat()
    log_msg = f"GUTENBERG|{step_name}|{status}|{message}"

    # Print to terminal (for development)
    print(f"{timestamp}|{log_msg}")

    # Log to file (for automation)
    logger.info(log_msg)


# Initialize logger
logger = setup_logging()




def execute_load_gutenberg_metadata(current_status: str = None) -> str:
    """
    LOAD_GUTENBERG_METADATA: Download and update Gutenberg catalog weekly

    Process:
    1. Download RDF archive using bulk downloader
    2. Extract and parse ~76K books
    3. Load JSON data into gutenberg_books table
    4. Clean up temp files

    Returns:
        str: "S" (success), "F" (failed), "P" (processing/skip)
    """
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print("LOAD_GUTENBERG_METADATA", "STILL_PROCESSING", "Step still processing from previous run")
        return "P"

    # Update to processing when starting
    add_gutenberg_event('LOAD_GUTENBERG_METADATA', 'processing')
    log_and_print("LOAD_GUTENBERG_METADATA", "PROCESSING", "Weekly metadata load started")

    try:
        # Force reload to get enhanced bulk downloader with all metadata fields
        import importlib
        import gutenberg_bulk_downloader
        importlib.reload(gutenberg_bulk_downloader)

        log_and_print("LOAD_GUTENBERG_METADATA", "DOWNLOADING", "Starting Project Gutenberg catalog download with enhanced metadata extraction")

        success = gutenberg_bulk_downloader.run_bulk_download_as_function(
            output_dir="temp_gutenberg_weekly",
            cleanup=True
        )

        if not success:
            log_and_print("LOAD_GUTENBERG_METADATA", "ERROR", "Bulk download failed")
            return "F"

        log_and_print("LOAD_GUTENBERG_METADATA", "LOADING", "Download complete - loading data into database")

        # Load the catalog into database
        catalog_file = "temp_gutenberg_weekly/gutenberg_complete_catalog.json"
        if load_catalog_to_database(catalog_file):
            log_and_print("LOAD_GUTENBERG_METADATA", "SUCCESS", "Successfully loaded catalog into database")

            # Copy enhanced catalog to gutenberg_agent directory for inspection
            try:
                import shutil
                shutil.copy(catalog_file, "gutenberg_agent/gutenberg_complete_catalog.json")
                log_and_print("LOAD_GUTENBERG_METADATA", "SAVED", "Enhanced catalog saved to gutenberg_agent/ directory")
            except Exception as copy_error:
                log_and_print("LOAD_GUTENBERG_METADATA", "WARNING", f"Failed to copy catalog: {copy_error}")

            # Clean up temp directory
            try:
                import shutil
                shutil.rmtree("temp_gutenberg_weekly")
                log_and_print("LOAD_GUTENBERG_METADATA", "CLEANUP", "Temporary files cleaned up")
            except Exception as cleanup_error:
                log_and_print("LOAD_GUTENBERG_METADATA", "WARNING", f"Cleanup failed: {cleanup_error}")

            return "S"
        else:
            log_and_print("LOAD_GUTENBERG_METADATA", "ERROR", "Failed to load catalog into database")
            return "F"

    except Exception as e:
        log_and_print("LOAD_GUTENBERG_METADATA", "ERROR", f"Exception: {str(e)}")
        return "F"


def run_gutenberg_automation():
    """
    Callable function to run gutenberg automation logic (for master_cli.py).

    Returns:
        bool: True if completed successfully, False if failed
    """
    try:
        # Check current week status first
        from gutenberg_helper import get_week_start
        week_start = get_week_start(datetime.now())
        latest_event = get_latest_step_event('LOAD_GUTENBERG_METADATA')

        # Check if already completed this week
        week_completed = (latest_event and
                        datetime.fromisoformat(latest_event['timestamp']) >= week_start and
                        latest_event['status'] == 'success')

        if week_completed:
            log_and_print("SYSTEM", "SKIPPING", "Metadata load already completed this week - no action needed")
        else:
            # Check if it's Saturday
            pacific = pytz.timezone('US/Pacific')
            now_pacific = datetime.now(pacific)

            if now_pacific.weekday() == 5:  # Saturday = 5
                log_and_print("LOAD_GUTENBERG_METADATA", "CHECKING", "Saturday detected - checking status")

                current_status = latest_event['status'] if latest_event else None
                log_and_print("LOAD_GUTENBERG_METADATA", "STATUS", f"Current status: {current_status or 'NEW'}")

                # Execute metadata load if not completed
                if current_status not in ['success']:
                    result = execute_load_gutenberg_metadata(current_status)

                    # Update status based on result
                    if result == "S":
                        add_gutenberg_event('LOAD_GUTENBERG_METADATA', 'success')
                        log_and_print("LOAD_GUTENBERG_METADATA", "SUCCESS", "Weekly metadata load completed")
                    elif result == "F":
                        add_gutenberg_event('LOAD_GUTENBERG_METADATA', 'failed')
                        log_and_print("LOAD_GUTENBERG_METADATA", "FAILED", "Weekly metadata load failed")
                    elif result == "P":
                        pass  # Already processing - just continue
            else:
                # Not Saturday - just wait quietly
                log_and_print("SYSTEM", "WAITING", f"Not Saturday (current: {now_pacific.strftime('%A')}) - waiting")

        # Step 2: Process books from CSV (download + add to audiobook table)
        latest_process_event = get_latest_step_event('PROCESS_BOOKS_FROM_CSV')
        process_status = latest_process_event['status'] if latest_process_event else None

        if process_status not in ['success']:  # Retry failed steps like audiobook CLI
            log_and_print("PROCESS_BOOKS_FROM_CSV", "CHECKING", "Checking CSV for books to process")
            result = process_books_from_csv()

            if result == "SUCCESS":
                add_gutenberg_event('PROCESS_BOOKS_FROM_CSV', 'success')
                log_and_print("PROCESS_BOOKS_FROM_CSV", "SUCCESS", "Processed books from CSV - downloaded and added to audiobook queue")
            elif result == "FAILED":
                add_gutenberg_event('PROCESS_BOOKS_FROM_CSV', 'failed')
                log_and_print("PROCESS_BOOKS_FROM_CSV", "FAILED", "Failed to process books from CSV - will retry next run")
            else:  # result == "SKIP"
                log_and_print("PROCESS_BOOKS_FROM_CSV", "SKIPPED", "No books in CSV to process")
        else:
            log_and_print("PROCESS_BOOKS_FROM_CSV", "COMPLETED", "Book processing already completed successfully")

        # TODO: Add other steps here in the future

        return True

    except Exception as e:
        log_and_print("SYSTEM", "ERROR", f"Gutenberg automation failed: {str(e)}")
        return False


def main():
    """
    Main entry point - continuous 5-minute loop with Saturday metadata loading.
    """
    print("GUTENBERG CLI CONTINUOUS AUTOMATION")
    print(f"Running every {LOOP_INTERVAL_MINUTES} minutes")
    print(f"Working directory: {os.getcwd()}")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    run_count = 0
    try:
        while True:
            run_count += 1
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[Gutenberg Run #{run_count}] {timestamp}")
            print("#" * 60)

            try:
                # Use the complete automation function that has all 3 steps
                success = run_gutenberg_automation()

                if success:
                    print(f"SUCCESS: Gutenberg Run #{run_count} completed successfully")
                    logger.info(f"GUTENBERG|AUTOMATION|RUN_{run_count}|SUCCESS|Automation cycle completed")
                else:
                    print(f"ERROR: Gutenberg Run #{run_count} failed")
                    logger.error(f"GUTENBERG|AUTOMATION|RUN_{run_count}|ERROR|Automation cycle failed")

            except KeyboardInterrupt:
                raise  # Re-raise to break out of loop
            except Exception as e:
                print(f"ERROR: Gutenberg Run #{run_count} failed: {str(e)}")
                logger.error(f"GUTENBERG|AUTOMATION|RUN_{run_count}|ERROR|Automation cycle failed: {str(e)}")

            print(f"Waiting {LOOP_INTERVAL_MINUTES} minutes until next run...")
            logger.info(f"GUTENBERG|AUTOMATION|RUN_{run_count}|WAITING|Next run in {LOOP_INTERVAL_MINUTES} minutes")
            print("#" * 60)

            # Sleep for specified interval
            time.sleep(LOOP_INTERVAL_MINUTES * 60)

    except KeyboardInterrupt:
        print(f"\nGutenberg automation stopped by user after {run_count} runs")
        logger.info(f"GUTENBERG|AUTOMATION|STOPPED|User stopped automation after {run_count} runs")
        print("Goodbye!")


if __name__ == "__main__":
    main()