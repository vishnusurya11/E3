import os
import glob
import subprocess
from pathlib import Path
import json
from typing import Dict, List

# Configuration
FOLDER_TIMESTAMP = 'pg1155'
INPUT_PATH = rf"D:\Projects\pheonix\dev\output\speech\{FOLDER_TIMESTAMP}"
OUTPUT_PATH = rf".\combined_audio\{FOLDER_TIMESTAMP}"
CHUNK_GAP_MS = 500    # Gap between chunks (was sentence gap)
CHAPTER_GAP_MS = 1000  # Gap between chapters
FFMPEG_PATH = "ffmpeg"  # Try using ffmpeg from PATH

def get_audio_duration(file_path):
    """Get duration of audio file in seconds using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except:
        return 0

def format_timestamp(seconds):
    """Convert seconds to YouTube timestamp format (always HH:MM:SS)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    # Always return HH:MM:SS format for consistency
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def extract_chapter_number(chapter_name):
    """Extract chapter number from folder name (ch001 -> 1)"""
    if chapter_name.startswith('ch') and len(chapter_name) > 2:
        try:
            return int(chapter_name[2:])
        except ValueError:
            pass
    # Fallback for numeric folders
    try:
        return int(chapter_name)
    except ValueError:
        return 0

def extract_chunk_number(chunk_name):
    """Extract chunk number from folder name (chunk001 -> 1)"""
    if chunk_name.startswith('chunk') and len(chunk_name) > 5:
        try:
            return int(chunk_name[5:])
        except ValueError:
            pass
    # Fallback for old sentence format (s0001 -> 1)
    if chunk_name.startswith('s') and len(chunk_name) > 1:
        try:
            return int(chunk_name[1:])
        except ValueError:
            pass
    return 0

def find_audio_file(chunk_folder):
    """Find the audio file in a chunk folder"""
    # Priority order for audio file patterns
    patterns = [
        "audio_*.flac",
        "audio_*.wav", 
        "audio_*.mp3",
        "*.flac",
        "*.wav",
        "*.mp3"
    ]
    
    for pattern in patterns:
        audio_files = list(chunk_folder.glob(pattern))
        if audio_files:
            return audio_files[0]
    
    return None

def create_silence_file(duration_ms, output_path):
    """Create a silence audio file of specified duration"""
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono:d={duration_ms/1000}",
        "-c:a", "mp3",
        "-b:a", "192k",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error creating silence file: {e.stderr}")
        return None

def combine_audio_for_book(
    book_id: str,
    input_path: str,
    output_path: str,
    combination_plan: Dict = None,
    metadata_sources: List[str] = None,
    chunk_gap_ms: int = 500,
    chapter_gap_ms: int = 1000,
    ffmpeg_path: str = "ffmpeg",
    audio_format: str = "mp3",
    audio_bitrate: str = "192k",
    verbose: bool = True,
    **options
) -> Dict:
    """
    Combine audio files for a book into final audiobook file(s).
    
    Args:
        book_id: Book identifier (e.g., 'pg1155')
        input_path: Path to audio files directory with chapter structure
        output_path: Path where combined files will be saved
        combination_plan: Dict from Step 7 with parts/chapters plan (None = single file)
        metadata_sources: List of paths to search for chapter titles
        chunk_gap_ms: Gap between chunks in milliseconds
        chapter_gap_ms: Gap between chapters in milliseconds
        ffmpeg_path: Path to ffmpeg executable
        audio_format: Output audio format (mp3, flac, etc.)
        audio_bitrate: Audio bitrate for compression
        verbose: Whether to print progress messages
        **options: Additional options for future extensibility
        
    Returns:
        Dict with success status, output files, and metadata
    """
    if verbose:
        print(f"Combining audio files for book: {book_id}")
        print("=" * 60)
    
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    # Check if input path exists
    if not input_path.exists():
        error_msg = f"ERROR: Input path does not exist: {input_path}"
        if verbose:
            print(error_msg)
        return {'success': False, 'error': error_msg}
    
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Load chapter titles from various sources
    chapter_titles = {}
    
    # Default metadata sources if not provided
    if metadata_sources is None:
        metadata_sources = [
            f"output/{book_id}-images/metadata.json",  # TTS metadata
            f"./{book_id}.json",  # Old JSON format
            f"foundry/processing/{book_id}/metadata.json"  # New location
        ]
    
    # Try loading chapter titles from metadata sources
    for metadata_path in metadata_sources:
        metadata_path = Path(metadata_path)
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Try new format first (chapters array)
                if 'chapters' in data and isinstance(data['chapters'], list):
                    for chapter in data['chapters']:
                        if 'index' in chapter and 'title' in chapter:
                            chapter_titles[chapter['index']] = chapter['title']
                    if verbose and chapter_titles:
                        print(f"Loaded {len(chapter_titles)} chapter titles from {metadata_path.name}\n")
                    break
                    
                # Try old format (chapter_titles dict)
                elif 'chapter_titles' in data:
                    for key, title in data['chapter_titles'].items():
                        chapter_num = int(key.split('_')[1]) if '_' in key else int(key)
                        chapter_titles[chapter_num] = title
                    if verbose and chapter_titles:
                        print(f"Loaded {len(chapter_titles)} chapter titles from {metadata_path.name}\n")
                    break
                    
            except Exception as e:
                if verbose:
                    print(f"Could not load metadata from {metadata_path}: {e}")
    
    # Create subdirectories
    chapters_path = output_path / "chapters"
    chapters_path.mkdir(exist_ok=True)
    
    # Get all chapter folders (ch001, ch002, etc.)
    chapter_folders = [d for d in input_path.iterdir() if d.is_dir() and d.name.startswith('ch')]
    
    if not chapter_folders:
        # Try numeric folders as fallback
        chapter_folders = [d for d in input_path.iterdir() if d.is_dir() and d.name.isdigit()]
        if chapter_folders and verbose:
            print(f"Using numeric chapter folders (old format)")
    
    if not chapter_folders:
        error_msg = f"No chapter folders found in {input_path}!"
        if verbose:
            print(error_msg)
            print(f"Expected folders like: ch001, ch002, etc.")
        return {'success': False, 'error': error_msg}
    
    # Sort chapters by number
    chapter_folders.sort(key=lambda x: extract_chapter_number(x.name))
    
    if verbose:
        print(f"Found {len(chapter_folders)} chapters\n")
    
    # Determine which chapters to process and how to group them
    parts_to_create = []
    
    if combination_plan and 'combinations' in combination_plan:
        # Use Step 7 combination plan
        if verbose:
            print(f"Using combination plan with {len(combination_plan['combinations'])} parts")
        
        for combo in combination_plan['combinations']:
            part_num = combo['part']
            chapters_in_part = combo['chapters']
            output_filename = combo.get('output_filename', f"{book_id}_part{part_num}.{audio_format}")
            
            parts_to_create.append({
                'part_number': part_num,
                'chapters': chapters_in_part,
                'output_filename': output_filename,
                'description': f"Part {part_num} (Chapters {combo.get('chapter_range', 'N/A')})"
            })
    else:
        # Default: All chapters in one file
        all_chapter_nums = [extract_chapter_number(cf.name) for cf in chapter_folders]
        parts_to_create.append({
            'part_number': 1,
            'chapters': all_chapter_nums,
            'output_filename': f"{book_id}_full_book.{audio_format}",
            'description': "Complete book (all chapters)"
        })
    
    if verbose:
        print(f"Will create {len(parts_to_create)} audio files:")
        for part in parts_to_create:
            print(f"  {part['description']} -> {part['output_filename']}")
        print()
    
    # Process each chapter first (create individual chapter files)
    chapter_files = []
    chapter_info = []
    
    for chapter_folder in chapter_folders:
        chapter_num = extract_chapter_number(chapter_folder.name)
        chapter_title = chapter_titles.get(chapter_num, f"Chapter {chapter_num}")
        
        if verbose:
            print(f"Processing Chapter {chapter_num}: {chapter_title}")
        
        # Get all chunk folders
        chunk_folders = [d for d in chapter_folder.iterdir() if d.is_dir() and d.name.startswith('chunk')]
        
        if not chunk_folders:
            # Try sentence folders as fallback (old format)
            chunk_folders = [d for d in chapter_folder.iterdir() if d.is_dir() and d.name.startswith('s')]
            if chunk_folders and verbose:
                print(f"  Using sentence folders (old format)")
        
        if not chunk_folders:
            if verbose:
                print(f"  WARNING: No chunks found in {chapter_folder.name}")
            continue
        
        # Sort chunks by number
        chunk_folders.sort(key=lambda x: extract_chunk_number(x.name))
        
        if verbose:
            print(f"  Found {len(chunk_folders)} chunks")
        
        # Create list file for this chapter
        chapter_list_file = output_path / f"chapter_{chapter_num:03d}_list.txt"
        
        chunks_found = 0
        with open(chapter_list_file, 'w') as f:
            for chunk_folder in chunk_folders:
                audio_file = find_audio_file(chunk_folder)
                
                if audio_file:
                    # Use absolute path and convert backslashes to forward slashes for ffmpeg
                    abs_path = audio_file.resolve()
                    f.write(f"file '{str(abs_path).replace(chr(92), '/')}'\n")
                    chunks_found += 1
                    if verbose and (chunks_found <= 3 or chunks_found == len(chunk_folders)):
                        print(f"    Chunk {extract_chunk_number(chunk_folder.name):03d}: {audio_file.name}")
                else:
                    if verbose:
                        print(f"    WARNING: No audio in {chunk_folder.name}")
        
        if verbose and chunks_found > 3:
            print(f"    ... and {chunks_found - 3} more chunks")
        
        if chunks_found == 0:
            if verbose:
                print(f"  ERROR: No audio files found for chapter {chapter_num}")
            continue
        
        # Create chapter audio file
        chapter_output = chapters_path / f"chapter_{chapter_num:03d}.{audio_format}"
        
        cmd = [
            ffmpeg_path, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(chapter_list_file),
            "-c:a", audio_format,
            "-b:a", audio_bitrate,
            str(chapter_output)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if verbose:
                print(f"  ✓ Created: {chapter_output.name}")
            
            # Get duration of this chapter
            duration = get_audio_duration(chapter_output)
            if verbose:
                print(f"  Duration: {format_timestamp(duration)}\n")
            
            chapter_info.append({
                'number': chapter_num,
                'title': chapter_title,
                'file': chapter_output,
                'duration': duration
            })
            
            chapter_files.append(chapter_output)
            
        except subprocess.CalledProcessError as e:
            error_msg = f"ERROR creating chapter {chapter_num}: {e.stderr}"
            if verbose:
                print(f"  {error_msg}")
            return {'success': False, 'error': error_msg}
        except FileNotFoundError:
            error_msg = f"ERROR: ffmpeg not found at {ffmpeg_path}"
            if verbose:
                print(error_msg)
                print("Please install ffmpeg or update the ffmpeg_path parameter")
            return {'success': False, 'error': error_msg}
    
    # Create final combined files based on parts plan
    if chapter_files:
        final_files_created = []
        
        for part_info in parts_to_create:
            part_num = part_info['part_number']
            chapters_in_part = part_info['chapters']
            output_filename = part_info['output_filename']
            
            if verbose:
                print("\n" + "=" * 60)
                print(f"Creating {part_info['description']}...")
            
            # Filter chapter files for this part
            part_chapter_files = [
                info for info in chapter_info 
                if info['number'] in chapters_in_part
            ]
            
            if verbose:
                print(f"  Chapters in this part: {chapters_in_part}")
                print(f"  Found chapter files: {len(part_chapter_files)}")
                for info in part_chapter_files:
                    print(f"    Chapter {info['number']}: {info['duration']:.1f}s ({info['duration']/60:.1f}min)")
            
            if not part_chapter_files:
                if verbose:
                    print(f"  WARNING: No chapters found for part {part_num}")
                continue
            
            # Create list file for this part
            part_list_file = output_path / f"part_{part_num}_list.txt"
            
            with open(part_list_file, 'w') as f:
                for chapter_info_item in part_chapter_files:
                    # Use absolute path for the chapter files
                    abs_path = chapter_info_item['file'].resolve()
                    f.write(f"file '{str(abs_path).replace(chr(92), '/')}'\n")
            
            # Create final combined audio for this part
            final_output = output_path / output_filename
            
            cmd = [
                ffmpeg_path, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(part_list_file),
                "-c", "copy",  # Just copy, don't re-encode
                str(final_output)
            ]
            
            # Verify all chapter files exist before combining
            missing_files = []
            for chapter_info_item in part_chapter_files:
                if not chapter_info_item['file'].exists():
                    missing_files.append(str(chapter_info_item['file']))
            
            if missing_files:
                error_msg = f"Missing chapter files: {missing_files}"
                if verbose:
                    print(f"  ERROR: {error_msg}")
                return {'success': False, 'error': error_msg}
            
            if verbose:
                print(f"  All {len(part_chapter_files)} chapter files verified to exist")
                print(f"  Running ffmpeg command...")
                print(f"  Input list: {part_list_file}")
                print(f"  Output file: {final_output}")
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode != 0:
                    error_msg = f"FFmpeg failed with return code {result.returncode}"
                    if result.stderr:
                        error_msg += f"\nSTDERR: {result.stderr[-1000:]}"  # Last 1000 chars
                    if result.stdout:
                        error_msg += f"\nSTDOUT: {result.stdout[-500:]}"   # Last 500 chars
                    
                    if verbose:
                        print(f"  FFmpeg Error: {error_msg}")
                    
                    raise subprocess.CalledProcessError(result.returncode, cmd, error_msg)
                
                # Verify output file was created and has reasonable size
                if not final_output.exists():
                    error_msg = "FFmpeg completed but output file not created"
                    if verbose:
                        print(f"  ERROR: {error_msg}")
                    return {'success': False, 'error': error_msg}
                
                output_size = final_output.stat().st_size
                if output_size < 1024 * 1024:  # Less than 1MB is suspicious
                    error_msg = f"Output file too small: {output_size} bytes"
                    if verbose:
                        print(f"  ERROR: {error_msg}")
                    return {'success': False, 'error': error_msg}
                
                if verbose:
                    print(f"✓ Success! {part_info['description']} saved to: {final_output}")
                    print(f"  Output size: {output_size/1024/1024:.1f} MB")
                
                # Generate YouTube timestamps for this part
                timestamps_file = output_path / f"youtube_timestamps_part{part_num}.txt"
                json_file = output_path / f"chapter_info_part{part_num}.json"
                
                current_time = 0
                timestamps = []
                
                if verbose:
                    print(f"\nYouTube Chapter Timestamps for Part {part_num}:")
                    print("-" * 30)
                
                with open(timestamps_file, 'w', encoding='utf-8') as f:
                    f.write(f"=== YouTube Chapter Timestamps for {book_id} Part {part_num} ===\n\n")
                    
                    for info in part_chapter_files:
                        timestamp = format_timestamp(current_time)
                        chapter_name = info['title']
                        
                        # Display and write timestamp
                        timestamp_line = f"{timestamp} - {chapter_name}"
                        if verbose:
                            print(timestamp_line)
                        f.write(timestamp_line + "\n")
                        
                        # Save for JSON
                        timestamps.append({
                            'chapter': info['number'],
                            'name': chapter_name,
                            'timestamp': timestamp,
                            'start_seconds': current_time,
                            'duration_seconds': info['duration']
                        })
                        
                        current_time += info['duration']
                    
                    # Total duration
                    total_line = f"\nTotal Duration: {format_timestamp(current_time)}"
                    if verbose:
                        print(total_line)
                    f.write(total_line + "\n")
                
                # Save JSON with detailed info
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'book_id': book_id,
                        'part': part_num,
                        'chapters': timestamps,
                        'total_duration_seconds': current_time,
                        'total_duration_formatted': format_timestamp(current_time),
                        'chapter_count': len(part_chapter_files)
                    }, f, indent=2)
                
                final_files_created.append({
                    'part': part_num,
                    'file': final_output,
                    'duration': current_time,
                    'chapters': len(part_chapter_files),
                    'timestamps_file': timestamps_file,
                    'json_file': json_file
                })
                
            except subprocess.CalledProcessError as e:
                error_msg = f"ERROR creating part {part_num}: {e.stderr}"
                if verbose:
                    print(error_msg)
                return {'success': False, 'error': error_msg}
        
        if verbose:
            print("\n" + "=" * 60)
            print("Summary:")
            print(f"  • Created {len(chapter_files)} chapter audio files")
            print(f"  • Combined into {len(final_files_created)} final part(s)")
            for final_file in final_files_created:
                print(f"    - Part {final_file['part']}: {final_file['file'].name} "
                      f"({final_file['chapters']} chapters, {format_timestamp(final_file['duration'])})")
            print("=" * 60)
        
        return {
            'success': True,
            'parts_created': len(final_files_created),
            'final_files': final_files_created,
            'chapter_files': chapter_files,
            'total_chapters_processed': len(chapter_files)
        }
        
    else:
        error_msg = "No chapters were successfully processed!"
        if verbose:
            print(f"\n{error_msg}")
        return {'success': False, 'error': error_msg}


def main():
    """Original main function using hardcoded values for backward compatibility"""
    result = combine_audio_for_book(
        book_id=FOLDER_TIMESTAMP,
        input_path=INPUT_PATH,
        output_path=OUTPUT_PATH,
        combination_plan=None,  # Use original single-file logic
        metadata_sources=None,  # Use default sources
        chunk_gap_ms=CHUNK_GAP_MS,
        chapter_gap_ms=CHAPTER_GAP_MS,
        ffmpeg_path=FFMPEG_PATH,
        audio_format="mp3",
        audio_bitrate="192k",
        verbose=True
    )
    
    if not result['success']:
        print(f"ERROR: {result.get('error', 'Unknown error')}")
    
    return result['success']

if __name__ == "__main__":
    main()