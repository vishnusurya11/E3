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
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, book_id, book_title, author, narrated_by, input_file,
                       narrator_audio,
                       parse_novel_status, metadata_status, audio_generation_status, 
                       audio_files_moved_status, audio_combination_planned_status,
                       subtitle_generation_status, audio_combination_status, video_generation_status,
                       parse_novel_completed_at, metadata_completed_at, audio_generation_completed_at,
                       audio_files_moved_completed_at, audio_combination_planned_completed_at,
                       subtitle_generation_completed_at, audio_combination_completed_at, video_generation_completed_at,
                       created_at, updated_at, metadata,
                       total_chapters, total_chunks, total_words,
                       total_audio_files, audio_jobs_completed, audio_duration_seconds, audio_file_size_bytes,
                       retry_count, max_retries,
                       image_prompts_status, image_prompts_started_at, image_prompts_completed_at,
                       image_jobs_generation_status, image_jobs_generation_completed_at,
                       image_jobs_completed, total_image_jobs, image_generation_status, image_generation_completed_at
                FROM audiobook_processing 
                ORDER BY id
            """)
            
            columns = [desc[0] for desc in cursor.description]
            books = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
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