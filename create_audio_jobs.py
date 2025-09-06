import json
import yaml
from datetime import datetime
import os
import shutil
import sys

# Path configurations - where ComfyUI agent looks for new jobs
JOBS_PROCESSING_PATH = "jobs/processing"  # Base path where agent monitors
AUDIO_JOBS_DIR = os.path.join(JOBS_PROCESSING_PATH, "speech")  # Subfolder for audio jobs
FINISHED_AUDIO_PATH = "jobs/finished/speech"  # Where finished audio files will be saved

def create_audio_jobs(chapter_key, sentences, chapter_title, timestamp, output_dir=AUDIO_JOBS_DIR):
    """Create individual YAML configs for each sentence
    
    Args:
        chapter_key: Chapter identifier
        sentences: List of sentences
        chapter_title: Title of the chapter
        timestamp: Timestamp to use in filenames (from input file)
        output_dir: Output directory for YAML files
    """
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    created_files = []
    
    # Extract chapter number from chapter_key (e.g., "chapter_1" -> "1")
    chapter_num = chapter_key.split("_")[1] if "_" in chapter_key else "1"
    
    # Create one job per sentence
    for idx, sentence in enumerate(sentences, 1):
        # Skip empty sentences
        if not sentence.strip():
            continue
            
        # Filename format: TYPE_TIMESTAMP_INDEX_jobname.yaml
        # where INDEX is the chapter number, jobname includes sentence number
        filename = f"SPEECH_{timestamp}_{chapter_num}_s{idx:04d}.yaml"
        
        # Create job configuration for single sentence
        job_config = {
            "job_type": "SPEECH",
            "workflow_id": "T2S_chatterbox_v1", 
            "priority": 5,
            "inputs": {
                "10_text": sentence,
                "6_audio": "D:\\Projects\\pheonix\\prod\\E3\\E3\\audio_samples\\toireland_shelley_cf_128kb.mp3",
                "9_filename_prefix" : f"speech/{timestamp}/{chapter_num}/s{idx:04d}/audio"
            },
            "outputs": {
                "file_path": f"{FINISHED_AUDIO_PATH}/{chapter_key}_{timestamp}_s{idx:04d}.wav"
            },
            "metadata": {
                "chapter": chapter_key,
                "title": chapter_title,
                "sentence_index": idx,
                "total_sentences": len(sentences),
                "creator": "Novel to Audio Converter",
                "version": "1.0"
            }
        }
        
        # Save YAML file with UTF-8 encoding to handle special characters
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            # allow_unicode=True ensures special characters are preserved
            yaml.dump(job_config, f, default_flow_style=False, allow_unicode=True)
        
        created_files.append(filepath)
        print(f"Created: {filepath}")
    
    print(f"\nTotal files created: {len(created_files)}")
    print(f"Files location: {output_dir}")
    print(f"Audio outputs will be saved to: {FINISHED_AUDIO_PATH}")
    return created_files

def main():
    # Input filename with timestamp
    input_filename = "20250809221655.json"
    
    # Extract timestamp from filename (remove .json extension)
    timestamp = os.path.splitext(input_filename)[0]
    print(f"Using timestamp from input file: {timestamp}")
    
    # Read parsed chapters
    with open(input_filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Get total chapters
    total_chapters = len(data["chapter_sentences"])
    print(f"\nFound {total_chapters} chapters to process")
    
    # Process ALL chapters
    for chapter_key in sorted(data["chapter_sentences"].keys()):
        if chapter_key in data["chapter_sentences"]:
            sentences = data["chapter_sentences"][chapter_key]
            title = data["chapter_titles"][chapter_key]
            
            print(f"\n{'='*60}")
            print(f"Processing {chapter_key}: {title}")
            print(f"Sentences to process: {len(sentences)}")
            print(f"{'='*60}")
            
            create_audio_jobs(
                chapter_key,
                sentences,
                title,
                timestamp
            )
    
    print(f"\n{'='*60}")
    print(f"ALL CHAPTERS PROCESSED!")
    print(f"Total chapters: {total_chapters}")
    print(f"{'='*60}")

def cleanup_processed_files():
    """Move all YAML files from processing to finished folder"""
    
    print("\n" + "="*60)
    print("CLEANUP: Moving processed files")
    print("="*60)
    
    # Ensure finished directory exists
    os.makedirs(FINISHED_AUDIO_PATH, exist_ok=True)
    
    moved_count = 0
    
    # Check if processing directory exists
    if os.path.exists(AUDIO_JOBS_DIR):
        # List all YAML files in processing
        yaml_files = [f for f in os.listdir(AUDIO_JOBS_DIR) if f.endswith('.yaml')]
        
        print(f"Found {len(yaml_files)} YAML files in processing folder")
        
        for filename in yaml_files:
            src_path = os.path.join(AUDIO_JOBS_DIR, filename)
            dst_path = os.path.join(FINISHED_AUDIO_PATH, filename)
            
            try:
                # Move file (this removes it from source)
                shutil.move(src_path, dst_path)
                moved_count += 1
                print(f"Moved: {filename}")
            except FileExistsError:
                # If file already exists in destination, just remove from source
                os.remove(src_path)
                moved_count += 1
                print(f"Removed duplicate: {filename}")
            except Exception as e:
                print(f"Error moving {filename}: {e}")
    
    print(f"\nMoved/cleaned {moved_count} files")
    print(f"Processing folder: {AUDIO_JOBS_DIR}")
    print(f"Finished folder: {FINISHED_AUDIO_PATH}")
    
    return moved_count

if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "cleanup":
            # Just run cleanup
            cleanup_processed_files()
        elif sys.argv[1] == "create":
            # Just create new jobs
            main()
        else:
            print("Usage: python create_audio_jobs.py [create|cleanup]")
            print("  create  - Create new audio job YAML files for all chapters")
            print("  cleanup - Move processed files from processing to finished folder")
    else:
        # Default: create jobs
        main()
        print("\nTo clean up processed files, run: python create_audio_jobs.py cleanup")