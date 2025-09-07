## Audiobook Generation System - Database & File Structure Requirements

### Database Schema

### 1. **books** (Book Catalog Table)
Stores master book information and metadata.

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `id` | VARCHAR(14) | PRIMARY KEY | Format: YYYYMMDDHHMMSS (manually provided) |
| `book_id` | VARCHAR(20) | UNIQUE, NOT NULL | Alphanumeric identifier (e.g., pg1243, vdsr324, sadkf4524jk) |
| `book_name` | VARCHAR(255) | NOT NULL | Full title of the book |
| `author` | VARCHAR(255) | | Author name(s) |
| `language` | CHAR(3) | NOT NULL | ISO 639-2/T codes (eng, esp, fra, deu, etc.) |
| `year_published` | INTEGER | | Publication year |
| `genre` | VARCHAR(100) | | Book genre/category |
| `summary` | TEXT | | Brief book description |


### 2. **narrators** (Voice Talent Registry)
Maintains available narrator profiles and voice samples.

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `narrator_id` | VARCHAR(100) | PRIMARY KEY | Unique string (e.g., firstname_lastname) |
| `narrator_name` | VARCHAR(255) | NOT NULL | Full display name |
| `gender` | VARCHAR(20) | | Voice gender classification |
| `sample_filepath` | VARCHAR(500) | | Path to voice sample file |
| `language` | CHAR(3) | NOT NULL | Primary language (ISO 639-2/T) |
| `accent` | VARCHAR(50) | | Accent description (optional) |


### 3. **audiobook_productions** (Audiobook Generation Master)
Central table tracking audiobook creation requests and status.

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `audiobook_id` | VARCHAR(14) | PRIMARY KEY | Format: YYYYMMDDHHMMSS |
| `book_id` | VARCHAR(20) | FOREIGN KEY | References books.book_id |
| `narrator_id` | VARCHAR(100) | FOREIGN KEY | References narrators.narrator_id |
| `language` | CHAR(3) | NOT NULL | Target audiobook language |
| `status` | ENUM | NOT NULL | Values: 'pending', 'processing', 'failed', 'success' |
| `publish_date` | TIMESTAMP | | When audiobook was made public/uploaded |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Request creation time |
| `updated_at` | TIMESTAMP | ON UPDATE CURRENT_TIMESTAMP | Last status update |

### 4. **audiobook_process_events** (Processing Pipeline Tracker)
Logs each step in the audiobook generation pipeline.

| Column | Data Type | Constraints | Description |
|--------|-----------|-------------|-------------|
| `audiobook_id` | VARCHAR(14) | COMPOSITE KEY | References audiobook_productions.audiobook_id |
| `timestamp` | TIMESTAMP | COMPOSITE KEY | Event occurrence time (with milliseconds) |
| `step_number` | VARCHAR(100) | NOT NULL | Sequential step order (STEP1, 2, 3, ...) |
| `status` | ENUM | NOT NULL | Values: 'pending', 'processing', 'failed', 'success' |
|



## Implementation Notes

### Primary Keys
- Using YYYYMMDDHHMMSS format allows chronological ordering and uniqueness
- For `audiobook_process_events`, combine `timestamp` (with milliseconds) + `audiobook_id` for uniqueness

### Status Values
- `pending`: Awaiting processing
- `processing`: Currently being processed
- `failed`: Error occurred, check error_message
- `success`: Completed successfully

### Language Codes
Use ISO 639-2/T three-letter codes:
- `eng` - English
- `esp` - Spanish
- `fra` - French
- `deu` - German
- `ita` - Italian
- `por` - Portuguese
- `rus` - Russian
- `jpn` - Japanese
- `zho` - Chinese

### Folder Naming Conventions
- Keep folder names lowercase
- Use underscores in filenames, not spaces
- Include book_id in all generated filenames for traceability
- Maintain consistent naming patterns

### Process Steps (Example Pipeline)
Example sequence for `audiobook_process_events.step_name`:
1. `text_extraction` - Extract text from source file
2. `chapter_detection` - Identify chapter boundaries
3. `text_preprocessing` - Clean and prepare text
4. `audio_generation` - Generate audio with TTS
5. `audio_processing` - Post-process audio (normalize, enhance)
6. `final_compilation` - Combine chapters into single file
7. `quality_check` - Verify output quality
8. `publishing` - Upload/make public

### Directory Creation
Ensure these directories exist before processing:
- `foundry/` - Main processing directory
- `logs/` - Logging directory

Subdirectories are created dynamically during processing based on book_id and language.




### SQL Commands for Testing Data

#### 1. Add a Book to books Table
```sql
INSERT INTO books (
    id, book_id, book_name, author, language, year_published, genre, summary
) VALUES (
    '20250907120000',  -- YYYYMMDDHHMMSS format
    'pg74', 
    'The Adventures of Tom Sawyer',
    'Mark Twain',
    'eng',
    1876,
    'fiction',
    'Classic American novel about a young boy growing up along the Mississippi River'
);
```

#### 2. Add a Narrator to narrators Table
```sql
INSERT INTO narrators (
    narrator_id, narrator_name, gender, sample_filepath, language, accent
) VALUES (
    'rowan_whitmore',
    'Rowan Whitmore', 
    'male',
    'audio_samples/toireland_shelley_cf_128kb.mp3',
    'eng',
    'british'
);
```

#### 3. Add Audiobook Production Request
```sql
INSERT INTO audiobook_productions (
    audiobook_id, book_id, narrator_id, language, status, created_at, updated_at
) VALUES (
    '20250907120100',  -- YYYYMMDDHHMMSS format
    'pg74',
    'rowan_whitmore',
    'eng', 
    'pending',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);
```

#### 4. Verify Data Setup
```sql
-- Check all tables have data
SELECT * FROM books;
SELECT * FROM narrators;  
SELECT * FROM audiobook_productions;

-- Check relationships
SELECT b.book_name, n.narrator_name, ap.status
FROM audiobook_productions ap
JOIN books b ON ap.book_id = b.book_id  
JOIN narrators n ON ap.narrator_id = n.narrator_id;
```

#### 5. Check Processing Queue
```sql
-- Find books that need audiobook processing
SELECT b.book_id, b.book_name, b.author, ap.status
FROM books b
LEFT JOIN audiobook_productions ap ON b.book_id = ap.book_id
ORDER BY b.id;
```


# STEP Progression 

## STEP 0: Processing Queue Management

### Purpose
Identify and display all audiobook production requests that need processing.

### Logic
```sql
-- Get all incomplete audiobook productions
SELECT ap.audiobook_id, ap.book_id, ap.narrator_id, ap.status, 
       b.book_name, b.author, n.narrator_name
FROM audiobook_productions ap
JOIN books b ON ap.book_id = b.book_id
JOIN narrators n ON ap.narrator_id = n.narrator_id  
WHERE ap.status != 'success'  -- pending, processing, or failed
ORDER BY ap.audiobook_id;  -- Process by creation order (YYYYMMDDHHMMSS)
```

### Output Display
Show each incomplete production with:
- Audiobook ID (YYYYMMDDHHMMSS format)
- Book information (ID, title, author)
- Narrator assignment  
- Current status (pending/processing/failed)
- Processing priority (oldest first)

### Success Criteria
- Display all non-success productions
- Show clear processing queue with priorities
- Identify which step each production needs next

---

## STEP 1: Parse Novel Content

### Purpose
Extract chapters and text chunks from HTML source file for TTS processing.

### Logic
```python
# 1. Find input HTML file in foundry/{book_id}/ using pattern *{book_id}*.html
# 2. Create output directory: foundry/{book_id}/{language}/chapters/
# 3. Call parse_novel_tts.parse_novel() function
# 4. Save parsed chapters as individual JSON files
```

### Input Requirements
- HTML source file in foundry/{book_id}/ directory
- Language code from audiobook_productions.language
- Valid book structure with chapter anchors

### Output Structure
```
foundry/{book_id}/{language}/chapters/
├── metadata.json      # Book metadata and chapter summary
├── chapter_001.json   # Individual chapter with text chunks
├── chapter_002.json
└── ...
```

### Success Criteria
- Parse HTML into structured chapters
- Extract actual paragraph content (not just titles)
- Create TTS-ready text chunks
- Update event: STEP1_parsing → 'success'
- Queue next step: STEP2_metadata → 'pending'

### Error Conditions
- HTML file not found
- Parse failure (no chapters detected)
- File write errors
- Update event: STEP1_parsing → 'failed'

---

## STEP 2: Add Book Metadata to First Chunk

### Purpose
Enhance the first audio chunk with book introduction metadata for professional audiobook presentation.

### Logic
```python
# 1. Load chapter_001.json from foundry/{book_id}/{language}/chapters/
# 2. Extract first chunk text from first chapter
# 3. Prepend book metadata: "{book_name} by {author}, narrated by {narrator_name}, "
# 4. Update chunk text and char_count
# 5. Save modified chapter_001.json
```

### Input Requirements
- Completed STEP1_parsing (chapter_001.json exists)
- Book metadata from audiobook_productions join (book_name, author, narrator_name)
- Valid chapter structure with chunks array

### Output Modification
```json
{
  "chapter": {
    "chunks": [
      {
        "chunk_id": 1,
        "text": "The Adventures of Tom Sawyer by Mark Twain, narrated by Rowan Whitmore, [original first chunk text...]",
        "char_count": 520  // Updated count
      }
    ]
  }
}
```

### Success Criteria
- Locate first chapter JSON file successfully
- Add metadata prefix to first chunk text
- Update char_count with new text length
- Save modified file without corruption
- Update event: STEP2_metadata → 'success'
- Queue next step: STEP3_create_audio_jobs → 'pending'

### Error Conditions
- chapter_001.json file not found
- Invalid JSON structure (no chunks)
- File write permission errors
- Update event: STEP2_metadata → 'failed'

---

## STEP 3: Create TTS Audio Jobs

### Purpose
Convert parsed chapter JSON files into TTS job YAML configurations for ComfyUI processing.

### Logic
```python
# 1. Read chapter JSON files from foundry/{book_id}/{language}/chapters/
# 2. Extract text chunks for TTS processing
# 3. Create YAML job configs using narrator voice sample
# 4. Save job files to comfyui_jobs/processing/speech/
# 5. Use create_tts_audio_jobs.create_tts_jobs() function
```

### Input Requirements
- Completed STEP2_metadata (enhanced chapter JSON files)
- Chapter files in foundry/{book_id}/{language}/chapters/
- Narrator voice sample file path from audiobook_dict['sample_filepath']
- Valid ComfyUI job output directories

### Output Structure
```
comfyui_jobs/processing/speech/
├── SPEECH_{book_id}_001.yaml    # TTS job for chunk 1
├── SPEECH_{book_id}_002.yaml    # TTS job for chunk 2  
└── ...                          # Job files for all chunks
```

### Success Criteria
- Read all chapter JSON files successfully
- Create TTS job YAML configs for all text chunks
- Use correct narrator voice sample path
- Save job files to ComfyUI processing directory
- Update event: STEP3_create_audio_jobs → 'success'
- Queue next step: STEP4_monitor_audio → 'pending'

### Error Conditions
- Chapter JSON files not found
- Invalid chapter file structure
- Voice sample file missing
- Job file creation/write errors
- Update event: STEP3_create_audio_jobs → 'failed' 

---

## STEP 4: Monitor and Move Audio Files

### Purpose
Monitor ComfyUI TTS job completion and move generated audio files to foundry directory structure.

### Logic
```python
# 1. Query comfyui_jobs table for job status counts by book_id
# 2. Check if all jobs are 'done' (no pending/processing jobs remaining)  
# 3. If jobs still running: return "processing" and wait for next cycle
# 4. If all done: move audio files from ComfyUI output to foundry/{book_id}/{language}/speech/
# 5. Update event status accordingly
```

### Input Requirements
- Completed STEP3_create_audio_jobs (TTS jobs created)
- ComfyUI jobs in database with config_name containing book_id
- ComfyUI output files in D:/Projects/pheonix/dev/output/speech/alpha/{book_id}*

### Output Structure
```
foundry/{book_id}/{language}/speech/
├── audio_file_001.wav    # Moved from ComfyUI output
├── audio_file_002.wav    # Generated audio files
└── ...                   # All completed audio files
```

### Success Criteria
- Query ComfyUI job status successfully
- All TTS jobs completed (status = 'done')
- Audio files moved from ComfyUI output to foundry structure
- Update event: STEP4_monitor_and_move_audio → 'success'
- Queue next step: STEP5_combine_audio → 'pending'

### Wait Conditions
- Jobs still pending or processing
- Log waiting status but don't update database
- Return "processing" to indicate still waiting

### Error Conditions  
- No ComfyUI jobs found for book_id
- All jobs failed with no successful completions
- Audio file moving errors
- Update event: STEP4_monitor_and_move_audio → 'failed'

---

## STEP 5: Plan and Combine Audio Files

### Purpose
Two-phase process: 1) Analyze total duration and create optimal combination plan, 2) Execute audio combination based on the plan.

### Logic
```python
# Phase 1: Planning
# 1. Analyze individual chapter audio files for duration using ffprobe
# 2. Calculate total audiobook duration 
# 3. If > 10 hours: Create multi-part plan with smart chapter distribution
# 4. If ≤ 10 hours: Create single-part plan

# Phase 2: Combination
# 5. Access audio files in foundry/{book_id}/{language}/speech/ folder structure
# 6. Use ffmpeg to combine chunks within each chapter sequentially 
# 7. Combine chapters into final audiobook file(s) according to the plan
# 8. Generate YouTube timestamps and metadata files
```

### Input Requirements
- Completed STEP4_monitor_and_move_audio (audio files in foundry structure)
- Audio files in `foundry/{book_id}/{language}/speech/ch001/chunk001/audio_*.flac`
- Chapter metadata from STEP1 parsing in `foundry/{book_id}/{language}/chapters/`
- ffmpeg and ffprobe installed and accessible in system PATH

### Output Structure
```
foundry/{book_id}/{language}/combined_audio/
├── chapters/
│   ├── chapter_001.mp3           # Individual chapter files
│   ├── chapter_002.mp3
│   └── ...
├── {book_id}_full_book.mp3       # Single file (if ≤ 10h)
OR
├── {book_id}_part1.mp3           # Multi-part files (if > 10h)
├── {book_id}_part2.mp3
├── youtube_timestamps_part1.txt  # YouTube chapter timestamps
├── chapter_info_part1.json       # Chapter metadata JSON
└── ...
```

### Success Criteria
- Duration analysis completed successfully
- Optimal combination plan created (single vs multi-part)
- All chapter folders processed successfully
- Individual chapter audio files created
- Final audiobook file(s) generated according to plan
- YouTube timestamps and metadata files created
- Update event: STEP5_combine_audio → 'success'
- Queue next step: STEP6_generate_subtitles → 'pending'

### Error Conditions
- Duration analysis fails (ffprobe errors)
- No audio files found in speech directory
- ffmpeg not installed or not accessible
- Audio file corruption or format issues
- Insufficient disk space for output files
- Update event: STEP5_combine_audio → 'failed'

---

## STEP 6: Generate Subtitles

### Purpose
Generate SRT subtitle files for audiobook parts based on combination plan and audio timing.

### Logic
```python
# 1. Read combination_plan.json to know which chapters belong to which parts
# 2. For each part, generate subtitles using text chunks and audio timing
# 3. Create SRT files matching the audio structure (single or multi-part)
# 4. Update combination_plan.json with subtitle file paths
```

### Input Requirements
- Completed STEP5_combine_audio (combination plan and chapter structure)
- combination_plan.json with audio paths and part information
- Text chunks from STEP1 parsing in foundry/{book_id}/{language}/chapters/
- Audio files with timing information

### Output Structure
```
foundry/{book_id}/{language}/subtitles/
├── {book_id}_full_book.srt       # Single part subtitle
OR
├── {book_id}_part1.srt           # Multi-part subtitles
├── {book_id}_part2.srt
└── ...
```

### Success Criteria
- Read combination plan successfully
- Generate accurate SRT timing for each part
- Create subtitle files matching audio part structure
- Update combination_plan.json with subtitle_path for each part
- Update event: STEP6_generate_subtitles → 'success'
- Queue next step: STEP7_generate_image_prompts → 'pending'

### Error Conditions
- combination_plan.json not found
- Subtitle generation function errors
- File write permission errors
- Update event: STEP6_generate_subtitles → 'failed'

---

## STEP 7: Generate Image Prompts

### Purpose
Generate AI image prompts for audiobook thumbnail creation, handling both single and multi-part scenarios.

### Logic
```python
# 1. Read combination_plan.json to understand part structure
# 2. Generate cinematic image prompts for each audiobook part
# 3. For multi-part: include part information in prompts
# 4. Save image prompts to foundry structure
# 5. Update combination_plan.json with image prompt file paths
```

### Input Requirements
- Completed STEP6_generate_subtitles (combination plan with subtitle paths)
- combination_plan.json with part and chapter information
- Book metadata (title, author, narrator) for prompt context
- Access to AI prompt generation models

### Output Structure
```
foundry/{book_id}/{language}/image_prompts/
├── {book_id}_prompts.json        # Single part prompts
OR
├── {book_id}_part1_prompts.json  # Multi-part prompts
├── {book_id}_part2_prompts.json
└── ...
```

### Success Criteria
- Read combination plan successfully
- Generate 5+ high-quality image prompts per part
- Handle part-specific titles for multi-part books
- Save prompts in foundry structure
- Update combination_plan.json with image_prompts_path for each part
- Update event: STEP7_generate_image_prompts → 'success'
- Queue next step: STEP8_create_image_jobs → 'pending'

### Error Conditions
- combination_plan.json not found
- AI model access errors
- Image prompt generation failures
- File write permission errors
- Update event: STEP7_generate_image_prompts → 'failed'

---

## STEP 8: Create Image Jobs

### Purpose
Convert image prompts into ComfyUI job configurations for image generation processing.

### Logic
```python
# 1. Read combination_plan.json and image prompt files
# 2. For each part, read generated image prompts
# 3. Create ComfyUI YAML job files for each prompt
# 4. Organize jobs in comfyui_jobs/processing/image/ directory
# 5. Configure correct output paths with environment (alpha)
```

### Input Requirements
- Completed STEP7_generate_image_prompts (image prompt files)
- Image prompts in foundry/{book_id}/{language}/image_prompts/
- ComfyUI workflow template (workflows/image_qwen_image.json)
- Access to ComfyUI job processing directories

### Output Structure
```
comfyui_jobs/processing/image/
├── T2I_{book_id}_1_prompt001.yaml    # Image job for part 1, prompt 1
├── T2I_{book_id}_1_prompt002.yaml    # Image job for part 1, prompt 2
├── T2I_{book_id}_2_prompt001.yaml    # Multi-part: part 2 jobs
└── ...

# Output path in jobs: images/alpha/{book_id}/part1/prompt1
```

### Success Criteria
- Read combination plan and image prompts successfully
- Create ComfyUI job YAML files for all prompts
- Jobs organized in /image subfolder for proper ComfyUI processing
- Configure correct output paths with environment (alpha)
- Update event: STEP8_create_image_jobs → 'success'
- Queue next step: STEP9_monitor_and_move_images → 'pending'

### Error Conditions
- Image prompt files not found
- ComfyUI workflow template missing
- Job file creation/write errors
- Update event: STEP8_create_image_jobs → 'failed'

---

## STEP 9: Monitor and Move Images

### Purpose
Monitor ComfyUI image job completion and move generated images to foundry structure.

### Logic
```python
# 1. Query comfyui_jobs table for T2I_{book_id} job status counts
# 2. Check if all image jobs are 'done' (no pending/processing jobs remaining)  
# 3. If jobs still running: return "processing" and wait for next cycle
# 4. If all done: move images from ComfyUI output to foundry/{book_id}/{language}/images/
# 5. Update event status accordingly
```

### Input Requirements
- Completed STEP8_create_image_jobs (ComfyUI image jobs created)
- ComfyUI jobs in database with config_name matching T2I_{book_id} pattern
- ComfyUI output files in D:/Projects/pheonix/dev/output/images/alpha/{book_id}/

### Output Structure
```
foundry/{book_id}/{language}/images/
├── part1/
│   ├── prompt1_00001_.png        # Moved from ComfyUI output
│   ├── prompt2_00001_.png        # Generated image files
│   └── ...
├── part2/                        # Multi-part: additional part folders
└── ...
```

### Success Criteria
- Query ComfyUI image job status successfully (T2I pattern)
- All image generation jobs completed (status = 'done')
- Image files moved from ComfyUI output to foundry structure
- Update event: STEP9_monitor_and_move_images → 'success'
- Queue next step: STEP10_select_image → 'pending'

### Wait Conditions
- Jobs still pending or processing
- Log waiting status but don't update database
- Return "processing" to indicate still waiting

### Error Conditions  
- No ComfyUI image jobs found for book_id
- All jobs failed with no successful completions
- Image file moving errors
- Update event: STEP9_monitor_and_move_images → 'failed'

---

## STEP 10: Select Images

### Purpose
Select one thumbnail image per audiobook part for video generation from generated images.

### Logic
```python
# 1. Read combination_plan.json to understand part structure
# 2. For each part, scan foundry/{book_id}/{language}/images/part{X}/ directory
# 3. Randomly select one image file per part (future: ML-based selection)
# 4. Update combination_plan.json with selected_image_path for each part
```

### Input Requirements
- Completed STEP9_monitor_and_move_images (images in foundry structure)
- Images organized in foundry/{book_id}/{language}/images/part{X}/ directories
- combination_plan.json with part structure information

### Output Updates
```json
// Updated combination_plan.json
"combinations": [
  {
    "part": 1,
    "audio_path": "foundry/{book_id}/{language}/combined_audio/{book_id}_part1.mp3",
    "subtitle_path": "foundry/{book_id}/{language}/subtitles/{book_id}_part1.srt",
    "image_prompts_path": "foundry/{book_id}/{language}/image_prompts/{book_id}_part1_prompts.json",
    "selected_image_path": "foundry/{book_id}/{language}/images/part1/prompt3_00001_.png"
  }
]
```

### Success Criteria
- Read combination plan and locate image directories successfully
- Select one image per part (random selection for now)
- Update combination_plan.json with selected_image_path fields
- Handle both single-part and multi-part scenarios
- Update event: STEP10_select_image → 'success'
- Queue next step: STEP11_generate_video → 'pending'

### Error Conditions
- No images found in part directories
- combination_plan.json read/write errors
- Random selection function errors
- Update event: STEP10_select_image → 'failed'