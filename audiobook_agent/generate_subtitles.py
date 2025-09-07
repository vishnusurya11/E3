#!/usr/bin/env python3
"""
Generate SRT subtitle files from TTS chunks and audio files.
Matches text chunks with their corresponding audio files to create accurate subtitles.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
import re

# Configuration
BOOK_ID = 'pg61262'  # Change this for different books
AUDIO_PATH = rf"D:\Projects\pheonix\dev\output\speech\{BOOK_ID}"
TEXT_PATH = rf"output\{BOOK_ID}-images"
OUTPUT_PATH = rf"subtitles\{BOOK_ID}"

# SRT timing format
SRT_TIME_FORMAT = "{:02d}:{:02d}:{:02d},{:03d}"


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    
    return SRT_TIME_FORMAT.format(hours, minutes, secs, millis)


def get_audio_duration(audio_file: Path) -> float:
    """Get duration of audio file in seconds using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_file)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        print(f"Warning: Could not get duration for {audio_file}")
        return 3.0  # Default duration if unable to read


def find_audio_file(chunk_folder: Path) -> Path:
    """Find the audio file in a chunk folder"""
    patterns = ["audio_*.flac", "audio_*.wav", "audio_*.mp3", "*.flac", "*.wav", "*.mp3"]
    
    for pattern in patterns:
        audio_files = list(chunk_folder.glob(pattern))
        if audio_files:
            return audio_files[0]
    
    return None


def load_chapter_text(chapter_file: Path) -> Dict:
    """Load chapter text data from JSON file"""
    with open(chapter_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def clean_text_for_subtitle(text: str) -> str:
    """Clean text for subtitle display"""
    # Remove excessive whitespace
    text = ' '.join(text.split())
    
    # Break very long lines (YouTube recommends max 2 lines, ~40 chars per line)
    max_length = 80
    if len(text) > max_length:
        # Try to break at punctuation or conjunctions
        break_points = ['. ', '? ', '! ', ', ', '; ', ' and ', ' but ', ' or ']
        best_break = -1
        target = len(text) // 2
        
        for bp in break_points:
            pos = text.find(bp, max(0, target - 20), min(len(text), target + 20))
            if pos != -1:
                best_break = pos + len(bp) - 1
                break
        
        if best_break > 0:
            text = text[:best_break + 1] + '\n' + text[best_break + 1:].strip()
        else:
            # Force break at word boundary near middle
            words = text.split()
            mid = len(words) // 2
            text = ' '.join(words[:mid]) + '\n' + ' '.join(words[mid:])
    
    return text


def split_text_into_segments(text: str, audio_duration: float) -> List[Tuple[str, float]]:
    """
    Split text into subtitle segments with appropriate timing.
    Returns list of (text, duration) tuples.
    """
    import re
    
    # Target 3-5 seconds per subtitle, with 60-100 chars ideal
    MIN_DURATION = 2.0
    MAX_DURATION = 6.0
    MIN_CHARS = 30  # Don't create tiny segments
    IDEAL_CHARS_PER_SUBTITLE = 80
    MAX_CHARS = 120  # Maximum chars before forcing a split
    
    # Calculate approximate reading speed
    total_chars = len(text)
    if total_chars == 0:
        return [(text, audio_duration)]
    
    chars_per_second = total_chars / audio_duration
    
    # First, try to split into sentences
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # If no good sentence breaks or very long sentences, split more aggressively
    if not sentences or any(len(s) > MAX_CHARS * 2 for s in sentences):
        # Split by various punctuation marks
        parts = re.split(r'(?<=[.!?,;:])\s+', text)
        sentences = []
        current = ""
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            # If current is empty, start new segment
            if not current:
                current = part
            # If adding this part would exceed max, save current and start new
            elif len(current) + len(part) + 1 > MAX_CHARS:
                sentences.append(current)
                current = part
            # If current is too small, keep adding
            elif len(current) < MIN_CHARS:
                current = current + " " + part
            # Otherwise add if it won't make it too long
            elif len(current) + len(part) + 1 <= IDEAL_CHARS_PER_SUBTITLE:
                current = current + " " + part
            else:
                sentences.append(current)
                current = part
        
        if current:
            sentences.append(current)
    
    # Now group sentences into subtitle segments
    segments = []
    current_segment = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # If sentence alone is too long, it needs to be its own segment(s)
        if len(sentence) > MAX_CHARS:
            # Save any current segment first
            if current_segment:
                segments.append(current_segment)
                current_segment = ""
            
            # Split long sentence at clause boundaries if possible
            words = sentence.split()
            temp_segment = ""
            for word in words:
                if len(temp_segment) + len(word) + 1 > IDEAL_CHARS_PER_SUBTITLE:
                    if temp_segment:
                        segments.append(temp_segment)
                    temp_segment = word
                else:
                    temp_segment = (temp_segment + " " + word).strip()
            if temp_segment:
                segments.append(temp_segment)
        
        # If current segment is empty, start new one
        elif not current_segment:
            current_segment = sentence
        
        # If adding would exceed ideal length, save current and start new
        elif len(current_segment) + len(sentence) + 1 > IDEAL_CHARS_PER_SUBTITLE:
            segments.append(current_segment)
            current_segment = sentence
        
        # Otherwise, add to current segment
        else:
            current_segment = current_segment + " " + sentence
    
    # Don't forget the last segment
    if current_segment:
        segments.append(current_segment)
    
    # Merge tiny segments with neighbors
    merged_segments = []
    for segment in segments:
        if merged_segments and len(segment) < MIN_CHARS and len(merged_segments[-1]) + len(segment) + 1 <= MAX_CHARS:
            merged_segments[-1] = merged_segments[-1] + " " + segment
        else:
            merged_segments.append(segment)
    
    segments = merged_segments if merged_segments else [text]
    
    # Calculate duration for each segment based on character count
    segment_timings = []
    for segment in segments:
        # Calculate duration based on character count and reading speed
        duration = len(segment) / chars_per_second
        
        # Apply min/max limits
        duration = max(MIN_DURATION, min(MAX_DURATION, duration))
        
        segment_timings.append((segment, duration))
    
    # Adjust timings to exactly match total audio duration
    total_calculated = sum(d for _, d in segment_timings)
    if total_calculated > 0 and abs(total_calculated - audio_duration) > 0.1:
        scale_factor = audio_duration / total_calculated
        segment_timings = [(text, duration * scale_factor) for text, duration in segment_timings]
    
    return segment_timings


def generate_chapter_subtitles(
    chapter_num: int,
    chapter_folder: Path,
    chapter_text_data: Dict
) -> Tuple[List[Dict], float]:
    """
    Generate subtitle entries for a single chapter.
    Returns list of subtitle entries and total duration.
    """
    subtitles = []
    
    # Get chapter info from text data
    chapter_info = chapter_text_data.get('chapter', {})
    chunks = chapter_info.get('chunks', [])
    
    # Get all chunk folders from audio directory
    chunk_folders = sorted(
        [d for d in chapter_folder.iterdir() if d.is_dir() and d.name.startswith('chunk')],
        key=lambda x: int(x.name[5:]) if len(x.name) > 5 and x.name[5:].isdigit() else 0
    )
    
    if len(chunk_folders) != len(chunks):
        print(f"  Warning: Mismatch - {len(chunk_folders)} audio chunks vs {len(chunks)} text chunks")
    
    current_time = 0.0
    
    # Process each chunk
    for i, chunk_folder in enumerate(chunk_folders):
        # Find corresponding text chunk
        if i < len(chunks):
            text = chunks[i].get('text', '')
        else:
            print(f"  Warning: No text for chunk {i + 1}")
            text = "[No text available]"
        
        # Find audio file
        audio_file = find_audio_file(chunk_folder)
        if not audio_file:
            print(f"  Warning: No audio file in {chunk_folder.name}")
            continue
        
        # Get audio duration
        duration = get_audio_duration(audio_file)
        
        # Split text into multiple subtitle segments with proper timing
        segments = split_text_into_segments(text, duration)
        
        # Create subtitle entries for each segment
        segment_start = current_time
        for segment_text, segment_duration in segments:
            # Clean and format the segment text
            formatted_text = clean_text_for_subtitle(segment_text)
            
            subtitle_entry = {
                'index': len(subtitles) + 1,
                'start': segment_start,
                'end': segment_start + segment_duration,
                'text': formatted_text,
                'chunk_id': i + 1
            }
            
            subtitles.append(subtitle_entry)
            segment_start += segment_duration
        
        current_time += duration
    
    return subtitles, current_time


def write_srt_file(subtitles: List[Dict], output_file: Path, start_offset: float = 0):
    """Write subtitles to SRT file"""
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, sub in enumerate(subtitles, 1):
            # Adjust times with offset
            start_time = format_srt_time(sub['start'] + start_offset)
            end_time = format_srt_time(sub['end'] + start_offset)
            
            # Write SRT entry
            f.write(f"{i}\n")
            f.write(f"{start_time} --> {end_time}\n")
            f.write(f"{sub['text']}\n")
            f.write("\n")  # Empty line between entries


def generate_subtitles_for_book(
    book_id: str,
    audio_path: str,
    text_path: str, 
    output_path: str,
    chapters_to_include: List[int] = None,
    copy_to_combined_audio: bool = True,
    verbose: bool = True,
    **options
) -> Dict:
    """
    Generate SRT subtitle files for a book.
    
    Args:
        book_id: Book identifier (e.g., 'pg1155')
        audio_path: Path to audio files directory
        text_path: Path to text/chapter files directory  
        output_path: Path where subtitle files will be saved
        chapters_to_include: List of chapter numbers to include (None = all chapters)
        copy_to_combined_audio: Whether to copy full SRT to combined_audio folder
        verbose: Whether to print progress messages
        **options: Additional options for future extensibility
        
    Returns:
        Dict with success status, file paths, and metadata
    """
    if verbose:
        print(f"Subtitle Generator for: {book_id}")
        print("=" * 60)
    
    audio_path = Path(audio_path)
    text_path = Path(text_path)
    output_path = Path(output_path)
    
    # Check paths
    if not audio_path.exists():
        error_msg = f"ERROR: Audio path not found: {audio_path}"
        if verbose:
            print(error_msg)
        return {'success': False, 'error': error_msg}
    
    if not text_path.exists():
        error_msg = f"ERROR: Text path not found: {text_path}"
        if verbose:
            print(error_msg)
        return {'success': False, 'error': error_msg}
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    chapters_srt_path = output_path / "chapters"
    chapters_srt_path.mkdir(exist_ok=True)
    
    # Get all chapter folders from audio
    chapter_folders = sorted(
        [d for d in audio_path.iterdir() if d.is_dir() and d.name.startswith('ch')],
        key=lambda x: int(x.name[2:]) if len(x.name) > 2 and x.name[2:].isdigit() else 0
    )
    
    if not chapter_folders:
        error_msg = "No chapter folders found in audio path!"
        if verbose:
            print(error_msg)
        return {'success': False, 'error': error_msg}
    
    # Filter chapters if specified
    if chapters_to_include:
        chapter_folders = [
            cf for cf in chapter_folders 
            if int(cf.name[2:]) in chapters_to_include
        ]
        if verbose:
            print(f"Processing {len(chapter_folders)} selected chapters (of {len(chapters_to_include)} requested)")
    else:
        if verbose:
            print(f"Found {len(chapter_folders)} chapters\n")
    
    # Process each chapter
    all_subtitles = []
    cumulative_time = 0.0
    chapter_timings = []
    
    for chapter_folder in chapter_folders:
        # Extract chapter number
        chapter_num = int(chapter_folder.name[2:]) if chapter_folder.name[2:].isdigit() else 0
        
        # Find corresponding text file
        text_file = text_path / f"chapter_{chapter_num:03d}.json"
        
        if not text_file.exists():
            if verbose:
                print(f"Warning: No text file for chapter {chapter_num}")
            continue
        
        if verbose:
            print(f"Processing Chapter {chapter_num}...")
        
        # Load text data
        chapter_text_data = load_chapter_text(text_file)
        
        # Generate subtitles for this chapter
        chapter_subtitles, chapter_duration = generate_chapter_subtitles(
            chapter_num, chapter_folder, chapter_text_data
        )
        
        if chapter_subtitles:
            # Save individual chapter SRT
            chapter_srt_file = chapters_srt_path / f"chapter_{chapter_num:03d}.srt"
            write_srt_file(chapter_subtitles, chapter_srt_file)
            if verbose:
                print(f"  Created: {chapter_srt_file.name}")
                print(f"  Subtitles: {len(chapter_subtitles)}")
                print(f"  Duration: {chapter_duration:.1f}s\n")
            
            # Add to full book with time offset
            for sub in chapter_subtitles:
                full_sub = sub.copy()
                full_sub['start'] += cumulative_time
                full_sub['end'] += cumulative_time
                full_sub['chapter'] = chapter_num
                all_subtitles.append(full_sub)
            
            # Track chapter timing
            chapter_timings.append({
                'chapter': chapter_num,
                'start_time': cumulative_time,
                'duration': chapter_duration,
                'subtitle_count': len(chapter_subtitles)
            })
            
            cumulative_time += chapter_duration
    
    # Write full book SRT
    if all_subtitles:
        full_srt_file = output_path / f"{book_id}_full_book.srt"
        
        # Renumber for continuous sequence
        for i, sub in enumerate(all_subtitles, 1):
            sub['index'] = i
        
        write_srt_file(all_subtitles, full_srt_file)
        
        # Also copy to combined_audio folder for convenience (same name as MP3)
        audio_srt_copied = None
        if copy_to_combined_audio:
            audio_output_path = Path(f"combined_audio/{book_id}")
            if audio_output_path.exists():
                audio_srt_file = audio_output_path / f"{book_id}_full_book.srt"
                write_srt_file(all_subtitles, audio_srt_file)
                audio_srt_copied = audio_srt_file
                if verbose:
                    print(f"  Also copied to: {audio_srt_file} (for auto-loading)")
        
        if verbose:
            print("=" * 60)
            print("Full Book Subtitle Generation Complete!")
            print(f"  File: {full_srt_file}")
            print(f"  Total subtitles: {len(all_subtitles)}")
            print(f"  Total duration: {cumulative_time:.1f}s ({cumulative_time/60:.1f} minutes)")
        
        # Save metadata
        metadata = {
            'book_id': book_id,
            'total_subtitles': len(all_subtitles),
            'total_duration_seconds': cumulative_time,
            'total_duration_formatted': format_srt_time(cumulative_time),
            'chapter_count': len(chapter_timings),
            'chapters': chapter_timings,
            'audio_source': str(audio_path),
            'text_source': str(text_path),
            'chapters_included': chapters_to_include
        }
        
        metadata_file = output_path / "subtitle_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        if verbose:
            print(f"  Metadata: {metadata_file}")
            
            # Display sample
            print("\n" + "=" * 60)
            print("Sample subtitles (first 3):")
            print("-" * 30)
            for sub in all_subtitles[:3]:
                start = format_srt_time(sub['start'])
                end = format_srt_time(sub['end'])
                text_preview = sub['text'][:60] + "..." if len(sub['text']) > 60 else sub['text']
                print(f"{sub['index']}. [{start} --> {end}]")
                print(f"   {text_preview}\n")
        
        return {
            'success': True,
            'subtitle_file': full_srt_file,
            'metadata_file': metadata_file,
            'audio_srt_file': audio_srt_copied,
            'total_subtitles': len(all_subtitles),
            'total_duration': cumulative_time,
            'chapters_processed': len(chapter_timings)
        }
    
    else:
        error_msg = "No subtitles were generated!"
        if verbose:
            print(error_msg)
        return {'success': False, 'error': error_msg}


def main():
    """Original main function using hardcoded values for backward compatibility"""
    result = generate_subtitles_for_book(
        book_id=BOOK_ID,
        audio_path=AUDIO_PATH,
        text_path=TEXT_PATH,
        output_path=OUTPUT_PATH,
        chapters_to_include=None,  # All chapters
        copy_to_combined_audio=True,
        verbose=True
    )
    
    if not result['success']:
        print(f"ERROR: {result.get('error', 'Unknown error')}")
    
    return result['success']


if __name__ == "__main__":
    main()