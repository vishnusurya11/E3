"""
AUDIOBOOK CLI - Step 0 Implementation
Clean implementation using normalized database schema.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

from audiobook_helper import get_processing_queue, get_audiobook_events, add_audiobook_event, add_book_metadata_to_first_chunk


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


def main():
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
                         f"Book: {record['book_name']} by {record['author']} - Status: {record['status']}")
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
                
                success = execute_step1_parsing(audiobook)  # Pass entire dict
                
                # Update event status based on result
                if success:
                    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'success')
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'pending')  
                    
                    log_and_print(audiobook_id, book_id, "STEP1_parsing", "SUCCESS", "Novel parsing completed - STEP3_create_audio_jobs queued")
                else:
                    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP1_parsing", "FAILED", "Novel parsing execution failed")

            elif current_step == 'STEP2_metadata' and current_status not in ['success']:
                log_and_print(audiobook_id, book_id, "STEP2_metadata", "STARTING", "Metadata addition execution initiated")
                
                success = execute_step2_metadata(audiobook)  # Pass entire dict
                
                # Update event status based on result
                if success:
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'success')
                    add_audiobook_event(audiobook_id, 'STEP3_create_audio_jobs', 'pending')  
                    
                    log_and_print(audiobook_id, book_id, "STEP2_metadata", "SUCCESS", "Metadata addition completed - STEP3_create_audio_jobs queued")
                else:
                    add_audiobook_event(audiobook_id, 'STEP2_metadata', 'failed')
                    log_and_print(audiobook_id, book_id, "STEP2_metadata", "FAILED", "Metadata addition execution failed")
            
            # TODO: Add other steps (STEP3, STEP4, etc.)
    
    timestamp = datetime.now().isoformat()
    print(f"{timestamp}|SYSTEM|PROCESSING|COMPLETED|Event processing cycle finished")
    logger.info("SYSTEM|PROCESSING|COMPLETED|Event processing cycle finished")


def execute_step1_parsing(audiobook_dict: dict) -> bool:
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
    
    # Update to processing when starting
    add_audiobook_event(audiobook_id, 'STEP1_parsing', 'processing')
    log_and_print(audiobook_id, book_id, "STEP1_parsing", "PROCESSING", "Novel parsing execution started")
    
    try:
        language = audiobook_dict.get('language', 'eng')
        
        # Find input HTML file
        import glob, os
        input_pattern = f"foundry/{book_id}/*{book_id}*.html"
        html_files = glob.glob(input_pattern)
        
        if not html_files:
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"No HTML file found in foundry/{book_id}/")
            return False
            
        input_file = html_files[0]
        output_dir = f"foundry/{book_id}/{language}/chapters"
        os.makedirs(output_dir, exist_ok=True)
        
        log_and_print(audiobook_id, book_id, "STEP1_parsing", "PROGRESS", f"Input: {input_file} | Output: {output_dir}")
        
        # Call parse_novel function
        from parse_novel_tts import parse_novel
        result = parse_novel(input_file=input_file, output_dir=output_dir, verbose=True)
        
        if result.get('success', False):
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "SUCCESS", f"Parsed {result.get('total_chapters', 0)} chapters, {result.get('total_chunks', 0)} chunks, {result.get('total_words', 0)} words")
            return True
        else:
            log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"Parse failed: {result.get('error', 'Unknown')}")
            return False
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP1_parsing", "ERROR", f"Exception: {str(e)}")
        return False


def execute_step2_metadata(audiobook_dict: dict) -> bool:
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
            return True
        else:
            log_and_print(audiobook_id, book_id, "STEP2_metadata", "ERROR", "Failed to add metadata to first chunk")
            return False
        
    except Exception as e:
        log_and_print(audiobook_id, book_id, "STEP2_metadata", "ERROR", f"Exception: {str(e)}")
        return False


if __name__ == "__main__":
    main()