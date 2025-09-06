#!/usr/bin/env python3
"""
Check image generation job completion status.
Similar to audio job checking but for image generation jobs.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


def check_image_jobs_completion(
    book_id: str,
    verbose: bool = True
) -> Dict:
    """
    Check completion status of all image generation jobs for a book.
    Checks actual ComfyUI output directory for generated image files.
    
    Args:
        book_id: Book identifier
        verbose: Enable detailed output
    
    Returns:
        Dict with completion status and statistics
    """
    if verbose:
        print(f"\nChecking image job completion for book: {book_id}")
        print("=" * 60)
    
    # Connect to ComfyUI agent database to check job status
    comfyui_db_path = Path("database/comfyui_agent.db")
    audiobook_db_path = Path("database/audiobook.db")
    
    if not comfyui_db_path.exists():
        return {
            'success': False,
            'error': f'ComfyUI database not found: {comfyui_db_path}'
        }
    
    if not audiobook_db_path.exists():
        return {
            'success': False,
            'error': f'Audiobook database not found: {audiobook_db_path}'
        }
    
    try:
        # Get expected job count from audiobook database
        with sqlite3.connect(audiobook_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_image_jobs, image_jobs_completed, image_jobs_generation_status
                FROM audiobook_processing 
                WHERE book_id = ?
            """, (book_id,))
            
            result = cursor.fetchone()
            if not result:
                return {
                    'success': False,
                    'error': f'Book not found in database: {book_id}'
                }
            
            expected_jobs, current_completed, generation_status = result
            
        if verbose:
            print(f"Expected image jobs: {expected_jobs}")
            print(f"Previously recorded completed: {current_completed}")
            print(f"Job generation status: {generation_status}")
        
        if generation_status != 'completed':
            return {
                'success': False,
                'error': f'Image job generation not completed for book {book_id}'
            }
        
        if expected_jobs == 0:
            return {
                'success': False,
                'error': f'No image jobs expected for book {book_id}'
            }
        
        # First check if image files actually exist in ComfyUI output directory
        clean_book_id = book_id.replace('-images', '')
        
        # Get book parts from metadata to check each part's output
        metadata_file = Path(f"foundry/processing/{book_id}/metadata.json")
        if not metadata_file.exists():
            return {
                'success': False,
                'error': f'Metadata file not found: {metadata_file}'
            }
        
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        image_prompts = metadata.get('image_prompts', {})
        parts = image_prompts.get('parts', [])
        
        total_expected_files = 0
        total_found_files = 0
        
        if verbose:
            print(f"Checking actual image files in ComfyUI output directories:")
        
        for part_data in parts:
            part_number = part_data['part']
            expected_images = len(part_data.get('prompts', []))
            
            # ComfyUI output directory (dynamic per book/part)
            output_dir = Path(f"D:\\Projects\\pheonix\\dev\\output\\images\\{book_id}\\part{part_number}")
            
            if output_dir.exists():
                # Count actual image files
                image_files = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
                found_images = len(image_files)
                
                if verbose:
                    print(f"  Part {part_number}: {found_images}/{expected_images} images in {output_dir}")
                    if found_images > 0:
                        for img in image_files[:2]:  # Show first 2 files
                            print(f"    - {img.name}")
                
                total_expected_files += expected_images
                total_found_files += found_images
            else:
                if verbose:
                    print(f"  Part {part_number}: Output directory not found: {output_dir}")
                total_expected_files += expected_images
        
        if verbose:
            print(f"\nFile count summary:")
            print(f"  Expected: {total_expected_files} image files")
            print(f"  Found: {total_found_files} image files")
            print(f"  Complete: {total_found_files >= total_expected_files}")
        
        # If all files exist, mark as completed immediately
        if total_found_files >= total_expected_files and total_expected_files > 0:
            if verbose:
                print(f"✅ All image files exist - marking as completed")
            
            # Update audiobook database directly
            with sqlite3.connect(audiobook_db_path) as conn:
                cursor = conn.cursor()
                completion_time = datetime.now().isoformat()
                
                cursor.execute("""
                    UPDATE audiobook_processing 
                    SET image_generation_status = 'completed',
                        image_generation_completed_at = ?,
                        image_jobs_completed = ?,
                        updated_at = ?
                    WHERE book_id = ?
                """, (completion_time, total_found_files, completion_time, book_id))
                
                conn.commit()  # CRITICAL: Commit the transaction
                
                return {
                    'success': True,
                    'all_completed': True,
                    'total_jobs': total_expected_files,
                    'completed_jobs': total_found_files,
                    'completion_rate': 1.0,
                    'method': 'file_check'
                }
        
        # If files don't exist, check ComfyUI database for job status
        clean_book_id = book_id.replace('-images', '')
        with sqlite3.connect(comfyui_db_path) as conn:
            cursor = conn.cursor()
            
            # Count completed image jobs for this book
            cursor.execute("""
                SELECT COUNT(*) FROM jobs 
                WHERE job_type = 'T2I' 
                AND workflow_id = 'image_qwen_image'
                AND (
                    json_extract(metadata, '$.book_id') = ? 
                    OR json_extract(metadata, '$.book_id') = ?
                    OR config_name LIKE ?
                )
                AND status = 'done'
            """, (book_id, clean_book_id, f"T2I_{clean_book_id}_%"))
            
            completed_count = cursor.fetchone()[0]
            
            # Count total image jobs for this book
            cursor.execute("""
                SELECT COUNT(*) FROM jobs 
                WHERE job_type = 'T2I' 
                AND workflow_id = 'image_qwen_image'
                AND (
                    json_extract(metadata, '$.book_id') = ? 
                    OR json_extract(metadata, '$.book_id') = ?
                    OR config_name LIKE ?
                )
            """, (book_id, clean_book_id, f"T2I_{clean_book_id}_%"))
            
            total_count = cursor.fetchone()[0]
        
        if verbose:
            print(f"ComfyUI database check:")
            print(f"  Total image jobs: {total_count}")
            print(f"  Completed jobs: {completed_count}")
        
        # Update audiobook database with current status
        with sqlite3.connect(audiobook_db_path) as conn:
            cursor = conn.cursor()
            
            # Update completion count
            cursor.execute("""
                UPDATE audiobook_processing 
                SET image_jobs_completed = ?, updated_at = ?
                WHERE book_id = ?
            """, (completed_count, datetime.now().isoformat(), book_id))
            
            # Check if all jobs are complete
            if completed_count >= expected_jobs and total_count >= expected_jobs:
                # Mark image generation as completed
                cursor.execute("""
                    UPDATE audiobook_processing 
                    SET image_generation_status = 'completed',
                        image_generation_completed_at = ?,
                        updated_at = ?
                    WHERE book_id = ?
                """, (datetime.now().isoformat(), datetime.now().isoformat(), book_id))
                
                if verbose:
                    print(f"✓ All image jobs completed! Marked as 'completed'")
                
                return {
                    'success': True,
                    'all_completed': True,
                    'total_jobs': expected_jobs,
                    'completed_jobs': completed_count,
                    'completion_rate': completed_count / expected_jobs if expected_jobs > 0 else 0
                }
            else:
                # Still processing
                cursor.execute("""
                    UPDATE audiobook_processing 
                    SET image_generation_status = 'processing',
                        updated_at = ?
                    WHERE book_id = ?
                """, (datetime.now().isoformat(), book_id))
                
                if verbose:
                    print(f"⏳ Image jobs still processing: {completed_count}/{expected_jobs}")
                
                return {
                    'success': True,
                    'all_completed': False,
                    'total_jobs': expected_jobs,
                    'completed_jobs': completed_count,
                    'completion_rate': completed_count / expected_jobs if expected_jobs > 0 else 0
                }
        
    except Exception as e:
        if verbose:
            print(f"Error checking image job completion: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def check_all_image_jobs(verbose: bool = True) -> Dict:
    """
    Check image job completion for all books with pending image generation.
    
    Args:
        verbose: Enable detailed output
    
    Returns:
        Dict with overall completion status
    """
    audiobook_db_path = Path("database/audiobook.db")
    
    if not audiobook_db_path.exists():
        return {
            'success': False,
            'error': f'Audiobook database not found: {audiobook_db_path}'
        }
    
    try:
        with sqlite3.connect(audiobook_db_path) as conn:
            cursor = conn.cursor()
            
            # Get books with image jobs in progress
            cursor.execute("""
                SELECT book_id FROM audiobook_processing 
                WHERE image_jobs_generation_status = 'completed'
                AND image_generation_status IN ('pending', 'processing')
                ORDER BY id
            """)
            
            books_to_check = [row[0] for row in cursor.fetchall()]
    
        if not books_to_check:
            if verbose:
                print("No books with pending image generation found")
            return {'success': True, 'books_checked': 0}
        
        results = []
        for book_id in books_to_check:
            if verbose:
                print(f"\n" + "="*60)
            result = check_image_jobs_completion(book_id, verbose)
            results.append({'book_id': book_id, 'result': result})
        
        completed_books = len([r for r in results if r['result'].get('all_completed', False)])
        
        if verbose:
            print(f"\n" + "="*60)
            print(f"Image job check summary:")
            print(f"  Books checked: {len(books_to_check)}")
            print(f"  Books completed: {completed_books}")
        
        return {
            'success': True,
            'books_checked': len(books_to_check),
            'books_completed': completed_books,
            'results': results
        }
        
    except Exception as e:
        if verbose:
            print(f"Error checking image jobs: {e}")
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        book_id = sys.argv[1]
        result = check_image_jobs_completion(book_id)
        if not result['success']:
            print(f"Error: {result['error']}")
            sys.exit(1)
    else:
        result = check_all_image_jobs()
        if not result['success']:
            print(f"Error: {result['error']}")
            sys.exit(1)