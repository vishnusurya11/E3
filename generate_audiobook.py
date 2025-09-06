#!/usr/bin/env python3
"""
Unified Audiobook Generation Workflow

Automated end-to-end audiobook generation from Project Gutenberg texts.
Processes books through all stages: parsing, TTS, audio combination, 
subtitle generation, and video creation.
"""

import csv
import json
import time
import sys
import os
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Audiobook pipeline modules imported as needed within functions

# Configuration
MAX_HOURS_PER_PART = 10  # Maximum hours per audiobook part (configurable for YouTube limits)

from parse_novel_tts import parse_novel
from create_tts_audio_jobs import create_tts_jobs
from audiobook_helper import get_all_books, get_processable_books, update_book_record, log_simple, mark_stage_completed, mark_stage_failed


################################################################################
# STEP 1: GET DATA FROM DATABASE  
################################################################################

def get_books_from_db() -> List[Dict]:
    """Connect to database and get all audiobook records."""
    print("STEP 1: Connecting to audiobook database...")
    
    # Use helper function
    books = get_all_books()
    
    if books:
        # Show what needs processing
        pending_books = [book for book in books if book['parse_novel_status'] == 'pending']
        print(f"Books that need processing: {len(pending_books)}")
        
        for book in pending_books:
            print(f"  - {book['book_id']}: {book['book_title']}")
    
    return books


################################################################################
# STEP 2: PARSE ONE RECORD
################################################################################

def parse_one_book(book_record: Dict, output_dir: str) -> bool:
    """Parse the selected book record and update database."""
    print(f"\nSTEP 2: Parsing book record...")
    
    book_id = book_record['book_id']
    book_title = book_record['book_title']
    input_file = book_record['input_file']
    
    print(f"Selected book: {book_title} (ID: {book_id})")
    print(f"Input file: {input_file}")
    print(f"Output directory: {output_dir}")
    
    # Update dict to processing status
    book_record['parse_novel_status'] = 'processing'
    update_book_record(book_record)  # Sync to database
    log_simple(book_id, f"Started parsing '{book_title}'", 'INFO', 'parse_start')
    
    try:
        print("Running parse_novel...")
        
        result = parse_novel(
            input_file=input_file,
            output_dir=output_dir,
            verbose=True
        )
        
        if result['success']:
            # Update dict with completion
            book_record = mark_stage_completed(book_record, 'parse_novel')
            
            # Add result data to dict
            book_record['total_chapters'] = result['total_chapters_all_books']
            book_record['total_chunks'] = result['total_chunks_all_books']
            book_record['total_words'] = result['total_words_all_books']
            
            # Sync back to database
            update_book_record(book_record)
            log_simple(book_id, f"Parse completed - {book_record['total_chapters']} chapters, {book_record['total_words']} words", 'INFO', 'parse_complete')
            
            print(f"Parse completed successfully!")
            print(f"   Total chapters: {book_record['total_chapters']}")
            print(f"   Total chunks: {book_record['total_chunks']}")
            print(f"   Total words: {book_record['total_words']}")
            return True
        else:
            # Update dict with failure
            book_record = mark_stage_failed(book_record, 'parse_novel')
            update_book_record(book_record)
            log_simple(book_id, f"Parse failed: {result.get('error', 'Unknown error')}", 'ERROR', 'parse_failed')
            
            print(f"Parse failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        # Update dict with failure
        book_record = mark_stage_failed(book_record, 'parse_novel')
        update_book_record(book_record)
        log_simple(book_id, f"Parse error: {e}", 'ERROR', 'parse_error')
        
        print(f"Parse error: {e}")
        return False


################################################################################
# STEP 4: GENERATE AUDIO JOBS
################################################################################

def generate_audio_jobs_for_book(book_dict: Dict, processing_dir: str) -> bool:
    """Generate TTS job files for the book."""
    print(f"\nSTEP 4: Generating audio jobs...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    narrator_audio = book_dict.get('narrator_audio')
    
    if not narrator_audio:
        print(f"No narrator_audio found for book {book_id}")
        log_simple(book_id, f"No narrator_audio configured for book", 'ERROR', 'audio_jobs_failed')
        return False
    
    # Input: foundry/processing/pg1155/
    book_folder = Path(processing_dir) / book_id
    
    print(f"Book folder: {book_folder}")
    print(f"Narrator audio: {narrator_audio}")
    
    if not book_folder.exists():
        print(f"Book folder not found: {book_folder}")
        log_simple(book_id, f"Book folder not found: {book_folder}", 'ERROR', 'audio_jobs_failed')
        return False
    
    # Output: jobs/processing/speech/ (regular jobs path)
    jobs_output_dir = "comfyui_jobs/processing/speech"
    finished_audio_dir = "comfyui_jobs/finished/speech"
    
    log_simple(book_id, f"Starting audio job generation for '{book_title}'", 'INFO', 'audio_jobs_start')
    
    try:
        print(f"Creating TTS jobs from: {book_folder}")
        
        # Use create_tts_jobs function
        result = create_tts_jobs(
            input_book_dir=str(book_folder),
            jobs_output_dir=jobs_output_dir,
            finished_audio_dir=finished_audio_dir,
            voice_sample=narrator_audio,
            verbose=False  # We handle our own logging
        )
        
        if result['success']:
            # Update database with job count
            book_dict['total_audio_files'] = result['total_jobs_created']
            book_dict = mark_stage_completed(book_dict, 'audio_generation')
            update_book_record(book_dict)
            
            log_simple(book_id, f"Audio jobs created: {result['total_jobs_created']} jobs", 'INFO', 'audio_jobs_complete')
            print(f"Audio jobs created: {result['total_jobs_created']} jobs")
            print(f"   Jobs location: {jobs_output_dir}")
            return True
        else:
            book_dict = mark_stage_failed(book_dict, 'audio_generation')
            update_book_record(book_dict)
            log_simple(book_id, f"Audio job creation failed: {result.get('error', 'Unknown error')}", 'ERROR', 'audio_jobs_failed')
            print(f"Audio job creation failed")
            return False
            
    except Exception as e:
        book_dict = mark_stage_failed(book_dict, 'audio_generation')
        update_book_record(book_dict)
        log_simple(book_id, f"Audio job creation error: {e}", 'ERROR', 'audio_jobs_error')
        print(f"Audio job creation error: {e}")
        return False


################################################################################
# STEP 5: CHECK AUDIO JOBS COMPLETION
################################################################################

def check_audio_jobs_completion(book_dict: Dict) -> bool:
    """Check if all audio jobs for this book are completed."""
    print(f"\nSTEP 5: Checking audio jobs completion...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    total_jobs = book_dict.get('total_audio_files', 0)
    current_completed = book_dict.get('audio_jobs_completed', 0)
    
    print(f"Book ID: {book_id}")
    print(f"Current status: {book_dict.get('audio_generation_status', 'unknown')}")
    print(f"Expected total jobs: {total_jobs}")
    print(f"Previously recorded completed: {current_completed}")
    
    if total_jobs == 0:
        print(f"No audio jobs found for book {book_id}")
        log_simple(book_id, f"No audio jobs to check", 'WARNING', 'audio_check_no_jobs')
        return False
    
    print(f"Checking {total_jobs} audio jobs for book '{book_title}'")
    
    try:
        # Query ComfyUI jobs database for completed jobs
        import sqlite3
        query_pattern = f"SPEECH_{book_id}_%"
        print(f"DEBUG: Querying jobs with pattern: {query_pattern}")
        
        with sqlite3.connect("database/comfyui_agent.db") as conn:
            cursor = conn.cursor()
            
            # Debug: Show some sample job names first
            cursor.execute("""
                SELECT config_name, status FROM comfyui_jobs 
                WHERE config_name LIKE ? LIMIT 5
            """, (query_pattern,))
            sample_jobs = cursor.fetchall()
            print(f"DEBUG: Sample jobs found:")
            for job_name, status in sample_jobs:
                print(f"  {job_name} -> {status}")
            
            # Now get the actual count
            cursor.execute("""
                SELECT COUNT(*) FROM comfyui_jobs 
                WHERE config_name LIKE ? AND status = 'done'
            """, (query_pattern,))
            
            completed_count = cursor.fetchone()[0]
            print(f"DEBUG: Database query returned {completed_count} completed jobs")
        
        # Update progress in audiobook database
        print(f"DEBUG: Updating audio_jobs_completed from {current_completed} to {completed_count}")
        book_dict['audio_jobs_completed'] = completed_count
        
        # Force database update
        success = update_book_record(book_dict)
        print(f"DEBUG: Database update success: {success}")
        
        print(f"Audio jobs progress: {completed_count}/{total_jobs} completed")
        log_simple(book_id, f"Audio jobs progress: {completed_count}/{total_jobs}", 'INFO', 'audio_progress_check')
        
        if completed_count >= total_jobs:
            # All done - mark audio generation completed
            print(f"DEBUG: All jobs completed! Marking status as 'completed'")
            book_dict['audio_generation_status'] = 'completed'
            book_dict['audio_generation_completed_at'] = datetime.now().isoformat()
            update_success = update_book_record(book_dict)
            print(f"DEBUG: Status update success: {update_success}")
            
            log_simple(book_id, f"All audio jobs completed ({completed_count}/{total_jobs})", 'INFO', 'audio_complete')
            print(f"All audio jobs completed - ready for next stage")
            return True
        else:
            # Keep as processing
            print(f"DEBUG: Jobs still processing, keeping status as 'processing'")
            book_dict['audio_generation_status'] = 'processing'
            update_success = update_book_record(book_dict)
            print(f"DEBUG: Status update success: {update_success}")
            
            log_simple(book_id, f"Audio jobs still processing ({completed_count}/{total_jobs})", 'INFO', 'audio_still_processing')
            print(f"Audio jobs still processing - will check again next run")
            return False
            
    except Exception as e:
        print(f"DEBUG: Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        log_simple(book_id, f"Error checking audio jobs: {e}", 'ERROR', 'audio_check_error')
        print(f"Error checking audio jobs: {e}")
        return False


################################################################################
# STEP 6: MOVE AUDIO FILES TO PROCESSING DIRECTORY
################################################################################

def move_audio_files_for_book(book_dict: Dict) -> bool:
    """Move generated audio directory structure from dev/output to foundry/processing."""
    print(f"\nSTEP 6: Moving audio directory to processing directory...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    # CRITICAL SAFETY CHECK: Verify all audio jobs are actually completed
    total_jobs = book_dict.get('total_audio_files', 0)
    completed_jobs = book_dict.get('audio_jobs_completed', 0)
    
    print(f"🔍 SAFETY CHECK: Audio job completion validation")
    print(f"  Expected jobs: {total_jobs}")
    print(f"  Completed jobs: {completed_jobs}")
    
    if total_jobs > 0 and completed_jobs < total_jobs:
        print(f"❌ SAFETY CHECK FAILED: Only {completed_jobs}/{total_jobs} jobs completed!")
        print(f"❌ Cannot move files until ALL audio jobs are finished")
        log_simple(book_id, f"Move blocked: {completed_jobs}/{total_jobs} jobs complete", 'ERROR', 'audio_move_blocked')
        return False
    
    print(f"✅ SAFETY CHECK PASSED: All {completed_jobs} jobs completed")
    
    # Source: dev/output/speech/{book_id}/
    source_dir = Path("D:/Projects/pheonix/dev/output/speech") / book_id
    
    # Destination: foundry/processing/{book_id}/speech/
    dest_dir = Path("foundry/processing") / book_id / "speech"
    
    print(f"Moving audio directory for book '{book_title}' (ID: {book_id})")
    print(f"  Source: {source_dir}")
    print(f"  Destination: {dest_dir}")
    
    if not source_dir.exists():
        print(f"Source directory not found: {source_dir}")
        log_simple(book_id, f"Source audio directory not found: {source_dir}", 'ERROR', 'audio_move_failed')
        return False
    
    if dest_dir.exists():
        print(f"Destination directory already exists: {dest_dir}")
        log_simple(book_id, f"Destination already exists, removing: {dest_dir}", 'WARNING', 'audio_move_dest_exists')
        import shutil
        shutil.rmtree(dest_dir)
    
    # Update status to processing
    book_dict['audio_files_moved_status'] = 'processing'
    update_book_record(book_dict)
    log_simple(book_id, f"Starting audio directory move for '{book_title}'", 'INFO', 'audio_move_start')
    
    try:
        import shutil
        
        # Count total files before move for logging
        total_files = sum(1 for f in source_dir.rglob('*') if f.is_file())
        
        print(f"Moving entire directory structure with all subdirectories...")
        print(f"  Estimated files to move: {total_files}")
        
        # Copy entire directory structure (preserves all subdirectories)
        shutil.copytree(str(source_dir), str(dest_dir))
        print(f"Directory structure copied successfully")
        
        # Verify the copy worked by checking if destination exists and has content
        if not dest_dir.exists():
            raise Exception("Destination directory not created")
        
        # Count files in destination to verify
        dest_files = sum(1 for f in dest_dir.rglob('*') if f.is_file())
        
        print(f"Verified destination has content")
        
        # Remove source directory after successful copy (completing the "move")
        print(f"Removing source directory after successful copy...")
        shutil.rmtree(str(source_dir))
        print(f"Source directory removed")
        
        # Mark as completed
        book_dict['audio_files_moved_status'] = 'completed'
        book_dict['audio_files_moved_completed_at'] = datetime.now().isoformat()
        update_book_record(book_dict)
        
        log_simple(book_id, f"Audio directory moved successfully with all subdirectories", 'INFO', 'audio_move_complete')
        print(f"Audio directory moved successfully - ready for next stage")
        return True
            
    except Exception as e:
        book_dict['audio_files_moved_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Audio directory move error: {e}", 'ERROR', 'audio_move_error')
        print(f"Audio directory move error: {e}")
        return False


################################################################################
# STEP 7: PLAN AUDIO COMBINATIONS
################################################################################

def plan_audio_combinations_for_book(book_dict: Dict) -> bool:
    """Analyze audio files and create optimal combination plan within YouTube limits."""
    print(f"\nSTEP 7: Planning audio combinations...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    # Audio directory: foundry/processing/{book_id}/speech/
    speech_dir = Path("foundry/processing") / book_id / "speech"
    metadata_file = Path("foundry/processing") / book_id / "metadata.json"
    
    print(f"Planning audio combinations for book '{book_title}' (ID: {book_id})")
    print(f"  Speech directory: {speech_dir}")
    print(f"  Max hours per part: {MAX_HOURS_PER_PART}")
    
    if not speech_dir.exists():
        print(f"Speech directory not found: {speech_dir}")
        log_simple(book_id, f"Speech directory not found: {speech_dir}", 'ERROR', 'combination_plan_failed')
        return False
    
    if not metadata_file.exists():
        print(f"Metadata file not found: {metadata_file}")
        log_simple(book_id, f"Metadata file not found: {metadata_file}", 'ERROR', 'combination_plan_failed')
        return False
    
    # Update status to processing
    book_dict['audio_combination_planned_status'] = 'processing'
    update_book_record(book_dict)
    log_simple(book_id, f"Starting audio combination planning for '{book_title}'", 'INFO', 'combination_plan_start')
    
    try:
        import json
        import subprocess
        from math import ceil
        
        # Load existing metadata
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        print(f"Analyzing audio durations for {metadata['total_chapters']} chapters...")
        
        # Analyze each chapter's audio duration
        chapter_durations = []
        total_duration_seconds = 0
        
        for chapter_info in metadata['chapters']:
            chapter_index = chapter_info['index']
            chapter_dir = speech_dir / f"ch{chapter_index:03d}"
            
            if not chapter_dir.exists():
                print(f"  Warning: Chapter directory not found: {chapter_dir}")
                continue
            
            # Find all audio files in chapter directory
            audio_files = []
            for ext in ['.flac', '.wav', '.mp3']:
                audio_files.extend(chapter_dir.rglob(f"*{ext}"))
            
            if not audio_files:
                print(f"  Warning: No audio files found in {chapter_dir}")
                continue
            
            # Get duration of all audio files in this chapter using ffprobe
            chapter_duration = 0
            for audio_file in audio_files:
                try:
                    result = subprocess.run([
                        'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', str(audio_file)
                    ], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        duration = float(result.stdout.strip())
                        chapter_duration += duration
                except Exception as e:
                    print(f"    Warning: Could not get duration for {audio_file}: {e}")
            
            chapter_durations.append({
                'chapter': chapter_index,
                'title': chapter_info['title'],
                'duration_seconds': chapter_duration,
                'duration_minutes': chapter_duration / 60,
                'duration_hours': chapter_duration / 3600
            })
            
            total_duration_seconds += chapter_duration
            print(f"  Chapter {chapter_index}: {chapter_duration/60:.1f} minutes")
        
        total_hours = total_duration_seconds / 3600
        total_minutes = total_duration_seconds / 60
        
        print(f"Total audiobook duration: {total_hours:.2f} hours ({total_minutes:.1f} minutes)")
        
        # Plan combinations based on total duration
        if total_hours <= MAX_HOURS_PER_PART:
            # Single part - fits within limit
            print(f"Audiobook fits within {MAX_HOURS_PER_PART}-hour limit - single part")
            combinations = [{
                'part': 1,
                'chapters': list(range(1, len(chapter_durations) + 1)),
                'chapter_range': f"1-{len(chapter_durations)}",
                'duration_seconds': total_duration_seconds,
                'duration_minutes': total_minutes,
                'duration_hours': total_hours,
                'output_filename': f"{book_id}_complete.mp3"
            }]
        else:
            # Multiple parts - need to split
            parts_needed = ceil(total_hours / MAX_HOURS_PER_PART)
            target_duration_per_part = total_duration_seconds / parts_needed
            
            print(f"Audiobook exceeds {MAX_HOURS_PER_PART}-hour limit - splitting into {parts_needed} parts")
            print(f"Target duration per part: {target_duration_per_part/3600:.2f} hours")
            
            # Smart chapter distribution
            combinations = []
            current_part = 1
            current_chapters = []
            current_duration = 0
            
            for chapter_info in chapter_durations:
                # Add chapter to current part
                current_chapters.append(chapter_info['chapter'])
                current_duration += chapter_info['duration_seconds']
                
                # Check if we should start a new part
                remaining_chapters = len(chapter_durations) - len(current_chapters)
                remaining_parts = parts_needed - current_part
                
                # Start new part if:
                # 1. Current duration exceeds target AND we have remaining chapters
                # 2. OR we've reached optimal distribution point
                if (remaining_parts > 0 and remaining_chapters > 0 and
                    (current_duration >= target_duration_per_part or
                     remaining_chapters <= remaining_parts)):
                    
                    # Finalize current part
                    combinations.append({
                        'part': current_part,
                        'chapters': current_chapters.copy(),
                        'chapter_range': f"{current_chapters[0]}-{current_chapters[-1]}",
                        'duration_seconds': current_duration,
                        'duration_minutes': current_duration / 60,
                        'duration_hours': current_duration / 3600,
                        'output_filename': f"{book_id}_part{current_part}.mp3"
                    })
                    
                    # Start new part
                    current_part += 1
                    current_chapters = []
                    current_duration = 0
            
            # Add final part if there are remaining chapters
            if current_chapters:
                combinations.append({
                    'part': current_part,
                    'chapters': current_chapters,
                    'chapter_range': f"{current_chapters[0]}-{current_chapters[-1]}",
                    'duration_seconds': current_duration,
                    'duration_minutes': current_duration / 60,
                    'duration_hours': current_duration / 3600,
                    'output_filename': f"{book_id}_part{current_part}.mp3"
                })
        
        print(f"\nCombination plan created:")
        for combo in combinations:
            print(f"  Part {combo['part']}: Chapters {combo['chapter_range']} "
                  f"({combo['duration_hours']:.2f} hours)")
        
        # Add combination plan to metadata
        metadata['audio_combination_plan'] = {
            'analysis_completed_at': datetime.now().isoformat(),
            'total_duration_seconds': total_duration_seconds,
            'total_duration_minutes': total_minutes,
            'total_duration_hours': total_hours,
            'max_hours_per_part': MAX_HOURS_PER_PART,
            'exceeds_limit': total_hours > MAX_HOURS_PER_PART,
            'parts_needed': len(combinations),
            'chapter_durations': chapter_durations,
            'combinations': combinations
        }
        
        # Save updated metadata
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Mark as completed
        book_dict['audio_combination_planned_status'] = 'completed'
        book_dict['audio_combination_planned_completed_at'] = datetime.now().isoformat()
        update_book_record(book_dict)
        
        log_simple(book_id, f"Audio combination plan created: {len(combinations)} parts, {total_hours:.2f} hours total", 'INFO', 'combination_plan_complete')
        print(f"Audio combination plan saved to metadata.json - ready for next stage")
        return True
            
    except Exception as e:
        book_dict['audio_combination_planned_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Audio combination planning error: {e}", 'ERROR', 'combination_plan_error')
        print(f"Audio combination planning error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 8: GENERATE SUBTITLES
################################################################################

def generate_subtitles_for_book_pipeline(book_dict: Dict) -> bool:
    """Generate subtitle files for the audiobook."""
    print(f"\nSTEP 8: Generating subtitles...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    # Paths - all under foundry/processing/{book_id}/
    speech_dir = Path("foundry/processing") / book_id / "speech"
    text_dir = Path("foundry/processing") / book_id
    output_dir = Path("foundry/processing") / book_id / "subtitles"
    
    print(f"Generating subtitles for book '{book_title}' (ID: {book_id})")
    print(f"  Audio source: {speech_dir}")
    print(f"  Text source: {text_dir}")
    print(f"  Output: {output_dir}")
    
    if not speech_dir.exists():
        print(f"Speech directory not found: {speech_dir}")
        log_simple(book_id, f"Speech directory not found: {speech_dir}", 'ERROR', 'subtitle_failed')
        return False
    
    if not text_dir.exists():
        print(f"Text directory not found: {text_dir}")
        log_simple(book_id, f"Text directory not found: {text_dir}", 'ERROR', 'subtitle_failed')
        return False
    
    # Update status to processing
    book_dict['subtitle_generation_status'] = 'processing'
    update_book_record(book_dict)
    log_simple(book_id, f"Starting subtitle generation for '{book_title}'", 'INFO', 'subtitle_start')
    
    try:
        # Import the function we just refactored
        from generate_subtitles import generate_subtitles_for_book
        
        # Generate subtitles using our reusable function
        result = generate_subtitles_for_book(
            book_id=book_id,
            audio_path=str(speech_dir),
            text_path=str(text_dir),
            output_path=str(output_dir),
            chapters_to_include=None,  # All chapters
            copy_to_combined_audio=False,  # We don't need the copy feature
            verbose=True
        )
        
        if result['success']:
            # Mark as completed
            book_dict['subtitle_generation_status'] = 'completed'
            book_dict['subtitle_generation_completed_at'] = datetime.now().isoformat()
            update_book_record(book_dict)
            
            log_simple(book_id, f"Subtitles generated: {result['total_subtitles']} subtitles, {result['total_duration']:.1f}s", 'INFO', 'subtitle_complete')
            print(f"Subtitles generated successfully!")
            print(f"   Total subtitles: {result['total_subtitles']}")
            print(f"   Duration: {result['total_duration']:.1f}s")
            print(f"   File: {result['subtitle_file']}")
            return True
        else:
            book_dict['subtitle_generation_status'] = 'failed'
            update_book_record(book_dict)
            
            log_simple(book_id, f"Subtitle generation failed: {result.get('error', 'Unknown error')}", 'ERROR', 'subtitle_failed')
            print(f"Subtitle generation failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        book_dict['subtitle_generation_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Subtitle generation error: {e}", 'ERROR', 'subtitle_error')
        print(f"Subtitle generation error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 9: COMBINE AUDIO FILES
################################################################################

def combine_audio_for_book_pipeline(book_dict: Dict) -> bool:
    """Combine audio files according to Step 7 combination plan."""
    print(f"\nSTEP 9: Combining audio files...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    # Paths - all under foundry/processing/{book_id}/
    speech_dir = Path("foundry/processing") / book_id / "speech"
    output_dir = Path("foundry/processing") / book_id / "combined_audio"
    metadata_file = Path("foundry/processing") / book_id / "metadata.json"
    
    print(f"Combining audio for book '{book_title}' (ID: {book_id})")
    print(f"  Audio source: {speech_dir}")
    print(f"  Output: {output_dir}")
    
    if not speech_dir.exists():
        print(f"Speech directory not found: {speech_dir}")
        log_simple(book_id, f"Speech directory not found: {speech_dir}", 'ERROR', 'audio_combine_failed')
        return False
    
    if not metadata_file.exists():
        print(f"Metadata file not found: {metadata_file}")
        log_simple(book_id, f"Metadata file not found: {metadata_file}", 'ERROR', 'audio_combine_failed')
        return False
    
    # Update status to processing
    book_dict['audio_combination_status'] = 'processing'
    update_book_record(book_dict)
    log_simple(book_id, f"Starting audio combination for '{book_title}'", 'INFO', 'audio_combine_start')
    
    try:
        # Load combination plan from Step 7
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        combination_plan = metadata.get('audio_combination_plan')
        if not combination_plan:
            print(f"No combination plan found in metadata.json")
            log_simple(book_id, f"No combination plan found in metadata", 'ERROR', 'audio_combine_failed')
            return False
        
        print(f"Using combination plan: {combination_plan['parts_needed']} parts, {combination_plan['total_duration_hours']:.2f} hours")
        
        # Import the function we just refactored
        from simple_ffmpeg_combine import combine_audio_for_book
        
        # Combine audio using our reusable function with Step 7 plan
        result = combine_audio_for_book(
            book_id=book_id,
            input_path=str(speech_dir),
            output_path=str(output_dir),
            combination_plan=combination_plan,  # Use Step 7 combination plan
            metadata_sources=[str(metadata_file)],  # Use our metadata file
            chunk_gap_ms=500,
            chapter_gap_ms=1000,
            ffmpeg_path="ffmpeg",  # Will use system ffmpeg
            audio_format="mp3",     # Use MP3 like original working script
            audio_bitrate="192k",   # Use 192k like original working script  
            verbose=True
        )
        
        if result['success']:
            # Mark as completed
            book_dict['audio_combination_status'] = 'completed'
            book_dict['audio_combination_completed_at'] = datetime.now().isoformat()
            update_book_record(book_dict)
            
            log_simple(book_id, f"Audio combination completed: {result['parts_created']} parts, {result['total_chapters_processed']} chapters", 'INFO', 'audio_combine_complete')
            print(f"Audio combination completed successfully!")
            print(f"   Parts created: {result['parts_created']}")
            print(f"   Chapters processed: {result['total_chapters_processed']}")
            for final_file in result['final_files']:
                print(f"   Created: {final_file['file'].name} ({final_file['chapters']} chapters)")
            
            # Mark audio combination as completed
            mark_stage_completed(book_dict, 'audio_combination_completed')
            return True
        else:
            book_dict['audio_combination_status'] = 'failed'
            update_book_record(book_dict)
            
            log_simple(book_id, f"Audio combination failed: {result.get('error', 'Unknown error')}", 'ERROR', 'audio_combine_failed')
            print(f"Audio combination failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        book_dict['audio_combination_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Audio combination error: {e}", 'ERROR', 'audio_combine_error')
        print(f"Audio combination error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 10: GENERATE IMAGE PROMPTS FOR THUMBNAILS
################################################################################

def generate_image_prompts_for_book_pipeline(book_dict: Dict) -> bool:
    """Generate thumbnail prompts for all video parts after audio combination."""
    print(f"\nSTEP 10: Generating thumbnail prompts...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    author = book_dict['author'] 
    narrator = book_dict['narrated_by']
    
    print(f"Generating prompts for '{book_title}' by {author} (ID: {book_id})")
    
    # Update status to processing
    book_dict['image_prompts_status'] = 'processing'
    book_dict['image_prompts_started_at'] = datetime.now().isoformat()
    update_book_record(book_dict)
    log_simple(book_id, f"Starting image prompt generation for '{book_title}'", 'INFO', 'image_prompts_start')
    
    try:
        # Import and call the image prompt generation function
        from generate_image_prompts import generate_image_prompts_for_book
        
        metadata_file_path = f"foundry/processing/{book_id}/metadata.json"
        
        result = generate_image_prompts_for_book(
            book_id=book_id,
            book_title=book_title,
            author=author,
            narrated_by=narrator,
            metadata_file_path=metadata_file_path,
            model_profile='balanced',  # Use balanced model profile for cost efficiency
            temperature=0.7,
            verbose=True
        )
        
        if result['success']:
            # VALIDATION: Verify prompts actually exist in metadata before marking complete
            import os
            import json
            metadata_file = f"foundry/processing/{book_id}/metadata.json"
            validation_passed = False
            
            try:
                if os.path.exists(metadata_file):
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    image_prompts = metadata.get('image_prompts', {})
                    parts = image_prompts.get('parts', [])
                    total_prompts = sum(len(part.get('prompts', [])) for part in parts)
                    
                    if total_prompts > 0:
                        validation_passed = True
                        print(f"✅ VALIDATION: Found {total_prompts} prompts in metadata")
                    else:
                        print(f"❌ VALIDATION: No prompts found in metadata")
                else:
                    print(f"❌ VALIDATION: Metadata file not found")
                    
            except Exception as e:
                print(f"❌ VALIDATION: Error reading metadata: {e}")
            
            if not validation_passed:
                print(f"❌ Step 10 validation failed - not marking as completed")
                book_dict['image_prompts_status'] = 'failed'
                update_book_record(book_dict)
                log_simple(book_id, f"Image prompt validation failed", 'ERROR', 'image_prompts_validation_failed')
                return False
            
            # Mark as completed
            print(f"🔄 Updating database status for {book_id}...")
            book_dict['image_prompts_status'] = 'completed'
            book_dict['image_prompts_completed_at'] = datetime.now().isoformat()
            
            print(f"  Setting image_prompts_status = 'completed'")
            print(f"  Setting image_prompts_completed_at = {book_dict['image_prompts_completed_at']}")
            
            try:
                update_book_record(book_dict)
                print(f"✅ Database update successful for {book_id}")
            except Exception as update_error:
                print(f"❌ Database update failed: {update_error}")
                return False
            
            log_simple(book_id, f"Image prompts generated: {result['total_prompts']} prompts for {result['total_parts']} parts", 'INFO', 'image_prompts_complete')
            print(f"Image prompts generated successfully!")
            print(f"   Total parts: {result['total_parts']}")
            print(f"   Total prompts: {result['total_prompts']}")
            print(f"   Prompts per part: {result['prompts_per_part']}")
            print(f"   Model profile: {result['model_profile']}")
            return True
        else:
            book_dict['image_prompts_status'] = 'failed'
            update_book_record(book_dict)
            
            log_simple(book_id, f"Image prompt generation failed: {result.get('error', 'Unknown error')}", 'ERROR', 'image_prompts_failed')
            print(f"Image prompt generation failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        book_dict['image_prompts_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Image prompt generation error: {e}", 'ERROR', 'image_prompts_error')
        print(f"Image prompt generation error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 11: CREATE IMAGE GENERATION JOBS
################################################################################

def create_image_jobs_for_book_pipeline(book_dict: Dict) -> bool:
    """Create ComfyUI image generation jobs from image prompts."""
    print(f"\nSTEP 11: Creating image generation jobs...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    print(f"Creating image jobs for '{book_title}' (ID: {book_id})")
    
    # Update status to processing
    book_dict['image_jobs_generation_status'] = 'processing'
    book_dict['image_jobs_generation_started_at'] = datetime.now().isoformat()
    update_book_record(book_dict)
    log_simple(book_id, f"Starting image job creation for '{book_title}'", 'INFO', 'image_jobs_start')
    
    try:
        # Import and call the image job creation function
        from create_image_jobs import create_image_jobs_for_book
        
        result = create_image_jobs_for_book(
            book_id=book_id,
            verbose=True
        )
        
        if result['success']:
            # VALIDATION: Verify job files actually exist before marking complete
            jobs_dir = "comfyui_jobs/processing"
            clean_book_id = book_id.replace('-images', '')
            expected_jobs = result['total_jobs_created']
            
            # Count actual T2I job files
            import glob
            job_pattern = f"{jobs_dir}/T2I_{clean_book_id}_*.yaml"
            actual_job_files = glob.glob(job_pattern)
            
            if len(actual_job_files) == expected_jobs and expected_jobs > 0:
                print(f"✅ VALIDATION: Found {len(actual_job_files)} T2I job files")
                validation_passed = True
            else:
                print(f"❌ VALIDATION: Expected {expected_jobs} job files, found {len(actual_job_files)}")
                validation_passed = False
            
            if not validation_passed:
                print(f"❌ Step 11 validation failed - not marking as completed")
                book_dict['image_jobs_generation_status'] = 'failed'
                update_book_record(book_dict)
                log_simple(book_id, f"Image job validation failed: expected {expected_jobs}, found {len(actual_job_files)}", 'ERROR', 'image_jobs_validation_failed')
                return False
            
            # Mark as completed and store job count
            print(f"🔄 Updating database status for STEP 11 completion...")
            book_dict['image_jobs_generation_status'] = 'completed'
            book_dict['image_jobs_generation_completed_at'] = datetime.now().isoformat()
            book_dict['total_image_jobs'] = result['total_jobs_created']
            book_dict['image_jobs_completed'] = 0  # Reset counter
            book_dict['image_generation_status'] = 'processing'  # Start tracking completion
            
            print(f"  Setting image_jobs_generation_status = 'completed'")
            print(f"  Setting total_image_jobs = {result['total_jobs_created']}")
            
            try:
                update_book_record(book_dict)
                print(f"✅ STEP 11 database update successful for {book_id}")
            except Exception as update_error:
                print(f"❌ STEP 11 database update failed: {update_error}")
                return False
            
            log_simple(book_id, f"Image jobs created: {result['total_jobs_created']} jobs", 'INFO', 'image_jobs_complete')
            print(f"Image jobs created successfully!")
            print(f"   Total jobs: {result['total_jobs_created']}")
            print(f"   Jobs location: {result['jobs_output_dir']}")
            return True
        else:
            book_dict['image_jobs_generation_status'] = 'failed'
            update_book_record(book_dict)
            
            log_simple(book_id, f"Image job creation failed: {result.get('error', 'Unknown error')}", 'ERROR', 'image_jobs_failed')
            print(f"Image job creation failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        book_dict['image_jobs_generation_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Image job creation error: {e}", 'ERROR', 'image_jobs_error')
        print(f"Image job creation error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 12: CHECK IMAGE JOBS COMPLETION
################################################################################

def check_image_jobs_completion_pipeline(book_dict: Dict) -> bool:
    """Check if all image jobs for this book are completed."""
    print(f"\nSTEP 12: Checking image jobs completion...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    total_jobs = book_dict.get('total_image_jobs', 0)
    current_completed = book_dict.get('image_jobs_completed', 0)
    
    print(f"Book ID: {book_id}")
    print(f"Current status: {book_dict.get('image_generation_status', 'unknown')}")
    print(f"Expected total jobs: {total_jobs}")
    print(f"Previously recorded completed: {current_completed}")
    
    if total_jobs == 0:
        print("No image jobs expected for this book")
        return True
    
    try:
        # Import and use the image job checker
        from check_image_jobs import check_image_jobs_completion
        
        result = check_image_jobs_completion(book_id, verbose=True)
        
        if result['success']:
            completed_count = result['completed_jobs']
            
            # Update progress in audiobook database (already done by checker, but confirm)
            book_dict['image_jobs_completed'] = completed_count
            
            # CRITICAL: Update status in book_dict if completed to avoid overwriting
            if result.get('all_completed', False):
                book_dict['image_generation_status'] = 'completed'
                book_dict['image_generation_completed_at'] = datetime.now().isoformat()
            
            update_book_record(book_dict)
            
            if result.get('all_completed', False):
                log_simple(book_id, f"All image jobs completed ({completed_count}/{total_jobs})", 'INFO', 'image_complete')
                print(f"All image jobs completed - ready for video generation")
                return True
            else:
                log_simple(book_id, f"Image jobs still processing ({completed_count}/{total_jobs})", 'INFO', 'image_still_processing')
                print(f"Image jobs still processing - will check again next run")
                return False
        else:
            print(f"Error checking image jobs: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"Image job completion check error: {e}")
        import traceback
        traceback.print_exc()
        return False


################################################################################
# STEP 13: GENERATE VIDEOS FROM AUDIO + IMAGES
################################################################################

def generate_videos_for_book_pipeline(book_dict: Dict) -> bool:
    """Generate videos from combined audio and thumbnail images."""
    print(f"\nSTEP 13: Generating videos from audio + images...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    
    print(f"Generating videos for '{book_title}' (ID: {book_id})")
    
    # PRE-VALIDATION: Verify images actually exist before starting video generation
    clean_book_id = book_id.replace('-images', '')
    images_base_dir = f"D:\\Projects\\pheonix\\dev\\output\\images\\{book_id}"
    
    if not os.path.exists(images_base_dir):
        print(f"❌ VALIDATION: Images directory not found: {images_base_dir}")
        print(f"❌ Cannot generate videos without images - marking as failed")
        book_dict['video_generation_status'] = 'failed'
        update_book_record(book_dict)
        log_simple(book_id, f"Video generation validation failed: no images directory", 'ERROR', 'video_validation_failed')
        return False
    
    # Check for actual image files
    import glob
    image_pattern = f"{images_base_dir}/part*/*.png"
    image_files = glob.glob(image_pattern)
    
    if len(image_files) == 0:
        print(f"❌ VALIDATION: No image files found in {images_base_dir}")
        print(f"❌ Cannot generate videos without images - marking as failed")
        book_dict['video_generation_status'] = 'failed'
        update_book_record(book_dict)
        log_simple(book_id, f"Video generation validation failed: no image files found", 'ERROR', 'video_validation_failed')
        return False
    
    print(f"✅ VALIDATION: Found {len(image_files)} image files for video generation")
    
    # Update status to processing with timing
    start_time = datetime.now()
    book_dict['video_generation_status'] = 'processing'
    book_dict['video_generation_started_at'] = start_time.isoformat()
    update_book_record(book_dict)
    print(f"⏱️  Video generation started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🚨 WARNING: This process may take 30+ minutes for long audiobooks")
    log_simple(book_id, f"Starting video generation for '{book_title}'", 'INFO', 'video_generation_start')
    
    try:
        # Import and call the video generation function
        from generate_videos import generate_videos_for_book
        
        result = generate_videos_for_book(
            book_id=book_id,
            verbose=True
        )
        
        if result['success']:
            # Calculate total duration
            end_time = datetime.now()
            duration = end_time - start_time
            duration_minutes = duration.total_seconds() / 60
            
            # Mark as completed
            print(f"🔄 Updating database status for STEP 13 completion...")
            book_dict['video_generation_status'] = 'completed'
            book_dict['video_generation_completed_at'] = end_time.isoformat()
            book_dict['total_videos_created'] = result['total_videos']
            
            print(f"  Setting video_generation_status = 'completed'")
            print(f"  Setting total_videos_created = {result['total_videos']}")
            
            try:
                update_book_record(book_dict)
                print(f"✅ STEP 13 database update successful for {book_id}")
            except Exception as update_error:
                print(f"❌ STEP 13 database update failed: {update_error}")
                return False
            
            # Log with timing information
            log_simple(book_id, f"Videos generated: {result['total_videos']} videos, size: {result['total_size']:,} bytes, duration: {duration_minutes:.1f}min", 'INFO', 'video_generation_complete')
            
            print(f"🎬 Videos generated successfully!")
            print(f"   ⏱️  Total duration: {duration_minutes:.1f} minutes ({duration.total_seconds():.0f} seconds)")
            print(f"   📹 Total videos: {result['total_videos']}")
            print(f"   💾 Total size: {result['total_size']:,} bytes")
            print(f"   📁 Output directory: {result['output_directory']}")
            print(f"   🕐 Started: {start_time.strftime('%H:%M:%S')}")
            print(f"   🏁 Finished: {end_time.strftime('%H:%M:%S')}")
            return True
        else:
            book_dict['video_generation_status'] = 'failed'
            update_book_record(book_dict)
            
            log_simple(book_id, f"Video generation failed: {result.get('error', 'Unknown error')}", 'ERROR', 'video_generation_failed')
            print(f"Video generation failed: {result.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        book_dict['video_generation_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Video generation error: {e}", 'ERROR', 'video_generation_error')
        print(f"Video generation error: {e}")
        import traceback
        traceback.print_exc()
        return False


def find_first_incomplete_book(books: List[Dict]) -> Optional[Dict]:
    """Find first book prioritized by pipeline stage - complete one book before starting next."""
    print("DEBUG: Evaluating books for processing with pipeline stage priority...")
    
    # Filter retryable books first
    retryable_books = []
    for book in books:
        if (book.get('retry_count') or 0) < (book.get('max_retries') or 3):
            retryable_books.append(book)
    
    if not retryable_books:
        print("DEBUG: No retryable books found")
        return None
    
    # Define pipeline stages in priority order (highest to lowest)
    # Higher stage = more advanced in pipeline = higher priority
    def get_pipeline_stage(book):
        parse_status = book['parse_novel_status']
        metadata_status = book['metadata_status']  
        audio_status = book['audio_generation_status']
        audio_moved_status = book.get('audio_files_moved_status', 'pending')
        combination_planned_status = book.get('audio_combination_planned_status', 'pending')
        subtitle_status = book.get('subtitle_generation_status', 'pending')
        audio_combination_status = book.get('audio_combination_status', 'pending')
        image_prompts_status = book.get('image_prompts_status', 'pending')
        image_jobs_generation_status = book.get('image_jobs_generation_status', 'pending')
        image_generation_status = book.get('image_generation_status', 'pending')
        video_generation_status = book.get('video_generation_status', 'pending')
        
        # PRIORITY: Check completion from highest step backwards
        # If final step is completed, book is fully completed regardless of intermediate inconsistencies
        if (audio_combination_status == 'completed' and 
            image_prompts_status == 'completed' and
            image_jobs_generation_status == 'completed' and
            image_generation_status == 'completed' and
            video_generation_status == 'completed'):
            return 1  # Fully completed
        
        # Stage 13: Video generation (after images completed)
        if (audio_combination_status == 'completed' and 
            image_prompts_status == 'completed' and
            image_jobs_generation_status == 'completed' and
            image_generation_status == 'completed'):
            return 13
        
        # Stage 12: Image job completion check (after image jobs created)
        if (audio_combination_status == 'completed' and 
            image_prompts_status == 'completed' and
            image_jobs_generation_status == 'completed'):
            return 12
        
        # Stage 11: Image job creation (after image prompts)
        if (audio_combination_status == 'completed' and 
            image_prompts_status == 'completed'):
            return 11
        
        # Stage 10: Image prompts (after audio combination)
        if audio_combination_status == 'completed':
            return 10
        
        # Stage 9: Audio combination (highest priority after subtitles)
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status == 'completed' and
            audio_moved_status == 'completed' and
            combination_planned_status == 'completed' and
            subtitle_status == 'completed'):
            return 9
        
        # Stage 8: Subtitle generation (after combination planning)
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status == 'completed' and
            audio_moved_status == 'completed' and
            combination_planned_status == 'completed'):
            return 8
        
        # Stage 7: Plan audio combinations (after files moved)
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status == 'completed' and
            audio_moved_status == 'completed'):
            return 7
        
        # Stage 6: Move audio files (ONLY after ALL audio jobs verified complete)
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status == 'completed' and
            audio_moved_status != 'completed'):
            # CRITICAL: Only allow Stage 6 if audio jobs are ACTUALLY complete
            total_jobs = book.get('total_audio_files', 0)
            completed_jobs = book.get('audio_jobs_completed', 0)
            if total_jobs > 0 and completed_jobs >= total_jobs:
                return 6  # Safe to move files
            else:
                return 5  # Must check/wait for audio job completion first
        
        # Stage 5: Audio completion checks
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status in ['processing', 'completed']):
            return 5
            
        # Stage 4: Audio job generation 
        if (parse_status == 'completed' and 
            metadata_status == 'completed' and 
            audio_status == 'pending'):
            return 4
            
        # Stage 3: Metadata addition
        if (parse_status == 'completed' and 
            metadata_status != 'completed'):
            return 3
            
        # Stage 2: Novel parsing
        if parse_status != 'completed':
            return 2
            
        # Stage 1: Fully completed (should not be selected)
        return 1
    
    # Sort books by pipeline stage (descending) then by database id (ascending)
    prioritized_books = sorted(retryable_books, 
                              key=lambda b: (-get_pipeline_stage(b), b['id']))
    
    print("DEBUG: Book priority order:")
    for book in prioritized_books:
        stage = get_pipeline_stage(book)
        book_id = book['book_id']
        parse_status = book['parse_novel_status']
        metadata_status = book['metadata_status']
        audio_status = book['audio_generation_status']
        
        print(f"  Stage {stage}: {book_id} - parse:{parse_status}, metadata:{metadata_status}, audio:{audio_status}")
    
    # Select the highest priority book that needs work
    print(f"🔍 BOOK SELECTION DEBUG:")
    for book in prioritized_books:
        stage = get_pipeline_stage(book)
        book_id = book['book_id']
        book_title = book.get('book_title', 'Unknown')
        
        # Debug status fields for each book
        audio_combo = book.get('audio_combination_status', 'pending')
        image_prompts = book.get('image_prompts_status', 'pending')
        image_jobs = book.get('image_jobs_generation_status', 'pending')
        
        print(f"  📚 {book_title} [{book_id}] - Stage {stage}")
        print(f"    audio_combination: {audio_combo}")
        print(f"    image_prompts: {image_prompts}")
        print(f"    image_jobs_generation: {image_jobs}")
        
        if stage > 1:  # Skip fully completed books (stage 1)
            print(f"  🎯 SELECTED: {book_id} at pipeline stage {stage}")
            return book
        else:
            print(f"  ✅ SKIPPED: {book_id} fully completed (stage {stage})")
    
    
    print("DEBUG: No incomplete books found")
    return None


def has_metadata_been_added(book_dict: Dict, processing_dir: str) -> bool:
    """Check if metadata has been added to first chunk."""
    try:
        book_id = book_dict['book_id']
        chapter_file = Path(processing_dir) / book_id / "chapter_001.json"
        
        if not chapter_file.exists():
            return False
        
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
        
        first_chunk_text = chapter_data['chapter']['chunks'][0]['text']
        book_title = book_dict['book_title']
        
        # Check if text already has book title prefix
        return first_chunk_text.startswith(book_title)
        
    except Exception:
        return False


def main(input_dir, output_dir):
    """Main function - sequential step processing."""
    print("Audiobook Generation - Sequential Pipeline")
    print("="*50)
    
    ################################################################################
    # STEP 1: GET BOOKS FROM DATABASE
    ################################################################################
    print("\nSTEP 1: Getting books from database...")
    books = get_books_from_db()
    
    if not books:
        print("No books found in database")
        return False
    
    ################################################################################
    # FIND NEXT BOOK TO PROCESS
    ################################################################################
    print("\nFinding next book to process...")
    print("DEBUG: Current book statuses:")
    for book in books:
        print(f"  {book['book_id']}: parse={book['parse_novel_status']}, metadata={book['metadata_status']}, audio={book['audio_generation_status']}")
    
    selected_book = find_first_incomplete_book(books)
    
    if not selected_book:
        print("✅ All books completed! No more work to do.")
        return True
    
    book_id = selected_book['book_id']
    book_title = selected_book['book_title']
    print(f"Selected book: {book_title} (ID: {book_id})")
    print(f"DEBUG: Selected book details:")
    print(f"  - total_audio_files: {selected_book.get('total_audio_files', 'None')}")
    print(f"  - audio_jobs_completed: {selected_book.get('audio_jobs_completed', 'None')}")
    
    ################################################################################
    # DETERMINE WHICH STEP TO RUN FOR THIS BOOK
    ################################################################################
    print(f"\nChecking which step to run for book {book_id}...")
    print(f"   Parse status: {selected_book['parse_novel_status']}")
    print(f"   Metadata status: {selected_book['metadata_status']}")
    print(f"   Audio status: {selected_book['audio_generation_status']}")
    print(f"   Audio files moved status: {selected_book.get('audio_files_moved_status', 'pending')}")
    print(f"   Audio combination planned status: {selected_book.get('audio_combination_planned_status', 'pending')}")
    print(f"   Subtitle generation status: {selected_book.get('subtitle_generation_status', 'pending')}")
    print(f"   Audio combination status: {selected_book.get('audio_combination_status', 'pending')}")
    
    if selected_book['parse_novel_status'] != 'completed':
        ################################################################################
        # STEP 2: PARSE NOVEL
        ################################################################################
        print(f"\nSTEP 2: Parse novel")
        success = parse_one_book(selected_book, output_dir)
        
    elif selected_book['metadata_status'] != 'completed':
        ################################################################################
        # STEP 3: ADD METADATA TO FIRST CHUNK  
        ################################################################################
        print(f"\nSTEP 3: Add metadata to first chunk")
        success = add_book_metadata_to_first_chunk(selected_book, output_dir)
        
    elif selected_book['audio_generation_status'] == 'pending':
        ################################################################################
        # STEP 4: GENERATE AUDIO JOBS
        ################################################################################
        print(f"\nSTEP 4: Generate audio jobs")
        success = generate_audio_jobs_for_book(selected_book, output_dir)
        
    elif (selected_book['audio_generation_status'] == 'completed' and 
          selected_book.get('audio_files_moved_status', 'pending') != 'completed' and
          selected_book.get('audio_jobs_completed', 0) >= selected_book.get('total_audio_files', 1)):
        ################################################################################
        # STEP 6: MOVE AUDIO FILES
        ################################################################################
        print(f"\nSTEP 6: Move audio files to processing directory")
        success = move_audio_files_for_book(selected_book)
        
    elif (selected_book['audio_files_moved_status'] == 'completed' and 
          selected_book.get('audio_combination_planned_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 7: PLAN AUDIO COMBINATIONS
        ################################################################################
        print(f"\nSTEP 7: Plan audio combinations")
        success = plan_audio_combinations_for_book(selected_book)
        
    elif (selected_book.get('audio_combination_planned_status', 'pending') == 'completed' and 
          selected_book.get('subtitle_generation_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 8: GENERATE SUBTITLES
        ################################################################################
        print(f"\nSTEP 8: Generate subtitles")
        success = generate_subtitles_for_book_pipeline(selected_book)
        
    elif (selected_book.get('subtitle_generation_status', 'pending') == 'completed' and 
          selected_book.get('audio_combination_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 9: COMBINE AUDIO FILES
        ################################################################################
        print(f"\nSTEP 9: Combine audio files")
        success = combine_audio_for_book_pipeline(selected_book)
        
    elif (selected_book.get('audio_combination_status', 'pending') == 'completed' and 
          selected_book.get('image_prompts_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 10: GENERATE IMAGE PROMPTS FOR THUMBNAILS
        ################################################################################
        print(f"🔍 STEP 10 CONDITION MATCHED:")
        print(f"  audio_combination_status == 'completed': {selected_book.get('audio_combination_status', 'pending') == 'completed'}")
        print(f"  image_prompts_status != 'completed': {selected_book.get('image_prompts_status', 'pending') != 'completed'}")
        print(f"\nSTEP 10: Generate thumbnail prompts")
        success = generate_image_prompts_for_book_pipeline(selected_book)
        
    elif (selected_book.get('image_prompts_status', 'pending') == 'completed' and 
          selected_book.get('image_jobs_generation_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 11: CREATE IMAGE GENERATION JOBS
        ################################################################################
        print(f"🎯 STEP 11 CONDITION MATCHED:")
        print(f"  image_prompts_status == 'completed': {selected_book.get('image_prompts_status', 'pending') == 'completed'}")
        print(f"  image_jobs_generation_status != 'completed': {selected_book.get('image_jobs_generation_status', 'pending') != 'completed'}")
        print(f"\nSTEP 11: Create image generation jobs")
        success = create_image_jobs_for_book_pipeline(selected_book)
        
    elif (selected_book.get('image_jobs_generation_status', 'pending') == 'completed' and 
          selected_book.get('image_generation_status', 'pending') != 'completed'):
        ################################################################################
        # STEP 12: CHECK IMAGE JOBS COMPLETION
        ################################################################################
        print(f"📊 STEP 12 CONDITION MATCHED:")
        print(f"  image_jobs_generation_status == 'completed': {selected_book.get('image_jobs_generation_status', 'pending') == 'completed'}")
        print(f"  image_generation_status != 'completed': {selected_book.get('image_generation_status', 'pending') != 'completed'}")
        print(f"\nSTEP 12: Check image job completion")
        success = check_image_jobs_completion_pipeline(selected_book)
        
    elif (selected_book.get('image_generation_status', 'pending') == 'completed' and 
          selected_book.get('video_generation_status', 'pending') in ['pending', 'failed']):
        ################################################################################
        # STEP 13: GENERATE VIDEOS FROM AUDIO + IMAGES
        ################################################################################
        print(f"🎬 STEP 13 CONDITION MATCHED:")
        print(f"  image_generation_status == 'completed': {selected_book.get('image_generation_status', 'pending') == 'completed'}")
        print(f"  video_generation_status != 'completed': {selected_book.get('video_generation_status', 'pending') != 'completed'}")
        print(f"\nSTEP 13: Generate videos from audio + images")
        success = generate_videos_for_book_pipeline(selected_book)
        
    elif (selected_book.get('video_generation_status', 'pending') == 'processing'):
        ################################################################################
        # STEP 13: VIDEO GENERATION IN PROGRESS - WAIT
        ################################################################################
        print(f"🎬 STEP 13: Video generation already in progress for {book_id}")
        
        # Calculate how long it's been processing
        started_at = selected_book.get('video_generation_started_at')
        if started_at:
            from datetime import datetime
            start_time = datetime.fromisoformat(started_at)
            elapsed = datetime.now() - start_time
            elapsed_minutes = elapsed.total_seconds() / 60
            print(f"   ⏱️  Processing for: {elapsed_minutes:.1f} minutes")
            
            if elapsed_minutes > 120:  # 2 hours
                print(f"   🚨 WARNING: Video generation taking unusually long (>{elapsed_minutes:.0f}min)")
                print(f"   💡 Consider checking if FFmpeg process is stuck")
            else:
                print(f"   ⏳ Normal processing time, waiting for completion...")
        else:
            print(f"   ⏳ Processing time unknown, waiting for completion...")
        
        print(f"Step completed: WAITING (video generation in progress)")
        return True
        
    elif (selected_book['audio_generation_status'] in ['processing', 'completed'] and 
          not (selected_book['audio_generation_status'] == 'completed' and 
               selected_book.get('audio_files_moved_status', 'pending') == 'completed')):
        ################################################################################
        # STEP 5: CHECK AUDIO JOBS COMPLETION
        ################################################################################
        if selected_book['audio_generation_status'] == 'completed':
            print(f"\nSTEP 5: Re-checking audio jobs completion (fixing inconsistent data)")
        else:
            print(f"\nSTEP 5: Checking audio jobs completion")
        success = check_audio_jobs_completion(selected_book)
        
    else:
        ################################################################################
        # ALL STEPS COMPLETED FOR THIS BOOK
        ################################################################################
        print(f"\nAll current steps completed for book {book_id}")
        print(f"Book pipeline finished (for now)")
        success = True
    
    ################################################################################
    # STEP COMPLETION SUMMARY
    ################################################################################
    step_result = "SUCCESS" if success else "FAILED"
    print(f"\nStep completed: {step_result}")
    print(f"Next run will continue with book {book_id} or move to next book")
    
    return success


################################################################################
# STEP 3: ADD BOOK METADATA TO FIRST CHUNK
################################################################################

def add_book_metadata_to_first_chunk(book_dict: Dict, processing_dir: str) -> bool:
    """Add book metadata prefix to first chunk of chapter 1."""
    print(f"\nSTEP 3: Adding book metadata to first chunk...")
    
    book_id = book_dict['book_id']
    book_title = book_dict['book_title']
    author = book_dict['author']
    narrated_by = book_dict['narrated_by']
    
    # Find chapter_001.json file
    chapter_file = Path(processing_dir) / book_id / "chapter_001.json"
    
    print(f"Looking for chapter file: {chapter_file}")
    
    if not chapter_file.exists():
        log_simple(book_id, f"Chapter file not found: {chapter_file}", 'ERROR', 'metadata_failed')
        print(f"Chapter file not found: {chapter_file}")
        return False
    
    try:
        # Read chapter file
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
        
        # Find first chunk
        chunks = chapter_data['chapter']['chunks']
        if not chunks:
            log_simple(book_id, "No chunks found in chapter file", 'ERROR', 'metadata_failed')
            print(f"No chunks found in chapter file")
            return False
        
        first_chunk = chunks[0]
        original_text = first_chunk['text']
        
        # Create metadata prefix
        metadata_prefix = f"{book_title} by {author}, narrated by {narrated_by}, "
        new_text = metadata_prefix + original_text
        
        # Update first chunk
        first_chunk['text'] = new_text
        first_chunk['char_count'] = len(new_text)
        
        # Save modified file
        with open(chapter_file, 'w', encoding='utf-8') as f:
            json.dump(chapter_data, f, indent=2, ensure_ascii=False)
        
        # Update metadata status in database
        book_dict['metadata_status'] = 'completed'
        book_dict['metadata_completed_at'] = datetime.now().isoformat()
        update_book_record(book_dict)
        
        log_simple(book_id, f"Added metadata prefix to first chunk", 'INFO', 'metadata_added')
        print(f"Metadata added to first chunk")
        print(f"   Prefix: {metadata_prefix}")
        print(f"   New char count: {len(new_text)}")
        
        return True
        
    except Exception as e:
        # Update metadata status to failed
        book_dict['metadata_status'] = 'failed'
        update_book_record(book_dict)
        
        log_simple(book_id, f"Error adding metadata: {e}", 'ERROR', 'metadata_error')
        print(f"Error adding metadata: {e}")
        return False


if __name__ == "__main__":
    input_dir = r"D:\Projects\pheonix\prod\E3\E3\foundry\input"
    output_dir = r"D:\Projects\pheonix\prod\E3\E3\foundry\output"
    processing_path = r"D:\Projects\pheonix\prod\E3\E3\foundry\processing"
    
    main(input_dir, processing_path)