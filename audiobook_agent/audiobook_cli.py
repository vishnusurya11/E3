"""
AUDIOBOOK CLI - Step 0 Implementation
Clean implementation using normalized database schema.
"""

import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

from audiobook_helper import get_processing_queue, get_audiobook_events, add_audiobook_event, add_book_metadata_to_first_chunk, get_comfyui_job_status_by_book_id, get_comfyui_audio_job_status, get_comfyui_image_job_status, move_comfyui_audio_files, move_comfyui_image_files, combine_audiobook_files, plan_audio_combinations, generate_subtitles_for_audiobook, generate_image_prompts_for_audiobook, create_image_jobs_for_audiobook, select_images_for_audiobook, generate_videos_for_audiobook, upload_videos_to_youtube

# Configuration
CONTINUOUS_MODE = True  # Set to False for single run
LOOP_INTERVAL_MINUTES = 5  # Configurable interval


def setup_logging():
    """Setup rotating log handler for automation."""
    logger = logging.getLogger('audiobook')
    logger.setLevel(logging.INFO)
    
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    handler = TimedRotatingFileHandler(
        'logs/audiobook.log',
        when='D',           # Daily rotation
        interval=1,         # Every 1 day
        backupCount=10      # Keep 10 days
    )
    
    # Pipe-separated format
    formatter = logging.Formatter('%(asctime)s|%(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def log_and_print(audiobook_id, book_id, step, status, message):
    """Log to file and print to terminal with consistent format."""
    timestamp = datetime.now().isoformat()
    log_msg = f"{audiobook_id}|{book_id}|{step}|{status}|{message}"
    
    # Print to terminal (for development)
    print(f"{timestamp}|{log_msg}")
    
    # Log to file (for automation)
    logger.info(log_msg)


# Initialize logger
logger = setup_logging()


def main_single_run():
    """
    ################################################################################
    # STEP 0: GET RECORDS THAT NEED PROCESSING
    # 
    # Purpose: Display audiobook productions with status != 'success'
    # Output:  Processing queue with book/narrator details
    ################################################################################
    """
    # Step 0 setup - no specific book yet
    timestamp = datetime.now().isoformat()
    print(f"DEBUG: Python working directory: {os.getcwd()}")
    print(f"{timestamp}|SYSTEM|STEP0_queue|STARTING|Getting processing queue")
    logger.info("SYSTEM|STEP0_queue|STARTING|Getting processing queue")
    
    # Get records that need processing (helper function)
    queue = get_processing_queue()

    print(f"queue--> {queue}")
    
    # Display results  
    if queue:
        timestamp = datetime.now().isoformat()
        print(f"{timestamp}|SYSTEM|STEP0_queue|SUCCESS|Found {len(queue)} productions to process")
        logger.info(f"SYSTEM|STEP0_queue|SUCCESS|Found {len(queue)} productions to process")
        
        for record in queue:
            log_and_print(record['audiobook_id'], record['book_id'], "STEP0_queue", "INFO", 
                         f"Book: {record['book_name']} by {record['author']}")
    else:
        timestamp = datetime.now().isoformat()
        print(f"{timestamp}|SYSTEM|STEP0_queue|SUCCESS|No productions need processing - All complete")
        logger.info("SYSTEM|STEP0_queue|SUCCESS|No productions need processing - All complete")

    # Sort queue by audiobook_id (YYYYMMDDHHMMSS format - oldest first)
    sorted_queue = sorted(queue, key=lambda x: x['audiobook_id'])
    
    if sorted_queue:
        timestamp = datetime.now().isoformat()
        print(f"{timestamp}|SYSTEM|PROCESSING|INFO|Processing {len(sorted_queue)} audiobooks in chronological order")
        logger.info(f"SYSTEM|PROCESSING|INFO|Processing {len(sorted_queue)} audiobooks in chronological order")
    
    for audiobook in sorted_queue:
        audiobook_id = audiobook['audiobook_id']
        book_id = audiobook['book_id']
        
        log_and_print(audiobook_id, book_id, "PROCESSING", "STARTING", f"Processing audiobook: {audiobook['book_name']}")
        
        # Check current events for this audiobook
        events = get_audiobook_events(audiobook_id)
        
        if not events:
            # No events yet - start with STEP1_parsing
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "QUEUING", "No events found - queuing STEP1_parsing")
            success = add_audiobook_event(audiobook_id, 'STEP1_parsing', 'pending')
            
            if success:
                log_and_print(audiobook_id, book_id, "STEP1_parsing", "QUEUED", "Added STEP1_parsing event")
            else:
                log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", "Failed to add event")
        else:
            # Find current step from latest event
            latest_event = events[-1]  # Last event by timestamp
            current_step = latest_event['step_number']
            current_status = latest_event['status']
            
            log_and_print(audiobook_id, book_id, current_step, "STATUS", f"Current state: {current_status.upper()} | Total events: {len(events)}")
            
            # Execute current step if pending or failed
            if current_step == 'STEP1_parsing' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP1_parsing", "STARTING", "Novel parsing execution initiated")
                
                result = execute_step1_parsing(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'success')
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'pending')  
                    
                    log_and_print(audiobook_id, book_id, "STEP1_parsing", "SUCCESS", "Novel parsing completed - STEP2_metadata queued")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP1_parsing", "FAILED", "Novel parsing execution failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP2_metadata' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP2_metadata", "STARTING", "Metadata addition execution initiated")
                
                result = execute_step2_metadata(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'success')
                    add_audiobook_event(audiobook_id, 'STEP3_create_audio_jobs', 'pending')  
                    
                    log_and_print(audiobook_id, book_id, "STEP2_metadata", "SUCCESS", "Metadata addition completed - STEP3_create_audio_jobs queued")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP2_metadata", "FAILED", "Metadata addition execution failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP3_create_audio_jobs' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "STARTING", "TTS job creation execution initiated")
                
                result = execute_step3_create_audio_jobs(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP3_create_audio_jobs', 'success')
                    add_audiobook_event(audiobook_id, 'STEP4_monitor_and_move_audio', 'pending')  
                    
                    log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "SUCCESS", "TTS jobs created - STEP4_monitor_and_move_audio queued")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP3_create_audio_jobs', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "FAILED", "TTS job creation failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP4_monitor_and_move_audio' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "STARTING", "Audio monitoring and moving execution initiated")
                
                result = execute_step4_monitor_and_move_audio(audiobook, current_status)  # Pass current status instead of step
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP4_monitor_and_move_audio', 'success')
                    add_audiobook_event(audiobook_id, 'STEP5_combine_audio', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "SUCCESS", "Audio monitoring and moving completed - STEP5_combine_audio queued")
                elif result == "P":
                    log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "WAITING", "ComfyUI jobs still processing - will check again next cycle")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP4_monitor_and_move_audio', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "FAILED", "Audio monitoring and moving failed")

            elif current_step == 'STEP5_combine_audio' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "STARTING", "Audio combination execution initiated")
                
                result = execute_step5_combine_audio(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP5_combine_audio', 'success')
                    add_audiobook_event(audiobook_id, 'STEP6_generate_subtitles', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "SUCCESS", "Audio planning and combination completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP5_combine_audio', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "FAILED", "Audio combination failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP6_generate_subtitles' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "STARTING", "Subtitle generation execution initiated")
                
                result = execute_step6_generate_subtitles(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP6_generate_subtitles', 'success')
                    add_audiobook_event(audiobook_id, 'STEP7_generate_image_prompts', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "SUCCESS", "Subtitle generation completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP6_generate_subtitles', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "FAILED", "Subtitle generation failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP7_generate_image_prompts' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "STARTING", "Image prompt generation execution initiated")
                
                result = execute_step7_generate_image_prompts(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP7_generate_image_prompts', 'success')
                    add_audiobook_event(audiobook_id, 'STEP8_create_image_jobs', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "SUCCESS", "Image prompt generation completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP7_generate_image_prompts', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "FAILED", "Image prompt generation failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP8_create_image_jobs' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "STARTING", "Image job creation execution initiated")
                
                result = execute_step8_create_image_jobs(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP8_create_image_jobs', 'success')
                    add_audiobook_event(audiobook_id, 'STEP9_monitor_and_move_images', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "SUCCESS", "Image job creation completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP8_create_image_jobs', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "FAILED", "Image job creation failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP9_monitor_and_move_images' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "STARTING", "Image monitoring and moving execution initiated")
                
                result = execute_step9_monitor_and_move_images(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP9_monitor_and_move_images', 'success')
                    add_audiobook_event(audiobook_id, 'STEP10_select_image', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "SUCCESS", "Image monitoring and moving completed")
                elif result == "P":
                    log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "WAITING", "ComfyUI image jobs still processing - will check again next cycle")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP9_monitor_and_move_images', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "FAILED", "Image monitoring and moving failed")

            elif current_step == 'STEP10_select_image' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP10_select_image", "STARTING", "Image selection execution initiated")
                
                result = execute_step10_select_images(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP10_select_image', 'success')
                    add_audiobook_event(audiobook_id, 'STEP11_generate_video', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP10_select_image", "SUCCESS", "Image selection completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP10_select_image', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP10_select_image", "FAILED", "Image selection failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP11_generate_video' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP11_generate_video", "STARTING", "Video generation execution initiated")
                
                result = execute_step11_generate_videos(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP11_generate_video', 'success')
                    add_audiobook_event(audiobook_id, 'STEP12_upload_video_to_youtube', 'pending')
                    
                    log_and_print(audiobook_id, book_id, "STEP11_generate_video", "SUCCESS", "Video generation completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP11_generate_video', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP11_generate_video", "FAILED", "Video generation failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book

            elif current_step == 'STEP12_upload_video_to_youtube' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "STARTING", "YouTube upload execution initiated")
                
                result = execute_step12_upload_video_to_youtube(audiobook, current_status)  # Pass current status
                
                # Update event status based on result
                if result == "S":
                    add_audiobook_event(audiobook_id, 'STEP12_upload_video_to_youtube', 'success')
                    # TODO: Add STEP13 when implemented
                    
                    log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "SUCCESS", "YouTube upload completed")
                elif result == "F":
                    add_audiobook_event(audiobook_id, 'STEP12_upload_video_to_youtube', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "FAILED", "YouTube upload failed")
                elif result == "P":
                    pass  # Skip - no events, just continue to next book
            
            # TODO: Add other steps (STEP13, STEP14, etc.)
    
    timestamp = datetime.now().isoformat()
    print(f"{timestamp}|SYSTEM|PROCESSING|COMPLETED|Event processing cycle finished")
    logger.info("SYSTEM|PROCESSING|COMPLETED|Event processing cycle finished")


def execute_step1_parsing(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP1_parsing: Parse novel from HTML source
    #
    # Purpose: Extract chapters and text chunks from book HTML file
    # Input:   Complete audiobook dict with book/narrator details
    # Output:  Parsed chapters saved to foundry/{book_id}/audiobook/
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP1_parsing", "STILL_PROCESSING", "Step still processing from previous run")
        return "P"  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'processing')
    log_and_print(audiobook_id, book_id, "STEP1_parsing", "PROCESSING", "Novel parsing execution started")
    
    try:
        language = audiobook_dict.get('language', 'eng')
        
        # Find input HTML file
        import glob, os
        input_pattern = f"foundry/{book_id}/*{book_id}*.html"
        html_files = glob.glob(input_pattern)
        print(f" html_files - > {html_files}")
        if not html_files:
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"No HTML file found in foundry/{book_id}/")
            return "F"
            
        input_file = html_files[0]
        output_dir = f"foundry/{book_id}/{language}/chapters"
        os.makedirs(output_dir, exist_ok=True)
        
        log_and_print(audiobook_id, book_id, "STEP1_parsing", "PROGRESS", f"Input: {input_file} | Output: {output_dir}")
        
        # Call parse_novel function
        from parse_novel_tts import parse_novel
        result = parse_novel(input_file=input_file, output_dir=output_dir, verbose=True)
        
        if result.get('success', False):
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "SUCCESS", f"Parsed {result.get('total_chapters', 0)} chapters, {result.get('total_chunks', 0)} chunks, {result.get('total_words', 0)} words")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"Parse failed: {result.get('error', 'Unknown')}")
            return "F"
        
    except Exception as e:
        print("###############")
        print(e)
        log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"Exception: {str(e)}")
        return "F"


def execute_step2_metadata(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP2_metadata: Add book metadata to first chunk
    #
    # Purpose: Enhance first audio chunk with book title/author info for introduction
    # Input:   Complete audiobook dict with book/narrator details
    # Output:  Enhanced first chunk in metadata.json
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP2_metadata", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'processing')
    log_and_print(audiobook_id, book_id, "STEP2_metadata", "PROCESSING", "Metadata addition execution started")
    
    try:
        # Call helper function to add metadata to first chunk
        success = add_book_metadata_to_first_chunk(
            book_id=book_id,
            language=language,
            book_name=audiobook_dict['book_name'],
            author=audiobook_dict['author'],
            narrator_name=audiobook_dict['narrator_name']
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP2_metadata", "SUCCESS", "Book metadata added to first chunk")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP2_metadata", "ERROR", "Failed to add metadata to first chunk")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP2_metadata", "ERROR", f"Exception: {str(e)}")
        return "F"


def execute_step3_create_audio_jobs(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP3_create_audio_jobs: Create TTS jobs for ComfyUI processing
    #
    # Purpose: Convert parsed chapter JSON files into TTS job YAML configs
    # Input:   Complete audiobook dict with narrator voice sample
    # Output:  TTS job files in comfyui_jobs/processing/speech/
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP3_create_audio_jobs', 'processing')
    log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "PROCESSING", "TTS job creation started")
    
    try:
        # Call create_tts_jobs function with our folder structure
        from create_tts_audio_jobs import create_tts_jobs
        
        input_dir = f"foundry/{book_id}/{language}/chapters"  # Our chapter files
        
        log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "PROGRESS", f"Input dir: {input_dir} | Voice: {audiobook_dict['sample_filepath']}")
        
        result = create_tts_jobs(
            input_book_dir=input_dir,
            jobs_output_dir="comfyui_jobs/processing/speech",      # ComfyUI input
            finished_audio_dir="comfyui_jobs/finished/speech",     # ComfyUI output  
            voice_sample=audiobook_dict['sample_filepath'],        # Narrator voice
            book_filter=book_id,
            verbose=True,
            audiobook_dict=audiobook_dict                          # NEW: Pass complete dict
        )
        
        if result.get('success', False):
            jobs_created = result.get('total_jobs_created', 0)
            log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "SUCCESS", f"Created {jobs_created} TTS jobs for ComfyUI processing")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "ERROR", f"Job creation failed: {result.get('error', 'Unknown error')}")
            return "F"
            
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP3_create_audio_jobs", "ERROR", f"Exception: {str(e)}")
        return False


def execute_step4_monitor_and_move_audio(audiobook_dict: dict, current_step):
    """
    ################################################################################
    # STEP4_monitor_and_move_audio: Monitor TTS job completion and move audio files
    #
    # Purpose: Monitor ComfyUI TTS job completion and organize generated audio files
    # Input:   Complete audiobook dict with book/narrator details
    # Output:  Audio files organized in foundry/{book_id}/speech/
    # Returns: "processing" if jobs still running, True if completed, False if failed
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # Update to processing when starting
    if current_step == "pending" or current_step == "failed":
        add_audiobook_event(audiobook_id, 'STEP4_monitor_and_move_audio', 'processing')
        log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "PROCESSING", "Audio monitoring and moving started")
    
    try:
        # Check ComfyUI audio job status for this book
        job_status = get_comfyui_audio_job_status(book_id)
        
        if not job_status:
            log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "ERROR", "No ComfyUI jobs found for this book")
            return "F"
        
        # Check if all jobs are done
        pending_count = job_status.get('pending', 0)
        processing_count = job_status.get('processing', 0) 
        done_count = job_status.get('done', 0)
        failed_count = job_status.get('failed', 0)
        
        log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "PROGRESS", 
                     f"Job status - Done: {done_count}, Pending: {pending_count}, Processing: {processing_count}, Failed: {failed_count}")
        
        # If there are still pending or processing jobs, wait
        if pending_count > 0 or processing_count > 0:
            log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "WAITING", "ComfyUI jobs still in progress - waiting for completion")
            return "processing"  # Special return value to indicate still processing
        
        # If there are failed jobs, report error
        if failed_count > 0 and done_count == 0:
            log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "ERROR", f"{failed_count} jobs failed with no successful completions")
            return "F"
        
        # All jobs are done - proceed with moving files
        log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "PROGRESS", f"All {done_count} ComfyUI jobs completed - moving audio files")
        
        # Move audio files from ComfyUI output to foundry
        success = move_comfyui_audio_files(book_id, language)
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "SUCCESS", "Audio files moved successfully to foundry speech directory")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "ERROR", "Failed to move audio files")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP4_monitor_and_move_audio", "ERROR", f"Exception: {str(e)}")
        return False


def execute_step5_combine_audio(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP5_combine_audio: Plan and combine audio files into final audiobook
    #
    # Purpose: 1) Analyze duration and create combination plan (parts/chapters)
    #          2) Combine audio files based on the plan
    # Input:   Audio files in foundry/{book_id}/{language}/speech/ with ch001/chunk001 structure  
    # Output:  Final audiobook files in foundry/{book_id}/{language}/combined_audio/
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP5_combine_audio', 'processing')
    log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "PROCESSING", "Audio planning and combination started")
    
    try:
        # Phase 1: Create combination plan
        log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "PLANNING", "Creating audio combination plan")
        
        combination_plan = plan_audio_combinations(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if not combination_plan.get('success', False):
            error_msg = combination_plan.get('error', 'Planning failed')
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "ERROR", f"Planning phase failed: {error_msg}")
            return "F"
        
        # Log planning results
        parts_needed = combination_plan.get('parts_needed', 1)
        total_hours = combination_plan.get('total_duration_hours', 0)
        
        if combination_plan.get('exceeds_limit', False):
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "PLANNED", 
                         f"Multi-part plan: {parts_needed} parts for {total_hours:.2f}h audiobook")
        else:
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "PLANNED", 
                         f"Single part plan: {total_hours:.2f}h audiobook")
        
        # Save combination plan to file for future steps
        try:
            import json
            import os
            plan_file = f"foundry/{book_id}/{language}/combination_plan.json"
            os.makedirs(os.path.dirname(plan_file), exist_ok=True)
            
            with open(plan_file, 'w', encoding='utf-8') as f:
                json.dump(combination_plan, f, indent=2, ensure_ascii=False)
            
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "SAVED", f"Combination plan saved to {plan_file}")
        except Exception as e:
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "WARNING", f"Failed to save combination plan: {e}")
        
        # Phase 2: Execute combination using the plan
        log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "COMBINING", "Executing audio combination with plan")
        
        success = combine_audiobook_files(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict,
            combination_plan=combination_plan  # Pass the plan to combination
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "SUCCESS", 
                         f"Audio planning and combination completed - {parts_needed} parts created")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "ERROR", "Audio combination phase failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP5_combine_audio", "ERROR", f"Exception: {str(e)}")
        return False


def execute_step6_generate_subtitles(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP6_generate_subtitles: Generate subtitle files for audiobook parts
    #
    # Purpose: Read combination plan and generate subtitles for each part
    # Input:   combination_plan.json and audio files from STEP5
    # Output:  Subtitle files and updated combination plan with subtitle paths
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP6_generate_subtitles', 'processing')
    log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "PROCESSING", "Subtitle generation started")
    
    try:
        # Call helper function to generate subtitles
        success = generate_subtitles_for_audiobook(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "SUCCESS", "Subtitle generation completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "ERROR", "Subtitle generation failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP6_generate_subtitles", "ERROR", f"Exception: {str(e)}")
        return False




def execute_step7_generate_image_prompts(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP7_generate_image_prompts: Generate image prompts for audiobook thumbnails
    #
    # Purpose: Read combination plan and generate image prompts for each part
    # Input:   combination_plan.json and book metadata
    # Output:  Image prompt files and updated combination plan with prompt paths
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP7_generate_image_prompts', 'processing')
    log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "PROCESSING", "Image prompt generation started")
    
    try:
        # Call helper function to generate image prompts
        success = generate_image_prompts_for_audiobook(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "SUCCESS", "Image prompt generation completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "ERROR", "Image prompt generation failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP7_generate_image_prompts", "ERROR", f"Exception: {str(e)}")
        return False


def execute_step8_create_image_jobs(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP8_create_image_jobs: Create ComfyUI image generation jobs
    #
    # Purpose: Read combination plan and create ComfyUI job files for image generation
    # Input:   Image prompts from STEP7 in foundry structure
    # Output:  ComfyUI job YAML files in comfyui_jobs/processing/
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP8_create_image_jobs', 'processing')
    log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "PROCESSING", "Image job creation started")
    
    try:
        # Call helper function to create image jobs
        success = create_image_jobs_for_audiobook(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "SUCCESS", "Image job creation completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "ERROR", "Image job creation failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP8_create_image_jobs", "ERROR", f"Exception: {str(e)}")
        return False



def execute_step9_monitor_and_move_images(audiobook_dict: dict, current_step):
    """
    ################################################################################
    # STEP9_monitor_and_move_images: Monitor image job completion and move image files
    #
    # Purpose: Monitor ComfyUI image job completion and organize generated image files
    # Input:   Complete audiobook dict with book details
    # Output:  Image files organized in foundry/{book_id}/{language}/images/
    # Returns: "processing" if jobs still running, True if completed, False if failed
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # Update to processing when starting
    if current_step == "pending" or current_step == "failed":
        add_audiobook_event(audiobook_id, 'STEP9_monitor_and_move_images', 'processing')
        log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "PROCESSING", "Image monitoring and moving started")
    
    try:
        # Check ComfyUI image job status for this book
        job_status = get_comfyui_image_job_status(book_id)
        
        if not job_status:
            log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "ERROR", "No ComfyUI image jobs found for this book")
            return "F"
        
        # Check if all jobs are done
        pending_count = job_status.get('pending', 0)
        processing_count = job_status.get('processing', 0) 
        done_count = job_status.get('done', 0)
        failed_count = job_status.get('failed', 0)
        
        log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "PROGRESS", 
                     f"Image job status - Done: {done_count}, Pending: {pending_count}, Processing: {processing_count}, Failed: {failed_count}")
        
        # If there are still pending or processing jobs, wait
        if pending_count > 0 or processing_count > 0:
            log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "WAITING", "ComfyUI image jobs still in progress - waiting for completion")
            return "processing"  # Special return value to indicate still processing
        
        # If there are failed jobs, report error
        if failed_count > 0 and done_count == 0:
            log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "ERROR", f"{failed_count} image jobs failed with no successful completions")
            return "F"
        
        # All jobs are done - proceed with moving files
        log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "PROGRESS", f"All {done_count} ComfyUI image jobs completed - moving image files")
        
        # Move image files from ComfyUI output to foundry
        success = move_comfyui_image_files(book_id, language)
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "SUCCESS", "Image files moved successfully to foundry images directory")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "ERROR", "Failed to move image files")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP9_monitor_and_move_images", "ERROR", f"Exception: {str(e)}")
        return False



def execute_step10_select_images(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP10_select_images: Select thumbnail images for audiobook parts
    #
    # Purpose: Randomly select one image per part from generated images
    # Input:   Generated images in foundry/{book_id}/{language}/images/
    # Output:  Updated combination plan with selected image paths
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP10_select_images", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP10_select_images', 'processing')
    log_and_print(audiobook_id, book_id, "STEP10_select_images", "PROCESSING", "Image selection started")
    
    try:
        # Call helper function to select images
        success = select_images_for_audiobook(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP10_select_images", "SUCCESS", "Image selection completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP10_select_images", "ERROR", "Image selection failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP10_select_images", "ERROR", f"Exception: {str(e)}")
        return False



def execute_step12_upload_video_to_youtube(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP12_upload_video_to_youtube: Upload video files to YouTube
    #
    # Purpose: Upload generated videos to YouTube with metadata and scheduling
    # Input:   Video files and metadata from combination_plan.json
    # Output:  YouTube video URLs and updated combination plan
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "STILL_PROCESSING", "Step still processing from previous run")
        return "P"  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP12_upload_video_to_youtube', 'processing')
    log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "PROCESSING", "YouTube upload started")
    
    try:
        # Call helper function to upload videos
        success = upload_videos_to_youtube(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "SUCCESS", "YouTube upload completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "ERROR", "YouTube upload failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP12_upload_video_to_youtube", "ERROR", f"Exception: {str(e)}")
        return "F"


def execute_step11_generate_videos(audiobook_dict: dict, current_status: str = "pending") -> str:
    """
    ################################################################################
    # STEP11_generate_videos: Generate video files from audio and selected images
    #
    # Purpose: Combine audio files with selected thumbnail images to create videos
    # Input:   Audio and image paths from combination_plan.json
    # Output:  Video files in foundry/{book_id}/{language}/videos/
    ################################################################################
    """
    book_id = audiobook_dict['book_id']
    audiobook_id = audiobook_dict['audiobook_id']
    language = audiobook_dict.get('language', 'eng')
    
    # If already processing, just log and exit
    if current_status == "processing":
        log_and_print(audiobook_id, book_id, "STEP11_generate_videos", "STILL_PROCESSING", "Step still processing from previous run")
        return True  # Don't change database status
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP11_generate_videos', 'processing')
    log_and_print(audiobook_id, book_id, "STEP11_generate_videos", "PROCESSING", "Video generation started")
    
    try:
        # Call helper function to generate videos
        success = generate_videos_for_audiobook(
            book_id=book_id,
            language=language,
            audiobook_dict=audiobook_dict
        )
        
        if success:
            log_and_print(audiobook_id, book_id, "STEP11_generate_videos", "SUCCESS", "Video generation completed")
            return "S"
        else:
            log_and_print(audiobook_id, book_id, "STEP11_generate_videos", "ERROR", "Video generation failed")
            return "F"
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP11_generate_videos", "ERROR", f"Exception: {str(e)}")
        return False



def run_audiobook_automation():
    """
    Callable function to run audiobook automation logic (for master_cli.py).

    Returns:
        bool: True if completed successfully, False if failed
    """
    try:
        main_single_run()
        return True
    except Exception as e:
        print(f"Audiobook automation failed: {str(e)}")
        logger.error(f"AUDIOBOOK|ERROR|Automation failed: {str(e)}")
        return False


def main():
    """
    Main entry point - supports both single run and continuous mode.
    """
    if not CONTINUOUS_MODE:
        return main_single_run()

    print(f"AUDIOBOOK CLI CONTINUOUS AUTOMATION")
    print(f"Running every {LOOP_INTERVAL_MINUTES} minutes")
    print(f"Working directory: {os.getcwd()}")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    run_count = 0
    try:
        while True:
            run_count += 1
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[Audiobook Run #{run_count}] {timestamp}")
            print("#" * 60)

            try:
                success = run_audiobook_automation()
                if success:
                    print(f"SUCCESS: Audiobook Run #{run_count} completed successfully")
                    logger.info(f"AUTOMATION|RUN_{run_count}|SUCCESS|Automation cycle completed")
                else:
                    print(f"ERROR: Audiobook Run #{run_count} failed")
                    logger.error(f"AUTOMATION|RUN_{run_count}|ERROR|Automation cycle failed")
            except KeyboardInterrupt:
                raise  # Re-raise to break out of loop
            except Exception as e:
                print(f"ERROR: Audiobook Run #{run_count} failed: {str(e)}")
                logger.error(f"AUTOMATION|RUN_{run_count}|ERROR|Automation cycle failed: {str(e)}")

            print(f"Waiting {LOOP_INTERVAL_MINUTES} minutes until next run...")
            logger.info(f"AUTOMATION|RUN_{run_count}|WAITING|Next run in {LOOP_INTERVAL_MINUTES} minutes")
            print("#" * 60)

            # Sleep for specified interval
            time.sleep(LOOP_INTERVAL_MINUTES * 60)

    except KeyboardInterrupt:
        print(f"\nAudiobook automation stopped by user after {run_count} runs")
        logger.info(f"AUTOMATION|STOPPED|User stopped automation after {run_count} runs")
        print("Goodbye!")


if __name__ == "__main__":
    main()