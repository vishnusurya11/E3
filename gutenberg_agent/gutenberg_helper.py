#!/usr/bin/env python3
"""
Gutenberg Helper Functions

Helper functions for managing gutenberg_process_events and gutenberg_books tables.
Provides event tracking and database operations for the Gutenberg CLI.
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def get_database_path() -> str:
    """Get path to the alpha database."""
    return "database/alpha_e3_agent.db"


def add_gutenberg_event(step_name: str, status: str) -> bool:
    """
    Add a new event to gutenberg_process_events table.

    Args:
        step_name: Name of the step (e.g., 'LOAD_GUTENBERG_METADATA')
        status: Status ('pending', 'processing', 'failed', 'success')

    Returns:
        bool: True if event added successfully
    """
    try:
        db_path = get_database_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            current_time = datetime.now().isoformat()

            cursor.execute("""
                INSERT INTO gutenberg_process_events (timestamp, step_name, status)
                VALUES (?, ?, ?)
            """, (current_time, step_name, status))

            conn.commit()
            print(f"   📝 Added event: {step_name} → {status}")
            return True

    except Exception as e:
        print(f"   ❌ Failed to add event: {e}")
        return False


def get_latest_step_event(step_name: str, since: Optional[datetime] = None) -> Optional[Dict]:
    """
    Get the latest event for a specific step.

    Args:
        step_name: Name of the step to check
        since: Optional datetime to filter events after this time

    Returns:
        Dict with event data or None if not found
    """
    try:
        db_path = get_database_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if since:
                cursor.execute("""
                    SELECT timestamp, step_name, status
                    FROM gutenberg_process_events
                    WHERE step_name = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (step_name, since.isoformat()))
            else:
                cursor.execute("""
                    SELECT timestamp, step_name, status
                    FROM gutenberg_process_events
                    WHERE step_name = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (step_name,))

            row = cursor.fetchone()
            return dict(row) if row else None

    except Exception as e:
        print(f"   ❌ Error getting latest event: {e}")
        return None


def get_week_start(current_time: datetime) -> datetime:
    """
    Get the start of the current week (Monday).

    Args:
        current_time: Current datetime

    Returns:
        datetime: Start of the week (Monday 00:00:00)
    """
    days_since_monday = current_time.weekday()
    week_start = current_time - timedelta(days=days_since_monday)
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def should_run_metadata_load() -> bool:
    """
    Check if metadata load should run this week.

    Rules:
    - Must be Sunday after 5 PM PST/PDT
    - Must not have run successfully this week already
    - Must not be currently processing

    Returns:
        bool: True if should run, False otherwise
    """
    try:
        import pytz

        # Get current Pacific time
        pacific = pytz.timezone('US/Pacific')
        now_pacific = datetime.now(pacific)

        print(f"   🕐 Current Pacific time: {now_pacific.strftime('%A %Y-%m-%d %H:%M:%S %Z')}")

        # Must be Sunday (6) and after 5 PM (17)
        if now_pacific.weekday() != 6:
            print(f"   📅 Not Sunday (current: {now_pacific.strftime('%A')}) - skipping metadata load")
            return False

        if now_pacific.hour < 17:
            print(f"   🕐 Before 5 PM PST (current: {now_pacific.hour}:00) - skipping metadata load")
            return False

        print(f"   ✅ Sunday after 5 PM PST - checking if already run this week...")

        # Get start of this week
        week_start = get_week_start(now_pacific.replace(tzinfo=None))
        print(f"   📅 Week started: {week_start}")

        # Check if already run successfully this week
        latest_event = get_latest_step_event('LOAD_GUTENBERG_METADATA', since=week_start)

        if latest_event:
            print(f"   📝 Found event this week: {latest_event['status']} at {latest_event['timestamp']}")

            if latest_event['status'] == 'success':
                print(f"   ✅ Already completed this week - skipping")
                return False

            if latest_event['status'] == 'processing':
                print(f"   🔄 Currently processing - skipping")
                return False
        else:
            print(f"   📝 No events found this week")

        print(f"   🚀 Ready to run metadata load!")
        return True

    except Exception as e:
        print(f"   ❌ Error checking schedule: {e}")
        return False


def load_catalog_to_database(catalog_file: str) -> bool:
    """
    Load Project Gutenberg catalog JSON file into gutenberg_books table.

    Args:
        catalog_file: Path to the JSON catalog file

    Returns:
        bool: True if loaded successfully
    """
    try:
        print(f"   📚 Loading catalog from: {catalog_file}")

        # Read JSON file
        with open(catalog_file, 'r', encoding='utf-8') as f:
            books = json.load(f)

        print(f"   📊 Found {len(books)} books in catalog")

        # Load into database
        db_path = get_database_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Drop and recreate table to get latest schema with all generated columns
            cursor.execute("DROP TABLE IF EXISTS gutenberg_books")
            print(f"   🗑️ Dropped existing gutenberg_books table")

            # Recreate table with latest schema including all new generated columns
            cursor.execute("""
                CREATE TABLE gutenberg_books (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    raw_metadata JSON,

                    -- Generated columns for fast queries (including new fields)
                    download_count INTEGER GENERATED ALWAYS AS (json_extract(raw_metadata, '$.download_count')) STORED,
                    primary_author TEXT GENERATED ALWAYS AS (json_extract(raw_metadata, '$.authors[0].name')) STORED,
                    language TEXT GENERATED ALWAYS AS (json_extract(raw_metadata, '$.languages[0]')) STORED,
                    publication_year INTEGER GENERATED ALWAYS AS (json_extract(raw_metadata, '$.publication_year')) STORED,
                    issued_date TEXT GENERATED ALWAYS AS (json_extract(raw_metadata, '$.issued_date')) STORED,

                    -- Timestamps
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data_version TEXT DEFAULT 'v1'
                )
            """)

            # Create indexes for performance
            cursor.execute("CREATE INDEX idx_gutenberg_author ON gutenberg_books(primary_author)")
            cursor.execute("CREATE INDEX idx_gutenberg_language ON gutenberg_books(language)")
            cursor.execute("CREATE INDEX idx_gutenberg_downloads ON gutenberg_books(download_count DESC)")
            cursor.execute("CREATE INDEX idx_gutenberg_publication_year ON gutenberg_books(publication_year)")
            cursor.execute("CREATE INDEX idx_gutenberg_title ON gutenberg_books(title)")

            print(f"   ✅ Recreated gutenberg_books table with latest schema")

            # Insert all books
            inserted_count = 0
            for book in books:
                try:
                    cursor.execute("""
                        INSERT INTO gutenberg_books (id, title, raw_metadata)
                        VALUES (?, ?, ?)
                    """, (book['id'], book['title'], json.dumps(book)))

                    inserted_count += 1

                    if inserted_count % 5000 == 0:
                        print(f"   📈 Inserted {inserted_count:,} books...")

                except Exception as insert_error:
                    print(f"   ⚠️ Failed to insert book {book.get('id', 'unknown')}: {insert_error}")
                    continue

            conn.commit()
            print(f"   ✅ Successfully loaded {inserted_count:,} books into database")
            return True

    except Exception as e:
        print(f"   ❌ Error loading catalog: {e}")
        return False


def read_csv_book_ids(csv_file: str) -> List[int]:
    """
    Read book IDs from CSV file.

    Args:
        csv_file: Path to CSV file containing book IDs

    Returns:
        List[int]: List of book IDs, empty list if file doesn't exist or is empty
    """
    import csv
    import os

    if not os.path.exists(csv_file):
        print(f"   📄 CSV file not found: {csv_file}")
        return []

    book_ids = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row_num, row in enumerate(reader, 1):
                if row and len(row) > 0:
                    # Parse all cells in row, handle comma-separated IDs
                    for cell in row:
                        if cell.strip().startswith('#'):  # Skip comment rows
                            continue

                        # Split cell by comma in case multiple IDs in one cell
                        for book_id_str in cell.split(','):
                            book_id_str = book_id_str.strip()
                            if book_id_str.isdigit():
                                book_id = int(book_id_str)
                                if book_id not in book_ids:  # Avoid duplicates
                                    book_ids.append(book_id)
                            elif book_id_str and not book_id_str.startswith('#'):
                                print(f"   ⚠️ Invalid book ID on row {row_num}: '{book_id_str}'")

        print(f"   📋 Found {len(book_ids)} book IDs in CSV")
        return book_ids

    except Exception as e:
        print(f"   ❌ Error reading CSV file: {e}")
        return []


def download_books_from_csv() -> str:
    """
    Download books from CSV file to foundry structure.

    Reads gutenberg_agent/books_to_download.csv and downloads each book
    to foundry/pg{book_id}/pg{book_id}-images.html format.

    Returns:
        str: "SUCCESS" if books downloaded, "SKIP" if no books or empty CSV
    """
    csv_file = "gutenberg_agent/books_to_download.csv"

    # Read book IDs from CSV
    book_ids = read_csv_book_ids(csv_file)

    if not book_ids:
        print(f"   📄 No books to download (CSV empty or missing)")
        return "SKIP"  # Don't add any events - just skip quietly

    # Add processing status when starting downloads
    add_gutenberg_event('DOWNLOAD_BOOKS', 'processing')
    print(f"   📝 Added event: DOWNLOAD_BOOKS → processing")

    print(f"   📚 Starting download of {len(book_ids)} books from CSV")

    # Import the download function
    from gutenberg_downloader import download_book_to_foundry

    downloaded_count = 0
    failed_count = 0

    for book_id in book_ids:
        print(f"   📖 Downloading pg{book_id}...")

        try:
            success = download_book_to_foundry(book_id)
            if success:
                downloaded_count += 1
                print(f"   ✅ pg{book_id} downloaded successfully")
            else:
                failed_count += 1
                print(f"   ❌ pg{book_id} download failed")
        except Exception as e:
            failed_count += 1
            print(f"   ❌ pg{book_id} download error: {e}")

    print(f"   📊 Download summary: {downloaded_count} success, {failed_count} failed")

    # Don't clear CSV here - let ADD_BOOKS_TO_AUDIOBOOK_QUEUE handle it
    if downloaded_count > 0:
        return "SUCCESS"
    else:
        return "FAILED"


def get_book_metadata_from_gutenberg(book_id: int) -> Optional[Dict]:
    """
    Get book metadata from gutenberg_books table.

    Args:
        book_id: Project Gutenberg book ID

    Returns:
        Dict with book metadata or None if not found
    """
    try:
        db_path = get_database_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, title, primary_author, language, publication_year,
                       json_extract(raw_metadata, '$.subjects') as subjects
                FROM gutenberg_books
                WHERE id = ?
            """, (book_id,))

            row = cursor.fetchone()
            if row:
                return dict(row)
            else:
                print(f"   ❌ Book ID {book_id} not found in gutenberg_books table")
                return None

    except Exception as e:
        print(f"   ❌ Error getting book metadata: {e}")
        return None


def insert_book_to_audiobook_table(timestamp_id: str, book_id: str, metadata: Dict) -> bool:
    """
    Insert book into audiobook books table.

    Args:
        timestamp_id: Unique ID in YYYYMMDDHHMMSS format
        book_id: Book ID with 'pg' prefix (e.g., 'pg1342')
        metadata: Book metadata from gutenberg_books

    Returns:
        bool: True if inserted successfully
    """
    try:
        db_path = get_database_path()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Extract genre from subjects (take first subject as genre)
            subjects_json = metadata.get('subjects', '[]')
            subjects = json.loads(subjects_json) if isinstance(subjects_json, str) else subjects_json
            genre = subjects[0] if subjects and len(subjects) > 0 else "General"

            # Clean genre (remove catalog codes like "PR", "E201")
            if genre and len(genre) <= 10 and genre.isupper():
                genre = subjects[1] if len(subjects) > 1 else "Literature"

            cursor.execute("""
                INSERT INTO books (
                    id, book_id, book_name, author, language, year_published, genre, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp_id,
                book_id,
                metadata.get('title', 'Unknown Title'),
                metadata.get('primary_author', 'Unknown Author'),
                metadata.get('language', 'eng'),
                metadata.get('publication_year'),
                genre[:100],  # Limit genre length
                ""  # Empty summary for now
            ))

            conn.commit()
            print(f"   ✅ Added {book_id} to audiobook books table")
            return True

    except Exception as e:
        print(f"   ❌ Error inserting {book_id}: {e}")
        return False


def clear_csv_file(csv_file: str) -> bool:
    """
    Clear the CSV file after successful processing.

    Args:
        csv_file: Path to CSV file to clear

    Returns:
        bool: True if cleared successfully
    """
    try:
        with open(csv_file, 'w', encoding='utf-8') as f:
            f.write("")  # Clear file content
        print(f"   🗑️ Cleared CSV file: {csv_file}")
        return True
    except Exception as e:
        print(f"   ❌ Error clearing CSV: {e}")
        return False


def add_books_to_audiobook_queue() -> str:
    """
    Add books from CSV to audiobook books table.

    Process:
    1. Read book IDs from books_to_download.csv
    2. Get metadata from gutenberg_books table
    3. Insert into books table with unique timestamp IDs
    4. Clear CSV after success

    Returns:
        str: "SUCCESS", "FAILED", or "SKIP"
    """
    csv_file = "gutenberg_agent/books_to_download.csv"

    # Read book IDs from CSV
    book_ids = read_csv_book_ids(csv_file)

    if not book_ids:
        print(f"   📄 No books to add (CSV empty or missing)")
        return "SKIP"

    # Add processing status
    add_gutenberg_event('ADD_BOOKS_TO_AUDIOBOOK_QUEUE', 'processing')
    print(f"   📝 Added event: ADD_BOOKS_TO_AUDIOBOOK_QUEUE → processing")

    print(f"   📚 Adding {len(book_ids)} books to audiobook queue")

    added_count = 0
    failed_count = 0

    for book_id in book_ids:
        print(f"   📖 Processing pg{book_id}...")

        # Get metadata from gutenberg_books table
        metadata = get_book_metadata_from_gutenberg(book_id)

        if metadata:
            # Generate unique timestamp ID
            timestamp_id = datetime.now().strftime('%Y%m%d%H%M%S')

            # Insert into audiobook books table
            if insert_book_to_audiobook_table(timestamp_id, f"pg{book_id}", metadata):
                added_count += 1
                print(f"   ✅ pg{book_id} added to audiobook queue")
            else:
                failed_count += 1

            # Sleep 1 second to ensure unique timestamp IDs
            time.sleep(1)
        else:
            failed_count += 1
            print(f"   ❌ pg{book_id} metadata not found")

    print(f"   📊 Add summary: {added_count} success, {failed_count} failed")

    if added_count > 0:
        # Clear CSV after successful additions
        clear_csv_file(csv_file)
        return "SUCCESS"
    else:
        return "FAILED"


def process_books_from_csv() -> str:
    """
    Complete book processing from CSV: download + add to audiobook table.

    Process:
    1. Read book IDs from CSV
    2. Download books to foundry (skip if already exists)
    3. Add books to audiobook table with unique timestamp IDs
    4. Clear CSV after success

    Returns:
        str: "SUCCESS", "FAILED", or "SKIP"
    """
    import os
    csv_file = "gutenberg_agent/books_to_download.csv"

    # Read book IDs from CSV
    book_ids = read_csv_book_ids(csv_file)

    if not book_ids:
        print(f"   📄 No books to process (CSV empty or missing)")
        return "SKIP"

    # Add processing status
    add_gutenberg_event('PROCESS_BOOKS_FROM_CSV', 'processing')
    print(f"   📝 Added event: PROCESS_BOOKS_FROM_CSV → processing")

    print(f"   📚 Processing {len(book_ids)} books from CSV")

    # Import download function
    from gutenberg_downloader import download_book_to_foundry

    downloaded_count = 0
    added_count = 0
    failed_count = 0

    for book_id in book_ids:
        print(f"   📖 Processing pg{book_id}...")

        # Step A: Download book if not already in foundry
        foundry_path = f"foundry/pg{book_id}/pg{book_id}-images.html"
        needs_download = not os.path.exists(foundry_path)

        if needs_download:
            print(f"   ⬇️ Downloading pg{book_id} to foundry...")
            try:
                if download_book_to_foundry(book_id):
                    downloaded_count += 1
                    print(f"   ✅ pg{book_id} downloaded successfully")
                else:
                    failed_count += 1
                    print(f"   ❌ pg{book_id} download failed - skipping add to table")
                    continue  # Skip adding to table if download failed
            except Exception as e:
                failed_count += 1
                print(f"   ❌ pg{book_id} download error: {e} - skipping")
                continue
        else:
            print(f"   📁 pg{book_id} already exists in foundry")

        # Step B: Add to audiobook table (only if download successful or already exists)
        print(f"   ➕ Adding pg{book_id} to audiobook table...")
        metadata = get_book_metadata_from_gutenberg(book_id)

        if metadata:
            # Generate unique timestamp ID
            timestamp_id = datetime.now().strftime('%Y%m%d%H%M%S')

            if insert_book_to_audiobook_table(timestamp_id, f"pg{book_id}", metadata):
                added_count += 1
                print(f"   ✅ pg{book_id} added to audiobook queue")
            else:
                failed_count += 1
                print(f"   ❌ pg{book_id} failed to add to audiobook table")

            # Sleep 1 second for unique timestamp IDs
            time.sleep(1)
        else:
            failed_count += 1
            print(f"   ❌ pg{book_id} metadata not found")

    print(f"   📊 Processing summary: {downloaded_count} downloaded, {added_count} added to queue, {failed_count} failed")

    if added_count > 0:
        # Clear CSV after successful processing
        clear_csv_file(csv_file)
        return "SUCCESS"
    else:
        return "FAILED"