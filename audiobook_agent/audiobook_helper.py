#!/usr/bin/env python3
"""
Audiobook Database Helper Functions

Simple helper functions for working with the audiobook pipeline database.
All functions work with dictionaries for easy data manipulation.
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional


################################################################################
# DATABASE CONNECTION
################################################################################

AUDIOBOOK_DB_PATH = "database/audiobook.db"

def get_db_connection():
    """Get connection to audiobook database."""
    return sqlite3.connect(AUDIOBOOK_DB_PATH)


################################################################################
# GET DATA FUNCTIONS
################################################################################

def get_all_books() -> List[Dict]:
    """Get all books from database as list of dicts."""
    print("Getting all books from audiobook database...")
    
    try:
        db_path = get_normalized_db_path()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Use new normalized schema with simple query for compatibility
            cursor.execute("""
                SELECT b.id, b.book_id, b.book_name as book_title, b.author,
                       n.narrator_name as narrated_by,
                       ap.status, ap.created_at, ap.updated_at
                FROM books b
                LEFT JOIN audiobook_productions ap ON b.book_id = ap.book_id
                LEFT JOIN narrators n ON ap.narrator_id = n.narrator_id
                ORDER BY b.id
            """)
            
            books = [dict(row) for row in cursor.fetchall()]
            
            print(f"Found {len(books)} books in database")
            return books
            
    except Exception as e:
        print(f"ERROR: Failed to get books: {e}")
        return []


def get_processable_books() -> List[Dict]:
    """Get books that can be processed (pending or failed within retry limit)."""
    all_books = get_all_books()
    processable = [book for book in all_books 
                  if book['parse_novel_status'] in ['pending', 'failed'] 
                  and book.get('retry_count', 0) < book.get('max_retries', 3)]
    
    print(f"Found {len(processable)} processable books (pending + retryable failed)")
    return processable


################################################################################
# UPDATE DATA FUNCTIONS
################################################################################

def update_book_record(book_dict: Dict) -> bool:
    """Update database record from dict - syncs all fields back to database."""
    book_id = book_dict.get('book_id')
    if not book_id:
        print("ERROR: No book_id in dict")
        return False
    
    print(f"Updating database record for book_id: {book_id}")
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Update with current timestamp
            book_dict['updated_at'] = datetime.now().isoformat()
            
            # Update all fields (except id which is auto-increment)
            cursor.execute("""
                UPDATE audiobook_processing SET
                    book_title = ?,
                    author = ?,
                    narrated_by = ?,
                    input_file = ?,
                    narrator_audio = ?,
                    parse_novel_status = ?,
                    metadata_status = ?,
                    audio_generation_status = ?,
                    audio_files_moved_status = ?,
                    audio_combination_planned_status = ?,
                    subtitle_generation_status = ?,
                    audio_combination_status = ?,
                    video_generation_status = ?,
                    parse_novel_completed_at = ?,
                    metadata_completed_at = ?,
                    audio_generation_completed_at = ?,
                    audio_files_moved_completed_at = ?,
                    audio_combination_planned_completed_at = ?,
                    subtitle_generation_completed_at = ?,
                    audio_combination_completed_at = ?,
                    video_generation_completed_at = ?,
                    image_prompts_status = ?,
                    image_prompts_started_at = ?,
                    image_prompts_completed_at = ?,
                    image_jobs_generation_status = ?,
                    image_jobs_generation_completed_at = ?,
                    image_jobs_completed = ?,
                    total_image_jobs = ?,
                    image_generation_status = ?,
                    image_generation_completed_at = ?,
                    video_generation_started_at = ?,
                    total_videos_created = ?,
                    updated_at = ?,
                    metadata = ?,
                    total_chapters = ?,
                    total_chunks = ?,
                    total_words = ?,
                    total_audio_files = ?,
                    audio_jobs_completed = ?,
                    audio_duration_seconds = ?,
                    audio_file_size_bytes = ?,
                    retry_count = ?,
                    max_retries = ?
                WHERE book_id = ?
            """, (
                book_dict.get('book_title'),
                book_dict.get('author'),
                book_dict.get('narrated_by'),
                book_dict.get('input_file'),
                book_dict.get('narrator_audio'),
                book_dict.get('parse_novel_status'),
                book_dict.get('metadata_status'),
                book_dict.get('audio_generation_status'),
                book_dict.get('audio_files_moved_status'),
                book_dict.get('audio_combination_planned_status'),
                book_dict.get('subtitle_generation_status'),
                book_dict.get('audio_combination_status'),
                book_dict.get('video_generation_status'),
                book_dict.get('parse_novel_completed_at'),
                book_dict.get('metadata_completed_at'),
                book_dict.get('audio_generation_completed_at'),
                book_dict.get('audio_files_moved_completed_at'),
                book_dict.get('audio_combination_planned_completed_at'),
                book_dict.get('subtitle_generation_completed_at'),
                book_dict.get('audio_combination_completed_at'),
                book_dict.get('video_generation_completed_at'),
                book_dict.get('image_prompts_status'),
                book_dict.get('image_prompts_started_at'),
                book_dict.get('image_prompts_completed_at'),
                book_dict.get('image_jobs_generation_status'),
                book_dict.get('image_jobs_generation_completed_at'),
                book_dict.get('image_jobs_completed'),
                book_dict.get('total_image_jobs'),
                book_dict.get('image_generation_status'),
                book_dict.get('image_generation_completed_at'),
                book_dict.get('video_generation_started_at'),
                book_dict.get('total_videos_created'),
                book_dict.get('updated_at'),
                json.dumps(book_dict.get('metadata')) if book_dict.get('metadata') else None,
                book_dict.get('total_chapters'),
                book_dict.get('total_chunks'),
                book_dict.get('total_words'),
                book_dict.get('total_audio_files'),
                book_dict.get('audio_jobs_completed'),
                book_dict.get('audio_duration_seconds'),
                book_dict.get('audio_file_size_bytes'),
                book_dict.get('retry_count', 0),
                book_dict.get('max_retries', 3),
                book_id
            ))
            
            conn.commit()
            print(f"Database record updated successfully")
            return True
            
    except Exception as e:
        print(f"ERROR: Failed to update record: {e}")
        return False


################################################################################
# LOGGING FUNCTIONS
################################################################################

def log_simple(book_id: str, message: str, level: str = 'INFO', event_type: str = 'general',
               stage: str = None, status: str = None, details: Dict = None) -> bool:
    """Simple logging to audiobook_logs table."""
    print(f"[{level}] {message}")
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audiobook_logs 
                (book_id, event_type, message, level, timestamp, details, stage, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                book_id, 
                event_type, 
                message, 
                level, 
                datetime.now().isoformat(),
                json.dumps(details) if details else None,
                stage,
                status
            ))
            conn.commit()
            return True
            
    except Exception as e:
        print(f"ERROR: Failed to log: {e}")
        return False


################################################################################
# UTILITY FUNCTIONS
################################################################################

def print_book_summary(book_dict: Dict):
    """Print a nice summary of a book record."""
    print(f"Book: {book_dict['book_title']}")
    print(f"  ID: {book_dict['book_id']}")
    print(f"  Author: {book_dict['author']}")
    print(f"  Parse Status: {book_dict['parse_novel_status']}")
    print(f"  Audio Status: {book_dict['audio_generation_status']}")
    print(f"  Updated: {book_dict['updated_at']}")


def mark_stage_completed(book_dict: Dict, stage: str) -> Dict:
    """Helper to mark a stage as completed in the dict."""
    book_dict[f'{stage}_status'] = 'completed'
    book_dict[f'{stage}_completed_at'] = datetime.now().isoformat()
    return book_dict


def mark_stage_failed(book_dict: Dict, stage: str) -> Dict:
    """Helper to mark a stage as failed in the dict with retry logic."""
    current_retries = book_dict.get('retry_count', 0)
    max_retries = book_dict.get('max_retries', 3)
    
    # Increment retry count
    book_dict['retry_count'] = current_retries + 1
    
    # Check if we've hit retry limit
    if book_dict['retry_count'] >= max_retries:
        book_dict[f'{stage}_status'] = 'failed_permanently'
        print(f"Book {book_dict['book_id']} failed permanently after {max_retries} retries")
    else:
        book_dict[f'{stage}_status'] = 'failed'
        print(f"Book {book_dict['book_id']} failed (retry {book_dict['retry_count']}/{max_retries})")
    
    return book_dict


################################################################################
# NEW NORMALIZED SCHEMA FUNCTIONS
################################################################################

def get_normalized_db_path():
    """Get database path using new config system."""
    import sys
    import os
    sys.path.append('..')
    from comfyui_agent.utils.config_loader import load_global_config
    config = load_global_config()
    return config['paths']['database']


def find_book_input_file(book_id: str) -> str:
    """
    Find HTML input file for book using book-centric structure.
    
    Looks for HTML files containing book_id in the filename within
    the book's dedicated folder (foundry/{book_id}/).
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        
    Returns:
        Path to the input HTML file
        
    Raises:
        FileNotFoundError: If no matching HTML file found
        
    Examples:
        >>> find_book_input_file('pg74')  
        'foundry/pg74/some_prefix_pg74_suffix.html'
    """
    import glob
    import os
    book_dir = f"foundry/{book_id}/"
    
    # Look for HTML files containing book_id in filename
    pattern = os.path.join(book_dir, f"*{book_id}*.html")
    matching_files = glob.glob(pattern)
    
    if matching_files:
        return matching_files[0]  # Return first match
        
    raise FileNotFoundError(f"No HTML file containing '{book_id}' found in {book_dir}")


def get_titles_status():
    """
    ################################################################################
    # STEP 0: SHOW INCOMPLETE AUDIOBOOKS READY FOR PROCESSING
    # 
    # Purpose: Display books that need audiobook processing (audiobook_complete = false)
    #          Shows processing queue ordered by insertion priority
    # Input:   None (reads from titles table)
    # Output:  Console display of incomplete audiobooks ready for processing
    # 
    # Uses normalized schema:
    #   - titles.id (auto-increment primary key - processing priority)
    #   - titles.book_id (business identifier like 'pg74')
    #   - titles.audiobook_complete (false = needs processing)
    ################################################################################
    """
    print("🔍 Step 0: Setting up processing queue from incomplete titles...")
    
    try:
        db_path = get_normalized_db_path()
        
        print(f"\n📚 PROCESSING QUEUE SETUP")
        print(f"Database: {db_path}")
        print("=" * 80)
        
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Read only incomplete audiobooks (processing candidates)
            cursor.execute("""
                SELECT id, book_id, title, author, audiobook_complete, audiobook_narrator_id
                FROM titles 
                WHERE audiobook_complete = false
                ORDER BY id
            """)
            
            incomplete_titles = cursor.fetchall()
            
            if not incomplete_titles:
                print("🎉 No incomplete audiobooks found - All audiobooks completed!")
                # Check total count for context
                cursor.execute("SELECT COUNT(*) as total FROM titles")
                total_count = cursor.fetchone()['total']
                print(f"📊 Total titles in database: {total_count}")
                return
            
            print(f"📖 Found {len(incomplete_titles)} incomplete audiobooks:")
            print()
            
            # Ensure production records exist for each incomplete title
            records_created = 0
            for title in incomplete_titles:
                # Check if production record exists for this book_id
                cursor.execute("""
                    SELECT id FROM audiobook_production 
                    WHERE book_id = ?
                """, (title['book_id'],))
                
                existing = cursor.fetchone()
                
                if not existing and title['audiobook_narrator_id']:
                    # Create new production record using book_id
                    cursor.execute("""
                        INSERT INTO audiobook_production (
                            book_id, narrator_id, status, created_at, updated_at
                        ) VALUES (?, ?, 'pending', datetime('now'), datetime('now'))
                    """, (title['book_id'], title['audiobook_narrator_id']))
                    
                    records_created += 1
                    creation_status = "✅ CREATED"
                elif existing:
                    creation_status = "📋 EXISTS"
                else:
                    creation_status = "❌ NO NARRATOR"
                
                # Display title info
                narrator_display = title['audiobook_narrator_id'] or '[Not Assigned]'
                print(f"ID {title['id']:2d} | {title['book_id']:10s} | {creation_status} | {title['title']}")
                print(f"      Author: {title['author'] or 'Unknown'}")
                print(f"      Narrator: {narrator_display}")
                print()
            
            # Commit any new records
            conn.commit()
            
            print("=" * 80)
            if records_created > 0:
                print(f"📝 Created {records_created} new production records")
            print(f"📊 Processing Queue: {len(incomplete_titles)} audiobooks ready")
            print(f"✅ Step 0: Processing queue setup completed")
            
    except Exception as e:
        print(f"❌ Step 0 FAILED: Error reading titles: {e}")
        import traceback
        traceback.print_exc()
        raise


def get_processing_queue():
    """
    Get all audiobook productions that need processing.
    
    Returns list of dicts with joined book/narrator data for productions
    where status != 'success' (pending, processing, failed).
    
    Returns:
        List[Dict]: Audiobook production records with book and narrator details
    """
    try:
        db_path = get_normalized_db_path()
        
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all incomplete audiobook productions (from AUDIOBOOK_CLI_PLAN.md)
            cursor.execute("""
                SELECT ap.audiobook_id, ap.book_id, ap.narrator_id, ap.status, 
                       b.book_name, b.author, n.narrator_name, n.sample_filepath
                FROM audiobook_productions ap
                JOIN books b ON ap.book_id = b.book_id
                JOIN narrators n ON ap.narrator_id = n.narrator_id  
                WHERE ap.status != 'success'
                ORDER BY ap.audiobook_id
            """)
            
            records = cursor.fetchall()
            return [dict(record) for record in records]
            
    except Exception as e:
        print(f"❌ Error getting processing queue: {e}")
        return []


def get_audiobook_events(audiobook_id: str):
    """
    Get all process events for a specific audiobook.
    
    Returns list of events ordered by timestamp to see step progression.
    
    Args:
        audiobook_id: The audiobook ID (YYYYMMDDHHMMSS format)
        
    Returns:
        List[Dict]: Event records with step_number, status, timestamp
    """
    try:
        db_path = get_normalized_db_path()
        
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT audiobook_id, timestamp, step_number, status
                FROM audiobook_process_events  
                WHERE audiobook_id = ?
                ORDER BY timestamp
            """, (audiobook_id,))
            
            events = cursor.fetchall()
            return [dict(event) for event in events]
            
    except Exception as e:
        print(f"❌ Error getting events for {audiobook_id}: {e}")
        return []


def add_audiobook_event(audiobook_id: str, step_number: str, status: str) -> bool:
    """
    Add new event to audiobook_process_events table.
    
    Args:
        audiobook_id: The audiobook ID (YYYYMMDDHHMMSS format)
        step_number: Step identifier (STEP1_parsing, STEP2_audio, etc.)
        status: Event status (pending, processing, failed, success)
        
    Returns:
        bool: True if event added successfully
    """
    try:
        db_path = get_normalized_db_path()
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Use microsecond precision to prevent duplicate timestamps
            from datetime import datetime
            precise_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            
            cursor.execute("""
                INSERT INTO audiobook_process_events (
                    audiobook_id, timestamp, step_number, status
                ) VALUES (?, ?, ?, ?)
            """, (audiobook_id, precise_timestamp, step_number, status))
            
            conn.commit()
            print(f"📝 Added event: {audiobook_id} - {step_number} - {status}")
            return True
            
    except Exception as e:
        print(f"❌ Error adding event: {e}")
        return False


def get_comfyui_job_status_by_book_id(book_id: str) -> Dict:
    """
    Get ComfyUI job status counts for a specific book_id.
    
    Queries comfyui_jobs table for jobs where config_name contains the book_id
    and returns status counts as a dictionary.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        
    Returns:
        Dict: Status counts like {'done': 3, 'pending': 152, 'processing': 1}
    """
    try:
        db_path = get_normalized_db_path()
        
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Query job status counts for this book_id
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM comfyui_jobs 
                WHERE config_name LIKE ?
                GROUP BY status
            """, (f'%{book_id}%',))
            
            results = cursor.fetchall()
            
            # Convert to dict
            status_counts = {}
            for row in results:
                status_counts[row['status']] = row['count']
            
            print(f"📊 ComfyUI job status for {book_id}: {status_counts}")
            return status_counts
            
    except Exception as e:
        print(f"❌ Error getting ComfyUI job status for {book_id}: {e}")
        return {}


def move_comfyui_audio_files(book_id: str, language: str = 'eng') -> bool:
    """
    Move completed ComfyUI audio files from dev output to foundry speech directory.
    
    Moves files from D:/Projects/pheonix/dev/output/speech/alpha/{book_id}* 
    to foundry/{book_id}/speech/
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (default: 'eng')
        
    Returns:
        bool: True if files moved successfully
    """
    import glob
    import shutil
    import os
    
    # Source pattern - ComfyUI output directory
    source_pattern = f"D:/Projects/pheonix/dev/output/speech/alpha/{book_id}*"
    
    # Destination directory 
    dest_dir = f"foundry/{book_id}/{language}/speech"
    
    print(f"🔍 Looking for audio files: {source_pattern}")
    
    try:
        # Find source files
        source_files = glob.glob(source_pattern)
        
        if not source_files:
            print(f"❌ No audio files found matching: {source_pattern}")
            return False
        
        # Create destination directory
        os.makedirs(dest_dir, exist_ok=True)
        
        # Move each file
        moved_count = 0
        for source_file in source_files:
            filename = os.path.basename(source_file)
            dest_path = os.path.join(dest_dir, filename)
            
            print(f"📁 Moving: {source_file} -> {dest_path}")
            
            # Use copy2 to preserve metadata, then remove source
            shutil.copy2(source_file, dest_path)
            os.remove(source_file)
            moved_count += 1
        
        print(f"✅ Successfully moved {moved_count} audio files to {dest_dir}")
        return True
        
    except Exception as e:
        print(f"❌ Error moving audio files: {e}")
        return False


def add_book_metadata_to_first_chunk(book_id: str, language: str, book_name: str, author: str, narrator_name: str) -> bool:
    """
    Add book metadata prefix to first chunk of first chapter.
    
    Adds "Book Title by Author, narrated by Narrator," to beginning of first chunk.
    Updates char_count and saves modified JSON file.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng') 
        book_name: Full book title
        author: Author name
        narrator_name: Narrator name
        
    Returns:
        bool: True if metadata added successfully
    """
    import json
    import os
    
    # Find chapter_001.json in new folder structure
    chapter_file = f"foundry/{book_id}/{language}/chapters/chapter_001.json"
    
    print(f"🔍 Looking for first chapter: {chapter_file}")
    
    if not os.path.exists(chapter_file):
        print(f"❌ Chapter file not found: {chapter_file}")
        return False
    
    try:
        # Read chapter file
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
        
        # Find first chunk
        chunks = chapter_data['chapter']['chunks']
        if not chunks:
            print(f"❌ No chunks found in chapter file")
            return False
        
        first_chunk = chunks[0]
        original_text = first_chunk['text']
        
        # Create metadata prefix
        metadata_prefix = f"{book_name} by {author}, narrated by {narrator_name}, "
        new_text = metadata_prefix + original_text
        
        print(f"📝 Adding metadata prefix: '{metadata_prefix}'")
        
        # Update first chunk
        first_chunk['text'] = new_text
        first_chunk['char_count'] = len(new_text)
        
        # Save modified file
        with open(chapter_file, 'w', encoding='utf-8') as f:
            json.dump(chapter_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Added metadata prefix to first chunk ({len(metadata_prefix)} chars)")
        return True
        
    except Exception as e:
        print(f"❌ Failed to add metadata: {e}")
        return False