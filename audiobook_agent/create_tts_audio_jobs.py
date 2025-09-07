#!/usr/bin/env python3
"""
Create ComfyUI audio job configurations from parsed TTS novel chunks.
Each chunk becomes a separate YAML job file for TTS processing.
"""

import json
import yaml
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Default paths (can be overridden in function calls)
DEFAULT_VOICE_SAMPLE = "D:\\Projects\\pheonix\\prod\\E3\\E3\\audio_samples\\toireland_shelley_cf_128kb.mp3"


def create_chunk_job(
    book_id: str,
    chapter_index: int,
    chunk: Dict,
    book_metadata: Dict,
    chapter_title: str,
    jobs_output_dir: str,
    finished_audio_dir: str,
    voice_sample: str
) -> str:
    """
    Create a single YAML job configuration for a TTS chunk.
    
    Args:
        book_id: Book identifier (e.g., 'pg159-images')
        chapter_index: Chapter number
        chunk: Chunk dictionary with text and metadata
        book_metadata: Book-level metadata
        chapter_title: Title of the chapter
        output_dir: Output directory for YAML files
    
    Returns:
        Path to created YAML file
    """
    # Create clean book ID (remove -images suffix if present)
    clean_book_id = book_id.replace('-images', '')
    
    # Generate filename: SPEECH_[book]_[index]_ch[chapter]_chunk[chunk_id].yaml
    # Use chapter index as the integer index required by validation
    filename = f"SPEECH_{clean_book_id}_{chapter_index}_ch{chapter_index:03d}_chunk{chunk['chunk_id']:03d}.yaml"
    
    # Create job configuration
    job_config = {
        "job_type": "SPEECH",
        "workflow_id": "T2S_chatterbox_v1",
        "priority": 5,
        "inputs": {
            "10_text": chunk["text"],
            "6_audio": voice_sample,
            "9_filename_prefix": f"speech/{clean_book_id}/ch{chapter_index:03d}/chunk{chunk['chunk_id']:03d}/audio"
        },
        "outputs": {
            "file_path": f"{finished_audio_dir}/{clean_book_id}_ch{chapter_index:03d}_chunk{chunk['chunk_id']:03d}.wav"
        },
        "metadata": {
            "book_title": book_metadata.get("book_title", "Unknown"),
            "book_id": book_id,
            "chapter_index": chapter_index,
            "chapter_title": chapter_title,
            "chunk_id": chunk["chunk_id"],
            "char_count": chunk["char_count"],
            "source_file": book_metadata.get("source_file", ""),
            "creator": "TTS Audio Job Generator",
            "version": "1.0",
            "created_at": datetime.now().isoformat()
        }
    }
    
    # Save YAML file with UTF-8 encoding
    filepath = os.path.join(jobs_output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(job_config, f, default_flow_style=False, allow_unicode=True)
    
    return filepath


def process_book(book_path: Path, jobs_output_dir: str, finished_audio_dir: str, voice_sample: str) -> int:
    """
    Process all chapters in a book directory.
    
    Args:
        book_path: Path to book directory containing chapter JSON files
        output_dir: Output directory for YAML files
    
    Returns:
        Number of job files created
    """
    book_id = book_path.name
    print(f"\nProcessing book: {book_id}")
    print("=" * 60)
    
    # Read metadata if available
    metadata_file = book_path / "metadata.json"
    book_metadata = {}
    if metadata_file.exists():
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata_data = json.load(f)
            book_metadata = {
                "book_title": metadata_data.get("book_title", "Unknown"),
                "source_file": metadata_data.get("source_file", ""),
                "total_chapters": metadata_data.get("total_chapters", 0)
            }
            print(f"Book Title: {book_metadata['book_title']}")
            print(f"Total Chapters: {book_metadata['total_chapters']}")
    
    # Get all chapter files
    chapter_files = sorted(book_path.glob("chapter_*.json"))
    if not chapter_files:
        print(f"No chapter files found in {book_path}")
        return 0
    
    total_jobs = 0
    
    # Process each chapter
    for chapter_file in chapter_files:
        with open(chapter_file, 'r', encoding='utf-8') as f:
            chapter_data = json.load(f)
        
        # Extract chapter info
        chapter_info = chapter_data.get("chapter", {})
        chapter_index = chapter_info.get("index", 0)
        chapter_title = chapter_info.get("title", "")
        chunks = chapter_info.get("chunks", [])
        
        # Use book metadata from chapter file if main metadata not available
        if not book_metadata and "book_metadata" in chapter_data:
            book_metadata = chapter_data["book_metadata"]
        
        print(f"\nChapter {chapter_index}: {chapter_title}")
        print(f"  Chunks to process: {len(chunks)}")
        
        # Create job for each chunk
        for chunk in chunks:
            filepath = create_chunk_job(
                book_id=book_id,
                chapter_index=chapter_index,
                chunk=chunk,
                book_metadata=book_metadata,
                chapter_title=chapter_title,
                jobs_output_dir=jobs_output_dir,
                finished_audio_dir=finished_audio_dir,
                voice_sample=voice_sample
            )
            total_jobs += 1
            
            # Show progress for first and last chunk of each chapter
            if chunk['chunk_id'] == 1 or chunk['chunk_id'] == len(chunks):
                preview = chunk['text'][:50] + "..." if len(chunk['text']) > 50 else chunk['text']
                print(f"    Created job for chunk {chunk['chunk_id']:03d}: {preview}")
    
    print(f"\nTotal jobs created for {book_id}: {total_jobs}")
    return total_jobs


def create_tts_jobs(
    input_dir: str = "output",
    input_book_dir: str = None,
    jobs_output_dir: str = "comfyui_jobs/processing/speech",
    finished_audio_dir: str = "comfyui_jobs/finished/speech",
    voice_sample: str = None,
    book_filter: str = None,
    verbose: bool = True
) -> Dict:
    """
    Create ComfyUI TTS job files from parsed novel chunks.
    
    Args:
        input_dir: Directory containing book folders with chapter JSON files
        input_book_dir: Specific book folder to process (overrides input_dir if provided)
        jobs_output_dir: Directory to save YAML job files
        finished_audio_dir: Directory where finished audio files will be saved
        voice_sample: Path to voice sample file (uses default if None)
        book_filter: Process only this specific book ID (used with input_dir)
        verbose: Print detailed progress information
    
    Returns:
        Dict with processing results and statistics
        
    Examples:
        # Process all books in directory
        result = create_tts_jobs(input_dir="output")
        
        # Process single book folder
        result = create_tts_jobs(input_book_dir="foundry/processing/pg1155")
        
        # Custom settings
        result = create_tts_jobs(
            input_book_dir="foundry/processing/pg1155",
            jobs_output_dir="foundry/output/jobs",
            voice_sample="audio_samples/narrator1.mp3"
        )
    """
    # Use default voice sample if none provided
    if voice_sample is None:
        voice_sample = DEFAULT_VOICE_SAMPLE
    
    # Determine processing mode and get book directories
    if input_book_dir:
        # Single book folder mode
        book_path = Path(input_book_dir)
        if not book_path.exists():
            error_msg = f"Book folder '{input_book_dir}' not found"
            if verbose:
                print(f"Error: {error_msg}")
            return {'error': error_msg, 'success': False}
        
        if not book_path.is_dir():
            error_msg = f"Path '{input_book_dir}' is not a directory"
            if verbose:
                print(f"Error: {error_msg}")
            return {'error': error_msg, 'success': False}
        
        book_dirs = [book_path]
        mode = "single book folder"
        display_input = str(book_path)
    else:
        # Directory mode (existing behavior)
        output_path = Path(input_dir)
        if not output_path.exists():
            error_msg = f"Input directory '{input_dir}' not found"
            if verbose:
                print(f"Error: {error_msg}")
            return {'error': error_msg, 'success': False}
        
        # Find book directories
        if book_filter:
            # Process specific book
            book_dirs = [output_path / book_filter] if (output_path / book_filter).exists() else []
            if not book_dirs:
                error_msg = f"Book '{book_filter}' not found in {input_dir}"
                if verbose:
                    print(f"Error: {error_msg}")
                return {'error': error_msg, 'success': False}
        else:
            # Process all books
            book_dirs = [d for d in output_path.iterdir() if d.is_dir()]
        
        if not book_dirs:
            error_msg = f"No book directories found in {input_dir}"
            if verbose:
                print(f"Error: {error_msg}")
            return {'error': error_msg, 'success': False}
        
        mode = "directory"
        display_input = str(output_path)
    
    if verbose:
        print("TTS Audio Job Generator")
        print("=" * 60)
        print(f"Mode: {mode}")
        print(f"Input: {display_input}")
        print(f"Jobs output: {jobs_output_dir}")
        print(f"Voice sample: {voice_sample}")
        print(f"Timestamp: {datetime.now().isoformat()}")
    
    # Create output directory if it doesn't exist
    os.makedirs(jobs_output_dir, exist_ok=True)
    
    if verbose:
        print(f"\nFound {len(book_dirs)} book(s) to process")
    
    # Process each book
    total_jobs_created = 0
    processed_books = []
    
    for book_path in sorted(book_dirs):
        try:
            jobs_created = process_book(book_path, jobs_output_dir, finished_audio_dir, voice_sample)
            total_jobs_created += jobs_created
            
            processed_books.append({
                'book_id': book_path.name,
                'jobs_created': jobs_created
            })
            
        except Exception as e:
            if verbose:
                print(f"Error processing book {book_path.name}: {e}")
            processed_books.append({
                'book_id': book_path.name,
                'jobs_created': 0,
                'error': str(e)
            })
    # Results
    result = {
        'success': True,
        'total_jobs_created': total_jobs_created,
        'books_processed': len(processed_books),
        'processed_books': processed_books,
        'settings': {
            'mode': mode,
            'input_dir': input_dir if not input_book_dir else None,
            'input_book_dir': input_book_dir,
            'jobs_output_dir': jobs_output_dir,
            'finished_audio_dir': finished_audio_dir,
            'voice_sample': voice_sample,
            'book_filter': book_filter
        }
    }
    
    if verbose:
        print("\n" + "=" * 60)
        print("PROCESSING COMPLETE!")
        print(f"Total job files created: {total_jobs_created}")
        print(f"Job files location: {jobs_output_dir}")
        print(f"Audio outputs will be saved to: {finished_audio_dir}")
        print("=" * 60)
    
    return result


def main(book_filter: Optional[str] = None):
    """CLI wrapper for create_tts_jobs function."""
    # Default paths for CLI usage
    default_input_dir = "output"
    default_jobs_dir = "comfyui_jobs/processing/speech"
    default_finished_dir = "comfyui_jobs/finished/speech"
    input_book_dir = r"D:\Projects\pheonix\prod\E3\E3\output\pg61262-images"
    result = create_tts_jobs(
        input_book_dir=input_book_dir,
        jobs_output_dir=default_jobs_dir,
        finished_audio_dir=default_finished_dir,
        voice_sample=DEFAULT_VOICE_SAMPLE,
        book_filter=book_filter,
        verbose=True
    )
    
    if result['success'] and result['total_jobs_created'] > 0:
        print("\nNext steps:")
        print("1. Ensure ComfyUI agent is running")
        print("2. Agent will automatically process files from:", result['settings']['jobs_output_dir'])
        print("3. Completed audio files will appear in:", result['settings']['finished_audio_dir'])
        print("\nTo process a specific book:")
        print("  python create_tts_audio_jobs.py [book_id]")
        print("  Example: python create_tts_audio_jobs.py pg159-images")
    
    return result['success']


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help', 'help']:
            print("Usage: python create_tts_audio_jobs.py [book_id]")
            print("\nCreate ComfyUI audio job YAML files from parsed TTS chunks.")
            print("\nArguments:")
            print("  book_id  - Optional: Process only this book (e.g., pg159-images)")
            print("             If omitted, processes all books in output directory")
            print("\nExamples:")
            print("  python create_tts_audio_jobs.py           # Process all books")
            print("  python create_tts_audio_jobs.py pg159-images  # Process specific book")
        else:
            # Process specific book
            main(book_filter=sys.argv[1])
    else:
        # Process all books
        main()