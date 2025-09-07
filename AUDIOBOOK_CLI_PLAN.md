# Python Developer Context

You are an experienced Python developer building a scalable audiobook generation application. 

## Development Principles
- Write clean, type-hinted Python 3.11+ code
- Follow PEP 8 and best practices
- Use async/await for I/O operations
- Implement proper error handling and logging
- Create modular, testable code with clear separation of concerns
- Use descriptive names and add docstrings
- Think about edge cases and performance
- Prefer composition over inheritance
- Use design patterns where appropriate (Strategy, Factory, etc.)

## Code Style
- Type hints for all function parameters and returns
- Proper exception handling with specific exceptions
- Logging instead of print statements
- Small, focused functions
- Abstract base classes for extensibility
- Dependency injection for testability

When I describe features or requirements, implement them following these principles. Always think about maintainability, scalability, and code quality.



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