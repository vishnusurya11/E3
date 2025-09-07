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


def get_comfyui_audio_job_status(book_id: str) -> Dict:
    """
    Get ComfyUI audio job status counts for a specific book_id.
    
    Queries comfyui_jobs table for SPEECH jobs only.
    
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
            
            # Query audio job status counts for this book_id (SPEECH pattern)
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM comfyui_jobs 
                WHERE config_name LIKE ?
                GROUP BY status
            """, (f'SPEECH_{book_id}%',))
            
            results = cursor.fetchall()
            
            # Convert to dict
            status_counts = {}
            for row in results:
                status_counts[row['status']] = row['count']
            
            print(f"📊 ComfyUI audio job status for {book_id}: {status_counts}")
            return status_counts
            
    except Exception as e:
        print(f"❌ Error getting ComfyUI audio job status for {book_id}: {e}")
        return {}


def get_comfyui_image_job_status(book_id: str) -> Dict:
    """
    Get ComfyUI image job status counts for a specific book_id.
    
    Queries comfyui_jobs table for T2I (text-to-image) jobs only.
    
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
            
            # Query image job status counts for this book_id (T2I pattern)
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM comfyui_jobs 
                WHERE config_name LIKE ?
                GROUP BY status
            """, (f'T2I_{book_id}%',))
            
            results = cursor.fetchall()
            
            # Convert to dict
            status_counts = {}
            for row in results:
                status_counts[row['status']] = row['count']
            
            print(f"📊 ComfyUI image job status for {book_id}: {status_counts}")
            return status_counts
            
    except Exception as e:
        print(f"❌ Error getting ComfyUI image job status for {book_id}: {e}")
        return {}


# Keep original function for backward compatibility
def get_comfyui_job_status_by_book_id(book_id: str) -> Dict:
    """
    Get ComfyUI job status counts for a specific book_id (all job types).
    
    Legacy function - prefer using specific audio/image functions.
    """
    return get_comfyui_audio_job_status(book_id)


def move_comfyui_audio_files(book_id: str, language: str = 'eng') -> bool:
    """
    Move completed ComfyUI audio folder structure from dev output to foundry speech directory.
    
    Copies entire folder structure from D:/Projects/pheonix/dev/output/speech/alpha/{book_id}/
    to foundry/{book_id}/{language}/speech/ preserving ch001/chunk001/audio_*.flac structure
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (default: 'eng')
        
    Returns:
        bool: True if folder structure moved successfully
    """
    import shutil
    import os
    from pathlib import Path
    
    # Source directory - ComfyUI output with chapter/chunk structure
    source_dir = f"D:/Projects/pheonix/dev/output/speech/alpha/{book_id}"
    
    # Destination directory 
    dest_dir = f"foundry/{book_id}/{language}/speech"
    
    print(f"🔍 Looking for audio folder: {source_dir}")
    
    try:
        source_path = Path(source_dir)
        dest_path = Path(dest_dir)
        
        if not source_path.exists():
            print(f"❌ Source folder not found: {source_dir}")
            return False
        
        if not source_path.is_dir():
            print(f"❌ Source path is not a directory: {source_dir}")
            return False
        
        # Create parent destination directory
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # If destination already exists, remove it first
        if dest_path.exists():
            print(f"🗑️ Removing existing destination: {dest_path}")
            shutil.rmtree(dest_path)
        
        print(f"📁 Copying folder structure: {source_dir} -> {dest_dir}")
        
        # Copy entire directory tree
        shutil.copytree(source_path, dest_path)
        
        # Count copied files for verification
        audio_files = list(dest_path.rglob("*.flac")) + list(dest_path.rglob("*.wav")) + list(dest_path.rglob("*.mp3"))
        chapter_dirs = [d for d in dest_path.iterdir() if d.is_dir() and d.name.startswith('ch')]
        
        print(f"✅ Successfully copied folder structure to {dest_dir}")
        print(f"📊 Found {len(chapter_dirs)} chapters with {len(audio_files)} audio files")
        
        # Now remove the source directory since we've successfully copied it
        print(f"🗑️ Removing source directory: {source_dir}")
        shutil.rmtree(source_path)
        
        return True
        
    except Exception as e:
        print(f"❌ Error moving audio folder structure: {e}")
        return False


def move_comfyui_image_files(book_id: str, language: str = 'eng') -> bool:
    """
    Move completed ComfyUI image files from dev output to foundry images directory.
    
    Copies entire folder structure from D:/Projects/pheonix/dev/output/image/alpha/{book_id}/
    to foundry/{book_id}/{language}/images/ preserving folder structure
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (default: 'eng')
        
    Returns:
        bool: True if folder structure moved successfully
    """
    import shutil
    import os
    from pathlib import Path
    
    # Source directory - ComfyUI image output
    source_dir = f"D:/Projects/pheonix/dev/output/images/alpha/{book_id}"
    
    # Destination directory 
    dest_dir = f"foundry/{book_id}/{language}/images"
    
    print(f"🔍 Looking for image folder: {source_dir}")
    
    try:
        source_path = Path(source_dir)
        dest_path = Path(dest_dir)
        
        if not source_path.exists():
            print(f"❌ Source image folder not found: {source_dir}")
            return False
        
        if not source_path.is_dir():
            print(f"❌ Source path is not a directory: {source_dir}")
            return False
        
        # Create parent destination directory
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # If destination already exists, remove it first
        if dest_path.exists():
            print(f"🗑️ Removing existing destination: {dest_path}")
            shutil.rmtree(dest_path)
        
        print(f"📁 Copying image folder structure: {source_dir} -> {dest_dir}")
        
        # Copy entire directory tree
        shutil.copytree(source_path, dest_path)
        
        # Count copied files for verification
        image_files = list(dest_path.rglob("*.png")) + list(dest_path.rglob("*.jpg")) + list(dest_path.rglob("*.jpeg"))
        
        print(f"✅ Successfully copied image folder structure to {dest_dir}")
        print(f"📊 Found {len(image_files)} image files")
        
        # Now remove the source directory since we've successfully copied it
        print(f"🗑️ Removing source directory: {source_dir}")
        shutil.rmtree(source_path)
        
        return True
        
    except Exception as e:
        print(f"❌ Error moving image folder structure: {e}")
        return False


def combine_audiobook_files(book_id: str, language: str, audiobook_dict: Dict, combination_plan: Dict = None) -> bool:
    """
    Combine individual audio files into complete audiobook using foundry structure.
    
    Calls the modified simple_ffmpeg_combine.py functions to create chapter-wise
    and final combined audio files.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        bool: True if audio combination completed successfully
    """
    try:
        # Import the foundry-specific combine function
        from simple_ffmpeg_combine import combine_audio_from_foundry
        
        print(f"🎵 Starting audio combination for {book_id} ({language})")
        
        # Call the combination function with foundry structure and plan
        result = combine_audio_from_foundry(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict,
            combination_plan=combination_plan,  # Pass the combination plan
            chunk_gap_ms=500,      # Gap between chunks
            chapter_gap_ms=1000,   # Gap between chapters
            ffmpeg_path="ffmpeg",  # Assume ffmpeg is in PATH
            audio_format="mp3",    # Standard format
            audio_bitrate="192k",  # Good quality
            verbose=True
        )
        
        if result['success']:
            parts_created = result.get('parts_created', 0)
            chapters_processed = result.get('total_chapters_processed', 0)
            
            print(f"✅ Audio combination successful:")
            print(f"   📚 Chapters processed: {chapters_processed}")
            print(f"   🎧 Audio parts created: {parts_created}")
            
            # Log final files created
            if 'final_files' in result:
                for file_info in result['final_files']:
                    print(f"   📄 Created: {file_info['file']}")
            
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            print(f"❌ Audio combination failed: {error_msg}")
            return False
        
    except ImportError as e:
        print(f"❌ Failed to import audio combination module: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during audio combination: {e}")
        return False


def plan_audio_combinations(book_id: str, language: str, audiobook_dict: Dict) -> Dict:
    """
    Analyze audio duration and create optimal combination plan for final audiobook.
    
    Checks total duration and creates plan to split into parts if over 10-hour limit.
    Based on the logic from cli_backup.py STEP 7.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        Dict: Combination plan with parts/chapters distribution and duration info
    """
    import subprocess
    import json
    from pathlib import Path
    from math import ceil
    
    MAX_HOURS_PER_PART = 10  # Maximum hours per audiobook part (YouTube limits)
    
    print(f"📊 Planning audio combinations for {book_id} ({language})")
    
    # Chapter audio files directory (output from STEP5)
    chapters_dir = Path(f"foundry/{book_id}/{language}/combined_audio/chapters")
    
    if not chapters_dir.exists():
        print(f"❌ Chapters directory not found: {chapters_dir}")
        return {'success': False, 'error': f'Chapters directory not found: {chapters_dir}'}
    
    try:
        # Get all chapter audio files
        chapter_files = sorted(chapters_dir.glob("chapter_*.mp3"))
        if not chapter_files:
            chapter_files = sorted(chapters_dir.glob("chapter_*.flac"))
        if not chapter_files:
            chapter_files = sorted(chapters_dir.glob("chapter_*.wav"))
        
        if not chapter_files:
            print(f"❌ No chapter audio files found in {chapters_dir}")
            return {'success': False, 'error': 'No chapter audio files found'}
        
        print(f"🔍 Found {len(chapter_files)} chapter files")
        
        # Calculate duration for each chapter using ffprobe
        chapter_durations = []
        total_duration_seconds = 0
        
        for chapter_file in chapter_files:
            try:
                cmd = [
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    str(chapter_file)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                duration = float(result.stdout.strip())
                chapter_durations.append(duration)
                total_duration_seconds += duration
                
                print(f"  📄 {chapter_file.name}: {duration/3600:.2f}h ({duration/60:.1f}min)")
                
            except Exception as e:
                print(f"❌ Error getting duration for {chapter_file}: {e}")
                return {'success': False, 'error': f'Error analyzing chapter duration: {e}'}
        
        # Convert to hours and minutes
        total_hours = total_duration_seconds / 3600
        total_minutes = total_duration_seconds / 60
        
        print(f"📊 Total audiobook duration: {total_hours:.2f} hours ({total_minutes:.1f} minutes)")
        print(f"🎯 Max hours per part: {MAX_HOURS_PER_PART}")
        
        # Plan combinations based on total duration
        if total_hours <= MAX_HOURS_PER_PART:
            # Single part - fits within limit
            print(f"✅ Audiobook fits within {MAX_HOURS_PER_PART}-hour limit - single part")
            combinations = [{
                'part': 1,
                'chapters': list(range(1, len(chapter_durations) + 1)),
                'chapter_range': f"1-{len(chapter_durations)}",
                'duration_seconds': total_duration_seconds,
                'duration_hours': total_hours,
                'output_filename': f"{book_id}_full_book.mp3",
                'audio_path': f"foundry/{book_id}/{language}/combined_audio/{book_id}_full_book.mp3"
            }]
        else:
            # Multiple parts - need to split
            parts_needed = ceil(total_hours / MAX_HOURS_PER_PART)
            target_duration_per_part = total_duration_seconds / parts_needed
            
            print(f"⚠️ Audiobook exceeds {MAX_HOURS_PER_PART}-hour limit - splitting into {parts_needed} parts")
            print(f"🎯 Target duration per part: {target_duration_per_part/3600:.2f} hours")
            
            # Smart chapter distribution
            combinations = []
            current_part = 1
            current_chapters = []
            current_duration = 0
            
            for i, duration in enumerate(chapter_durations, 1):
                current_chapters.append(i)
                current_duration += duration
                
                # Check if we should start a new part
                remaining_chapters = len(chapter_durations) - len(current_chapters)
                remaining_parts = parts_needed - current_part
                
                # Start new part if we've reached optimal distribution point
                if (remaining_parts > 0 and remaining_chapters > 0 and
                    current_duration >= target_duration_per_part):
                    
                    # Create combination for current part
                    combinations.append({
                        'part': current_part,
                        'chapters': current_chapters.copy(),
                        'chapter_range': f"{current_chapters[0]}-{current_chapters[-1]}",
                        'duration_seconds': current_duration,
                        'duration_hours': current_duration / 3600,
                        'output_filename': f"{book_id}_part{current_part}.mp3",
                        'audio_path': f"foundry/{book_id}/{language}/combined_audio/{book_id}_part{current_part}.mp3"
                    })
                    
                    print(f"  📦 Part {current_part}: Chapters {current_chapters[0]}-{current_chapters[-1]} ({current_duration/3600:.2f}h)")
                    
                    # Start new part
                    current_part += 1
                    current_chapters = []
                    current_duration = 0
            
            # Add remaining chapters to final part
            if current_chapters:
                combinations.append({
                    'part': current_part,
                    'chapters': current_chapters.copy(),
                    'chapter_range': f"{current_chapters[0]}-{current_chapters[-1]}",
                    'duration_seconds': current_duration,
                    'duration_hours': current_duration / 3600,
                    'output_filename': f"{book_id}_part{current_part}.mp3",
                    'audio_path': f"foundry/{book_id}/{language}/combined_audio/{book_id}_part{current_part}.mp3"
                })
                
                print(f"  📦 Part {current_part}: Chapters {current_chapters[0]}-{current_chapters[-1]} ({current_duration/3600:.2f}h)")
        
        # Create final combination plan
        combination_plan = {
            'success': True,
            'book_id': book_id,
            'language': language,
            'total_duration_seconds': total_duration_seconds,
            'total_duration_minutes': total_minutes,
            'total_duration_hours': total_hours,
            'max_hours_per_part': MAX_HOURS_PER_PART,
            'exceeds_limit': total_hours > MAX_HOURS_PER_PART,
            'parts_needed': len(combinations),
            'chapter_durations': chapter_durations,
            'combinations': combinations
        }
        
        print(f"✅ Combination plan created: {len(combinations)} parts")
        for combo in combinations:
            print(f"  📄 {combo['output_filename']}: {combo['duration_hours']:.2f}h")
        
        return combination_plan
        
    except Exception as e:
        print(f"❌ Error creating combination plan: {e}")
        return {'success': False, 'error': str(e)}


def generate_subtitles_for_audiobook(book_id: str, language: str, audiobook_dict: Dict) -> bool:
    """
    Generate subtitle files for audiobook based on combination plan.
    
    Reads combination_plan.json and generates subtitles for each part,
    then updates the plan file with subtitle paths.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        bool: True if subtitles generated successfully
    """
    import json
    import os
    from pathlib import Path
    
    print(f"📝 Generating subtitles for {book_id} ({language})")
    
    # Read combination plan
    plan_file = f"foundry/{book_id}/{language}/combination_plan.json"
    
    if not os.path.exists(plan_file):
        print(f"❌ Combination plan not found: {plan_file}")
        return False
    
    try:
        with open(plan_file, 'r', encoding='utf-8') as f:
            combination_plan = json.load(f)
        
        combinations = combination_plan.get('combinations', [])
        if not combinations:
            print(f"❌ No combinations found in plan file")
            return False
        
        print(f"🔍 Found {len(combinations)} parts to generate subtitles for")
        
        # Import subtitle generation function
        from generate_subtitles import generate_subtitles_for_book
        
        # Create subtitles directory
        subtitles_dir = f"foundry/{book_id}/{language}/subtitles"
        os.makedirs(subtitles_dir, exist_ok=True)
        
        # Generate subtitles for each part
        for combo in combinations:
            part_num = combo['part']
            chapters = combo['chapters']
            audio_filename = combo['output_filename']
            
            # Subtitle file path
            subtitle_filename = audio_filename.replace('.mp3', '.srt').replace('.flac', '.srt').replace('.wav', '.srt')
            subtitle_path = f"foundry/{book_id}/{language}/subtitles/{subtitle_filename}"
            
            print(f"📝 Generating subtitles for Part {part_num} (Chapters: {combo['chapter_range']})")
            print(f"   Audio: {combo['audio_path']}")
            print(f"   Subtitle: {subtitle_path}")
            
            # Generate subtitles using existing function
            result = generate_subtitles_for_book(
                book_id=book_id,
                audio_path=f"foundry/{book_id}/{language}/speech",  # Source audio with chapters/chunks
                text_path=f"foundry/{book_id}/{language}/chapters",  # Chapter metadata  
                output_path=subtitles_dir,
                chapters_to_include=chapters,  # Only chapters for this part
                copy_to_combined_audio=False,  # We'll handle file placement
                verbose=True
            )
            
            if not result.get('success', False):
                print(f"❌ Failed to generate subtitles for Part {part_num}")
                return False
            
            # Add subtitle path to combination plan
            combo['subtitle_path'] = subtitle_path
            
            print(f"✅ Subtitles generated for Part {part_num}")
        
        # Save updated combination plan with subtitle paths
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(combination_plan, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Subtitle generation completed - updated combination plan saved")
        return True
        
    except Exception as e:
        print(f"❌ Error generating subtitles: {e}")
        return False


def generate_image_prompts_for_audiobook(book_id: str, language: str, audiobook_dict: Dict, verbose: bool = True) -> bool:
    """
    Generate image prompts for audiobook based on combination plan.
    
    Reads combination_plan.json and generates image prompts for each part,
    then updates the plan file with image prompt paths.
    
    Args:
        book_id: Book identifier (e.g., 'pg74')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        bool: True if image prompts generated successfully
    """
    import json
    import os
    from pathlib import Path
    
    print(f"🎨 Generating image prompts for {book_id} ({language})")
    
    # Read combination plan
    plan_file = f"foundry/{book_id}/{language}/combination_plan.json"
    
    if not os.path.exists(plan_file):
        print(f"❌ Combination plan not found: {plan_file}")
        return False
    
    try:
        with open(plan_file, 'r', encoding='utf-8') as f:
            combination_plan = json.load(f)
        
        combinations = combination_plan.get('combinations', [])
        if not combinations:
            print(f"❌ No combinations found in plan file")
            return False
        
        print(f"🔍 Found {len(combinations)} parts to generate image prompts for")
        
        # Import image prompt generation function (new foundry wrapper)
        from generate_image_prompts import generate_image_prompts_from_foundry
        
        # Create image prompts directory
        prompts_dir = f"foundry/{book_id}/{language}/image_prompts"
        os.makedirs(prompts_dir, exist_ok=True)
        
        # Generate image prompts using new foundry wrapper
        print(f"🎨 Calling foundry-compatible image prompt generation")
        
        result = generate_image_prompts_from_foundry(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict,
            model_profile='balanced',
            verbose=verbose
        )
        
        if result.get('success', False):
            # Update combination plan with image prompt paths
            for combo in combinations:
                part_num = combo['part']
                
                # Image prompts file path
                if len(combinations) > 1:
                    # Multi-part: include part number
                    prompts_filename = f"{book_id}_part{part_num}_prompts.json"
                else:
                    # Single part: no part number needed
                    prompts_filename = f"{book_id}_prompts.json"
                
                prompts_path = f"foundry/{book_id}/{language}/image_prompts/{prompts_filename}"
                combo['image_prompts_path'] = prompts_path
                
                print(f"✅ Updated combination plan with prompts path for Part {part_num}")
            
            # Save updated combination plan with image prompt paths
            with open(plan_file, 'w', encoding='utf-8') as f:
                json.dump(combination_plan, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Image prompt generation completed - updated combination plan saved")
            return True
        else:
            error_msg = result.get('error', 'Image prompt generation failed')
            print(f"❌ {error_msg}")
            return False
        
    except Exception as e:
        print(f"❌ Error generating image prompts: {e}")
        return False


def create_image_jobs_for_audiobook(book_id: str, language: str, audiobook_dict: Dict) -> bool:
    """
    Create ComfyUI image generation jobs for audiobook based on combination plan.
    
    Reads combination_plan.json and image prompts to create ComfyUI job files,
    similar to how create_tts_audio_jobs works.
    
    Args:
        book_id: Book identifier (e.g., 'pg23731')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        bool: True if image jobs created successfully
    """
    try:
        # Import the foundry-specific image job creation function
        from create_image_jobs import create_image_jobs_from_foundry
        
        print(f"🖼️ Starting image job creation for {book_id} ({language})")
        
        # Call the image job creation function with foundry structure
        result = create_image_jobs_from_foundry(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict,
            jobs_output_dir="comfyui_jobs/processing/image",  # Organized in image subfolder
            finished_images_dir="comfyui_jobs/finished/image",   # Organized in image subfolder
            workflow_template="workflows/image_qwen_image.json",  # Default workflow
            verbose=True
        )
        
        if result['success']:
            jobs_created = result.get('total_jobs_created', 0)
            parts_processed = result.get('parts_processed', 0)
            
            print(f"✅ Image job creation successful:")
            print(f"   🎨 Parts processed: {parts_processed}")
            print(f"   📄 Total jobs created: {jobs_created}")
            
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            print(f"❌ Image job creation failed: {error_msg}")
            return False
        
    except ImportError as e:
        print(f"❌ Failed to import image job creation module: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during image job creation: {e}")
        return False


def select_images_for_audiobook(book_id: str, language: str, audiobook_dict: Dict) -> bool:
    """
    Select one image per part for audiobook thumbnails and update combination plan.
    
    Randomly picks one image per part from generated images and adds selected
    image paths to combination_plan.json.
    
    Args:
        book_id: Book identifier (e.g., 'pg23731')
        language: Language code (e.g., 'eng')
        audiobook_dict: Complete audiobook metadata dict
        
    Returns:
        bool: True if images selected successfully
    """
    import json
    import os
    import random
    from pathlib import Path
    
    print(f"🎯 Selecting images for {book_id} ({language})")
    
    # Read combination plan
    plan_file = f"foundry/{book_id}/{language}/combination_plan.json"
    
    if not os.path.exists(plan_file):
        print(f"❌ Combination plan not found: {plan_file}")
        return False
    
    try:
        with open(plan_file, 'r', encoding='utf-8') as f:
            combination_plan = json.load(f)
        
        combinations = combination_plan.get('combinations', [])
        if not combinations:
            print(f"❌ No combinations found in plan file")
            return False
        
        print(f"🔍 Found {len(combinations)} parts to select images for")
        
        # Images base directory
        images_base_dir = Path(f"foundry/{book_id}/{language}/images")
        
        if not images_base_dir.exists():
            print(f"❌ Images directory not found: {images_base_dir}")
            return False
        
        # Select one image per part
        selections_made = 0
        for combo in combinations:
            part_num = combo['part']
            
            # Look for images in this part's directory
            part_dir = images_base_dir / f"part{part_num}"
            
            if not part_dir.exists():
                print(f"⚠️ Warning: Part {part_num} images directory not found: {part_dir}")
                continue
            
            # Find all image files in this part
            image_files = []
            for pattern in ["*.png", "*.jpg", "*.jpeg"]:
                image_files.extend(list(part_dir.rglob(pattern)))
            
            if not image_files:
                print(f"⚠️ Warning: No image files found for Part {part_num} in {part_dir}")
                continue
            
            # Randomly select one image
            selected_image = random.choice(image_files)
            selected_image_path = str(selected_image).replace('\\', '/')  # Normalize path separators
            
            # Add selected image path to combination plan
            combo['selected_image_path'] = selected_image_path
            selections_made += 1
            
            print(f"✅ Part {part_num}: Selected {selected_image.name} from {len(image_files)} images")
            print(f"   Path: {selected_image_path}")
        
        if selections_made == 0:
            print(f"❌ No images could be selected for any part")
            return False
        
        # Save updated combination plan with selected image paths
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(combination_plan, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Image selection completed - {selections_made} images selected")
        print(f"💾 Updated combination plan saved")
        return True
        
    except Exception as e:
        print(f"❌ Error selecting images: {e}")
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