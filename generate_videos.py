#!/usr/bin/env python3
"""
Generate videos for audiobooks by combining audio parts with thumbnail images.
Takes combined audio files and randomly selects from generated thumbnails.
"""

import json
import os
import random
import subprocess
import glob
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

def find_audio_file(audio_dir: str, base_filename: str, verbose: bool = False) -> Optional[str]:
    """
    Find audio file with any supported extension.
    
    Args:
        audio_dir: Directory to search in
        base_filename: Base filename without extension
        verbose: Enable logging
        
    Returns:
        Full path to audio file if found, None otherwise
    """
    # Support all common audio formats
    audio_extensions = ['.mp3', '.flac', '.wav', '.m4a', '.aac', '.ogg']
    
    for ext in audio_extensions:
        file_path = os.path.join(audio_dir, base_filename + ext)
        if os.path.exists(file_path):
            if verbose:
                print(f"    📁 Found audio file: {base_filename}{ext}")
            return file_path
    
    # If exact filename not found, try pattern matching
    if verbose:
        print(f"    🔍 Exact file not found, trying pattern search...")
    
    # Try glob pattern matching for any extension
    pattern = os.path.join(audio_dir, base_filename + ".*")
    matches = glob.glob(pattern)
    
    # Filter for audio files only
    audio_matches = [f for f in matches if os.path.splitext(f)[1].lower() in audio_extensions]
    
    if audio_matches:
        found_file = audio_matches[0]  # Take first match
        if verbose:
            print(f"    📁 Pattern match found: {os.path.basename(found_file)}")
        return found_file
    
    if verbose:
        print(f"    ❌ No audio file found for: {base_filename}")
        print(f"    🔍 Searched in: {audio_dir}")
        print(f"    🔍 Tried extensions: {audio_extensions}")
    
    return None

def generate_video_for_part(
    book_id: str,
    part_number: int,
    audio_file: str,
    images_dir: str,
    output_dir: str,
    verbose: bool = True
) -> Dict:
    """
    Generate a video for a single audiobook part.
    
    Args:
        book_id: Book identifier (e.g., 'pg1155')
        part_number: Part number (1, 2, etc.)
        audio_file: Path to combined audio file
        images_dir: Directory containing generated thumbnail images
        output_dir: Output directory for video file
        verbose: Enable detailed logging
        
    Returns:
        Dict with success status and video details
    """
    if verbose:
        print(f"  🎬 Generating video for Part {part_number}...")
    
    # Check audio file exists
    if not os.path.exists(audio_file):
        return {
            'success': False,
            'error': f'Audio file not found: {audio_file}'
        }
    
    # Find available thumbnail images
    part_images_dir = Path(images_dir) / f"part{part_number}"
    if not part_images_dir.exists():
        return {
            'success': False,
            'error': f'Images directory not found: {part_images_dir}'
        }
    
    # Get all image files (.png, .jpg)
    image_files = list(part_images_dir.glob("*.png")) + list(part_images_dir.glob("*.jpg"))
    
    if not image_files:
        return {
            'success': False,
            'error': f'No image files found in {part_images_dir}'
        }
    
    # Randomly select one thumbnail
    selected_image = random.choice(image_files)
    
    if verbose:
        print(f"    📁 Audio: {os.path.basename(audio_file)}")
        print(f"    🖼️  Image: {selected_image.name} (selected from {len(image_files)} options)")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate output filename
    output_filename = f"{book_id}_part{part_number}.mp4"
    output_path = os.path.join(output_dir, output_filename)
    
    # FFmpeg command to create video
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",  # Overwrite output file
        "-loop", "1",  # Loop the image for full audio duration
        "-i", str(selected_image),  # Input image
        "-i", audio_file,  # Input audio
        "-c:v", "libx264",  # Video codec
        "-tune", "stillimage",  # Optimize for static image
        "-c:a", "aac",  # Audio codec
        "-b:a", "192k",  # Audio bitrate
        "-b:v", "1000k",  # Video bitrate
        "-pix_fmt", "yuv420p",  # Pixel format for compatibility
        "-shortest",  # End when shortest input ends
        "-movflags", "+faststart",  # Optimize for streaming
        output_path
    ]
    
    if verbose:
        print(f"    🔄 Running FFmpeg...")
        print(f"    This may take a while for long audio files...")
        
    # Run FFmpeg with real-time progress (no timeout)
    try:
        process = subprocess.Popen(ffmpeg_cmd, stderr=subprocess.PIPE, universal_newlines=True)
        
        # Collect error output and show progress
        error_output = []
        
        for line in process.stderr:
            error_output.append(line)
            if "time=" in line:
                # Extract time from ffmpeg output
                time_str = line.split("time=")[1].split()[0]
                if verbose:
                    print(f"\r    Progress: {time_str}", end="", flush=True)
            elif "error" in line.lower() or "invalid" in line.lower():
                if verbose:
                    print(f"\n    FFmpeg: {line.strip()}")
        
        process.wait()
        
        if verbose:
            print()  # New line after progress
        
        if process.returncode == 0:
            # Check output file was created
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                
                if verbose:
                    print(f"    ✅ Video created: {output_filename} ({file_size:,} bytes)")
                
                return {
                    'success': True,
                    'output_file': output_path,
                    'file_size': file_size,
                    'selected_image': str(selected_image),
                    'audio_source': audio_file
                }
            else:
                return {
                    'success': False,
                    'error': 'FFmpeg completed but output file not found'
                }
        else:
            # FFmpeg failed
            error_text = ''.join(error_output[-10:])  # Last 10 lines
            return {
                'success': False,
                'error': f'FFmpeg failed with return code {process.returncode}: {error_text}'
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Video generation error: {e}'
        }


def generate_videos_for_book(
    book_id: str,
    output_path: str = None,
    verbose: bool = True
) -> Dict:
    """
    Generate videos for all parts of an audiobook.
    
    Args:
        book_id: Book identifier (e.g., 'pg1155')
        output_path: Optional custom output directory
        verbose: Enable detailed logging
        
    Returns:
        Dict with success status and video generation details
    """
    if verbose:
        print(f"\n🎬 GENERATING VIDEOS FOR AUDIOBOOK")
        print("=" * 60)
        print(f"📚 Book ID: {book_id}")
    
    try:
        # Setup paths
        base_dir = f"foundry/processing/{book_id}"
        audio_dir = f"{base_dir}/combined_audio"
        images_dir = f"D:\\Projects\\pheonix\\dev\\output\\images\\{book_id}"
        output_dir = output_path or f"{base_dir}/videos"
        
        if verbose:
            print(f"📁 Audio source: {audio_dir}")
            print(f"🖼️  Images source: {images_dir}")
            print(f"📹 Video output: {output_dir}")
        
        # Load metadata to get part information
        metadata_file = f"{base_dir}/metadata.json"
        if not os.path.exists(metadata_file):
            return {
                'success': False,
                'error': f'Metadata file not found: {metadata_file}'
            }
        
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # Get audio combination plan
        combination_plan = metadata.get('audio_combination_plan', {})
        combinations = combination_plan.get('combinations', [])
        
        if not combinations:
            return {
                'success': False,
                'error': 'No audio combinations found in metadata'
            }
        
        if verbose:
            print(f"📊 Found {len(combinations)} parts to process")
        
        # Generate videos for each part
        created_videos = []
        total_size = 0
        
        for combination in combinations:
            part_number = combination['part']
            expected_filename = combination.get('output_filename', f"{book_id}_part{part_number}.mp3")
            
            # Remove extension to get base filename
            base_filename = os.path.splitext(expected_filename)[0]
            
            if verbose:
                print(f"\n📹 Processing Part {part_number}:")
                print(f"    Expected: {expected_filename}")
            
            # Find actual audio file with any extension
            audio_file = find_audio_file(audio_dir, base_filename, verbose=verbose)
            
            if not audio_file:
                return {
                    'success': False,
                    'error': f'Audio file not found for part {part_number}. Expected base: {base_filename}'
                }
            
            # Generate video for this part
            result = generate_video_for_part(
                book_id=book_id,
                part_number=part_number,
                audio_file=audio_file,
                images_dir=images_dir,
                output_dir=output_dir,
                verbose=verbose
            )
            
            if result['success']:
                created_videos.append({
                    'part': part_number,
                    'video_file': result['output_file'],
                    'file_size': result['file_size'],
                    'selected_image': result['selected_image'],
                    'audio_source': result['audio_source']
                })
                total_size += result['file_size']
            else:
                if verbose:
                    print(f"    ❌ Failed: {result['error']}")
                return {
                    'success': False,
                    'error': f"Part {part_number} video generation failed: {result['error']}"
                }
        
        # Create generation metadata
        generation_metadata = {
            'book_id': book_id,
            'generation_completed_at': datetime.now().isoformat(),
            'total_parts': len(combinations),
            'total_videos': len(created_videos),
            'total_size_bytes': total_size,
            'videos': created_videos
        }
        
        # Save metadata
        metadata_file = os.path.join(output_dir, 'video_generation_metadata.json')
        with open(metadata_file, 'w') as f:
            json.dump(generation_metadata, f, indent=2)
        
        if verbose:
            print(f"\n✅ VIDEO GENERATION COMPLETE!")
            print(f"   Total videos: {len(created_videos)}")
            print(f"   Total size: {total_size:,} bytes")
            print(f"   Output directory: {output_dir}")
        
        return {
            'success': True,
            'total_videos': len(created_videos),
            'total_size': total_size,
            'output_directory': output_dir,
            'created_videos': created_videos,
            'metadata_file': metadata_file
        }
        
    except Exception as e:
        if verbose:
            print(f"❌ Video generation error: {e}")
            import traceback
            traceback.print_exc()
        
        return {
            'success': False,
            'error': f'Video generation failed: {e}'
        }


def main():
    """Test video generation with pg1155"""
    print("🎬 VIDEO GENERATION TEST")
    print("=" * 40)
    
    # Test with pg1155
    result = generate_videos_for_book(
        book_id="pg1155",
        verbose=True
    )
    
    if result['success']:
        print(f"\n🎉 Success! Generated {result['total_videos']} videos")
        for video in result['created_videos']:
            print(f"  📹 Part {video['part']}: {os.path.basename(video['video_file'])}")
    else:
        print(f"\n❌ Failed: {result['error']}")
    
    return result['success']


if __name__ == "__main__":
    main()