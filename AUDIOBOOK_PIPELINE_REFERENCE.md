# 📚 AUDIOBOOK PIPELINE REFERENCE GUIDE

> **Complete step-by-step reference for audiobook production automation**

---

## 🔄 STEP 0: QUEUE MANAGEMENT & PROCESSING ORDER

**Purpose:** Query database for incomplete audiobook productions and establish processing order

**Input:**
- Database query: `audiobook_productions` table where `status != 'success'`

**Process:**
1. Execute `get_processing_queue()` from helper
2. Sort queue by `audiobook_id` (YYYYMMDDHHMMSS format - chronological order)
3. Display queue contents with book/author details
4. Initialize event tracking for books without events

**Output:**
- Processing queue sorted chronologically
- Initial `STEP1_parsing` events for new books

**Status Flow:**
- `STARTING` → `SUCCESS` (queue retrieved)
- `INFO` (individual book details)

**Dependencies:** SQLite database, audiobook_helper.py

---

## 📖 STEP 1: HTML NOVEL PARSING

**Purpose:** Extract chapters and text chunks from Project Gutenberg HTML files

**Input:**
- HTML file: `foundry/{book_id}/*{book_id}*.html`
- Language code (default: 'eng')

**Process:**
1. Locate HTML file using glob pattern
2. Create output directory: `foundry/{book_id}/{language}/chapters`
3. Call `parse_novel()` from `parse_novel_tts.py`
4. Extract chapters using multiple strategies (anchor, div, h2, hierarchy)
5. Generate TTS-optimized chunks (400-500 characters)

**Output:**
- Individual chapter JSON files: `chapter_001.json`, `chapter_002.json`, etc.
- Metadata with chapter counts, word counts, chunk statistics

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP2_metadata` (on success)

**Dependencies:** parse_novel_tts.py, BeautifulSoup, HTML parsing

**Error Conditions:**
- HTML file not found in foundry directory
- Parsing errors (malformed HTML, no chapter structure)
- File system permissions

---

## 📝 STEP 2: METADATA ENHANCEMENT

**Purpose:** Add book title, author, and narrator information to the first audio chunk

**Input:**
- Parsed chapter files from STEP 1
- Book metadata: title, author, narrator name

**Process:**
1. Call `add_book_metadata_to_first_chunk()` from helper
2. Enhance first chunk with introductory text
3. Format: "This is [book_name] by [author], narrated by [narrator_name]"

**Output:**
- Modified first chapter file with enhanced introduction
- Updated metadata.json

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP3_create_audio_jobs` (on success)

**Dependencies:** audiobook_helper.py, file system access

**Error Conditions:**
- Missing chapter files from STEP 1
- File write permissions
- Missing book metadata

---

## 🎤 STEP 3: TTS JOB CREATION

**Purpose:** Convert parsed chapter JSON files into ComfyUI TTS job configurations

**Input:**
- Chapter files: `foundry/{book_id}/{language}/chapters/`
- Voice sample file path from narrator configuration
- Complete audiobook metadata dictionary

**Process:**
1. Call `create_tts_jobs()` from `create_tts_audio_jobs.py`
2. Generate YAML job files for ComfyUI processing
3. Configure voice cloning with narrator's sample file
4. Set up job queue for batch processing

**Output:**
- TTS job files: `comfyui_jobs/processing/speech/`
- Job configurations with voice samples and text chunks

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP4_monitor_and_move_audio` (on success)

**Dependencies:** create_tts_audio_jobs.py, ComfyUI job system, voice samples

**Error Conditions:**
- Missing chapter files
- Invalid voice sample path
- ComfyUI job directory access issues

---

## 🔊 STEP 4: AUDIO MONITORING & MOVEMENT

**Purpose:** Monitor ComfyUI TTS job completion and organize generated audio files

**Input:**
- ComfyUI job status from `comfyui_jobs/processing/speech/`
- Generated audio files from ComfyUI output

**Process:**
1. Check job status: `get_comfyui_audio_job_status(book_id)`
2. Monitor pending/processing/done/failed counts
3. Wait for all jobs to complete (returns "processing" if still running)
4. Move completed audio files using `move_comfyui_audio_files()`

**Output:**
- Audio files organized: `foundry/{book_id}/{language}/speech/`
- File structure: `ch001/chunk001.wav`, `ch002/chunk001.wav`, etc.

**Status Flow:**
- `pending`/`failed` → `processing` → `WAITING` (if jobs still running) → `success`/`failed`
- Next step: `STEP5_combine_audio` (on success)

**Dependencies:** ComfyUI system, file system operations

**Error Conditions:**
- No ComfyUI jobs found
- All jobs failed with no successful completions
- File movement permissions

---

## 🎵 STEP 5: AUDIO COMBINATION & PLANNING

**Purpose:** Analyze duration and combine audio files into final audiobook parts

**Input:**
- Audio files: `foundry/{book_id}/{language}/speech/`
- Complete audiobook metadata dictionary

**Process:**
1. **Phase 1 - Planning:** Call `plan_audio_combinations()` to analyze duration
2. Determine if multi-part split needed (based on length limits)
3. **Phase 2 - Combination:** Execute `combine_audiobook_files()` with plan
4. Save combination plan: `foundry/{book_id}/{language}/combination_plan.json`

**Output:**
- Final audiobook files: `foundry/{book_id}/{language}/combined_audio/`
- Combination plan JSON with part details and durations
- Single file or multi-part structure based on length

**Status Flow:**
- `pending` → `processing` → `PLANNING` → `COMBINING` → `success`/`failed`
- Next step: `STEP6_generate_subtitles` (on success)

**Dependencies:** audiobook_helper.py, FFmpeg for audio processing

**Error Conditions:**
- Missing audio files from STEP 4
- FFmpeg processing errors
- Disk space issues for large files

---

## 📄 STEP 6: SUBTITLE GENERATION

**Purpose:** Generate subtitle/caption files for each audiobook part

**Input:**
- Combination plan: `combination_plan.json`
- Combined audio files from STEP 5
- Text content from original chapters

**Process:**
1. Read combination plan to understand part structure
2. Call `generate_subtitles_for_audiobook()` from helper
3. Generate subtitle timing based on audio duration
4. Create subtitle files for each part

**Output:**
- Subtitle files: `.srt` or `.vtt` format
- Updated combination plan with subtitle file paths

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP7_generate_image_prompts` (on success)

**Dependencies:** audiobook_helper.py, subtitle generation tools

**Error Conditions:**
- Missing combination plan
- Audio file access issues
- Text alignment problems

---

## 🖼️ STEP 7: IMAGE PROMPT GENERATION

**Purpose:** Generate AI image prompts for audiobook thumbnail creation

**Input:**
- Combination plan with part structure
- Book metadata (title, author, genre)
- Text content for context

**Process:**
1. Read combination plan to understand parts needed
2. Call `generate_image_prompts_for_audiobook()` from helper
3. Generate contextual prompts based on book content
4. Create prompts for thumbnail images per part

**Output:**
- Image prompt files per part
- Updated combination plan with prompt file paths

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP8_create_image_jobs` (on success)

**Dependencies:** audiobook_helper.py, AI prompt generation

**Error Conditions:**
- Missing combination plan
- Content analysis failures
- Prompt file write issues

---

## 🎨 STEP 8: IMAGE JOB CREATION

**Purpose:** Create ComfyUI job files for AI image generation

**Input:**
- Image prompts from STEP 7
- Combination plan structure
- Image generation parameters

**Process:**
1. Read image prompts for each part
2. Call `create_image_jobs_for_audiobook()` from helper
3. Generate ComfyUI YAML job files
4. Configure image generation settings (size, style, etc.)

**Output:**
- Image job files: `comfyui_jobs/processing/image/`
- Job queue for ComfyUI image generation

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP9_monitor_and_move_images` (on success)

**Dependencies:** audiobook_helper.py, ComfyUI job system

**Error Conditions:**
- Missing image prompts
- ComfyUI job directory issues
- Invalid job configurations

---

## 🖼️ STEP 9: IMAGE MONITORING & MOVEMENT

**Purpose:** Monitor ComfyUI image job completion and organize generated images

**Input:**
- ComfyUI image job status
- Generated image files from ComfyUI output

**Process:**
1. Check image job status: `get_comfyui_image_job_status(book_id)`
2. Monitor pending/processing/done/failed counts
3. Wait for completion (returns "processing" if still running)
4. Move completed images using `move_comfyui_image_files()`

**Output:**
- Image files organized: `foundry/{book_id}/{language}/images/`
- Multiple image options per part for selection

**Status Flow:**
- `pending`/`failed` → `processing` → `WAITING` (if jobs still running) → `success`/`failed`
- Next step: `STEP10_select_image` (on success)

**Dependencies:** ComfyUI system, file operations

**Error Conditions:**
- No ComfyUI image jobs found
- All image jobs failed
- File movement permissions

---

## 🎯 STEP 10: IMAGE SELECTION

**Purpose:** Select final thumbnail images for each audiobook part

**Input:**
- Generated images: `foundry/{book_id}/{language}/images/`
- Combination plan structure

**Process:**
1. Read available images for each part
2. Call `select_images_for_audiobook()` from helper
3. Apply selection criteria (random, quality-based, etc.)
4. Update combination plan with selected image paths

**Output:**
- Updated combination plan with final image selections
- Selected images ready for video generation

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP11_generate_video` (on success)

**Dependencies:** audiobook_helper.py, image processing

**Error Conditions:**
- No images available for selection
- Image file access issues
- Selection algorithm failures

---

## 🎬 STEP 11: VIDEO GENERATION

**Purpose:** Combine audio files with selected images to create final videos

**Input:**
- Combined audio files from STEP 5
- Selected images from STEP 10
- Subtitle files from STEP 6
- Combination plan with all paths

**Process:**
1. Read combination plan with audio/image/subtitle paths
2. Call `generate_videos_for_audiobook()` from helper
3. Use FFmpeg to combine audio, image, and subtitles
4. Generate video file per part

**Output:**
- Video files: `foundry/{book_id}/{language}/videos/`
- MP4 format ready for YouTube upload

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Next step: `STEP12_upload_video_to_youtube` (on success)

**Dependencies:** audiobook_helper.py, FFmpeg video processing

**Error Conditions:**
- Missing audio/image/subtitle files
- FFmpeg processing errors
- Video encoding failures

---

## 📺 STEP 12: YOUTUBE UPLOAD

**Purpose:** Upload generated videos to YouTube with metadata and scheduling

**Input:**
- Video files from STEP 11
- Combination plan with metadata
- YouTube API credentials
- Publish date from database (optional)

**Process:**
1. Read combination plan and video files
2. Call `upload_videos_to_youtube()` from helper
3. Configure video metadata (title, description, tags)
4. Handle scheduling: `private` + `publishAt` (if scheduled) or `public` (immediate)
5. Upload each part to YouTube channel

**Output:**
- YouTube video IDs and URLs
- Updated combination plan with YouTube metadata
- Videos published or scheduled based on publish_date

**Status Flow:**
- `pending` → `processing` → `success`/`failed`
- Final step - audiobook production complete

**Dependencies:** YouTube API, Google OAuth, audiobook_helper.py

**Error Conditions:**
- Missing video files
- YouTube API authentication failures
- Upload quota exceeded
- Network connectivity issues

---

## 📊 STATUS CODES & TRANSITIONS

**Return Codes:**
- `"S"` - Success (move to next step)
- `"F"` - Failed (mark as failed, stop processing)
- `"P"` - Processing/Skip (don't change status)
- `"processing"` - Still running (wait for next cycle)

**Event Status Flow:**
```
pending → processing → success/failed
                    ↓
             (next step queued)
```

**Database States:**
- `pending` - Queued for execution
- `processing` - Currently running
- `success` - Completed successfully
- `failed` - Error occurred, needs attention

---

## 🔧 SYSTEM CONFIGURATION

**Continuous Mode:**
- Runs every 5 minutes (`LOOP_INTERVAL_MINUTES = 5`)
- Processes queue in chronological order
- Handles concurrent processing states

**Logging:**
- Daily rotating logs: `logs/audiobook.log`
- Format: `timestamp|audiobook_id|book_id|step|status|message`
- 10-day retention

**Directory Structure:**
```
foundry/{book_id}/
├── {book_id}-images.html      # Source HTML
├── {language}/
│   ├── chapters/              # STEP 1 output
│   ├── speech/               # STEP 4 output
│   ├── combined_audio/       # STEP 5 output
│   ├── images/               # STEP 9 output
│   ├── videos/               # STEP 11 output
│   └── combination_plan.json # STEP 5 planning
```

---

*This reference guide covers all 13 steps of the automated audiobook production pipeline. Each step is designed to be fault-tolerant with proper error handling and status tracking.*