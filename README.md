# E3 ComfyUI Agent

Monitors folders for YAML configs → Queues in SQLite → Executes via ComfyUI API → Saves outputs.

## Prerequisites
- Python 3.9+
- ComfyUI running at http://127.0.0.1:8000
- Web ui  running at http://127.0.0.1:8080
- uv package manager: `pip install uv`

## Environment Configuration

E3 uses a clean, centralized configuration system supporting multiple environments:

### **Configuration Structure**
```
E3/
├── .env                    # Infrastructure settings (API keys, hosts)
├── config/
│   ├── global_alpha.yaml  # Alpha environment config  
│   └── global_prod.yaml   # Production environment config
├── comfyui_jobs/           # ComfyUI Agent job processing
│   ├── processing/         # Input job files (YAML configs)
│   └── finished/           # Generated outputs
├── foundry/                # Book-centric content management
│   ├── pg98/              # Project Gutenberg book 98
│   │   ├── input.html     # Original book file
│   │   ├── audiobook/     # Audio files, chapters, metadata
│   │   ├── images/        # Book illustrations, covers
│   │   └── videos/        # Future: video adaptations
│   └── pg123/             # Another book...
└── initialize.py           # Environment setup script
```

### **Setup Steps**
1. Copy `.env.example` to `.env`
2. Set `E3_ENV=alpha` for development or `E3_ENV=prod` for production  
3. Run `python initialize.py` - automatically uses correct config and database

### **Environment Differences**
- **Alpha**: `database/alpha_e3_agent.db`, `logs/e3_alpha.log`
- **Production**: `database/e3_agent.db`, `logs/e3_prod.log`
- **Cross-platform**: Works on Windows, Linux, Mac, and EC2
- **Clean separation**: `comfyui_jobs/` for ComfyUI agent, `foundry/` for books

### **Book-Centric Architecture**
E3 uses a scalable, content-first approach for media management:

- **Each book gets its own folder** under `foundry/` (e.g., `foundry/pg98/`)
- **Book ID as folder name** - typically Project Gutenberg IDs like `pg98`, `pg123`
- **All book assets in one place** - audiobooks, images, videos, and metadata
- **Extensible design** - easy to add new media types (`movies/`, `podcasts/`, `games/`)
- **Netflix-style content management** - each book becomes a complete media franchise
- **Simple operations** - backup, share, or delete entire book by folder
- **Future-ready** - supports multi-format adaptations of the same source content

### **Configuration Philosophy**
- **`.env`** = Infrastructure (API keys, hosts, ports) - what changes between deployments
- **`config/global_*.yaml`** = Application logic (timeouts, paths, settings) - what stays consistent
- **Environment interpolation**: `api_base_url: "http://${COMFYUI_HOST}:${COMFYUI_PORT}"`

## Windows Setup (Command Prompt)
```cmd
# 1. Clean up old venv if exists
rmdir /s /q .venv

# 2. Create new virtual environment
uv venv

# 3. Activate venv (Windows)
.venv\Scripts\activate

# 4. Install requirements
uv pip install -r requirements.txt

# 5. Install package
uv pip install -e .

# 6. Initialize environment and database
python initialize.py
```

## Linux/WSL Setup
```bash
# Create and activate venv
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
python initialize.py
```

## Start ComfyUI (Required)
```cmd
# In your ComfyUI directory:
python main.py --port 8000
```

## Run E3 Agent

### Windows (Command Prompt)
```cmd
# Make sure venv is activated first!
.venv\Scripts\activate

# Start all services:
python -m comfyui_agent.cli start --ui-port 8081

# Or run separately:
python -m comfyui_agent.cli monitor    # Terminal 1: Monitor
python -m comfyui_agent.cli run        # Terminal 2: Executor
python -m comfyui_agent.ui_server 8080 # Terminal 3: Web UI
```

### Linux/WSL
```bash
source .venv/bin/activate
python -m comfyui_agent.cli start --ui-port 8080
```

## Run Audiobook Agent

### Check Titles Status
```bash
# Activate virtual environment first
source .venv/bin/activate  # Linux/WSL
# OR
.venv\Scripts\activate     # Windows

# Check audiobook titles and completion status
python audiobook_agent/audiobook_cli.py
```

### Add Test Book to Database
```sql
-- Connect to database and add a test book
sqlite3 database/alpha_e3_agent.db
INSERT INTO titles (
    book_id, title, author, genre, language, 
    audiobook_complete, created_at, updated_at
) VALUES (
    'pg74',
    'The Adventures of Tom Sawyer', 
    'Mark Twain',
    'fiction',
    'en',
    false,
    datetime('now'),
    datetime('now')
);
.quit
```

## Submit Job
Copy a sample YAML to processing folder:

**Windows:**
```cmd
copy samples\test_job_t2i.yaml comfyui_jobs\processing\image\
```

**Linux/WSL:**
```bash
cp samples/test_job_t2i.yaml comfyui_jobs/processing/image/
```

The system will automatically:
1. Detect the file
2. Queue it in database
3. Send to ComfyUI
4. Save output to `comfyui_jobs/finished/image/`

## Web UI
Open http://localhost:8080 to:
- View job queue
- See completed/failed jobs
- Retry failed jobs
- Adjust priorities

## Database Management

### Adding New Books to Audiobook Pipeline

To add a new book to the audiobook processing pipeline, use this SQL template:

```sql
INSERT INTO audiobook_processing (
    book_id, book_title, author, narrated_by, input_file, narrator_audio,
    created_at, updated_at
) VALUES (
    'pg12345',                    -- Unique book ID (usually Project Gutenberg ID)
    'The Book Title',             -- Full title of the book
    'Author Name',                -- Author's name
    'Narrator Name',              -- Name of the narrator
    'foundry/input/pg12345.html', -- Path to input file (must exist)
    'D:\Projects\pheonix\prod\E3\E3\audio_samples\voice_sample.mp3', -- Voice sample path
    datetime('now'),              -- Creation timestamp
    datetime('now')               -- Update timestamp
);
```

### Field Requirements

**Required Fields:**
- `book_id`: Unique identifier (e.g., "pg12345" for Project Gutenberg book 12345)
- `book_title`: Complete title of the book
- `input_file`: Path to the source file (HTML, TXT, etc.) - **file must exist**
- `created_at`: Timestamp (use `datetime('now')`)
- `updated_at`: Timestamp (use `datetime('now')`)

**Optional but Recommended:**
- `author`: Author's full name
- `narrated_by`: Narrator's name for TTS
- `narrator_audio`: Path to voice sample file for TTS generation

### Usage Example

```bash
# Connect to database and add a book
python3 -c "
import sqlite3
conn = sqlite3.connect('database/audiobook.db')
cursor = conn.cursor()
cursor.execute('''
    INSERT INTO audiobook_processing (
        book_id, book_title, author, narrated_by, input_file, narrator_audio,
        created_at, updated_at
    ) VALUES (
        'pg11870',
        'The Country of the Blind, and Other Stories',
        'H. G. WELLS',
        'Rowan Whitmore',
        'foundry/input/pg11870.html',
        'D:\\Projects\\pheonix\\prod\\E3\\E3\\audio_samples\\toireland_shelley_cf_128kb.mp3',
        datetime('now'),
        datetime('now')
    )
''')
conn.commit()
conn.close()
print('Book added successfully!')
"
```

### Prerequisites
1. Input file must exist at the specified path
2. Voice sample file should exist for TTS generation
3. Ensure `foundry/input/` directory exists
4. Book ID should be unique in the database

## Development Environment Setup (Windows)

### Setting Up a Separate Dev Environment

To experiment safely without affecting your production setup:

#### 1. Install Prerequisites (Windows)
```cmd
# Install Python 3.9+ from python.org if not already installed
python --version

# Install uv package manager
pip install uv
```

#### 2. Clone to Dev Directory
```cmd
# Navigate to your desired dev location
cd D:\Projects\pheonix\dev

# Clone the entire project
git clone D:\Projects\pheonix\prod\E3\E3 E3-dev
# OR copy if not using git
xcopy D:\Projects\pheonix\prod\E3\E3 E3-dev /E /I /H

cd E3-dev
```

#### 3. Create Fresh Virtual Environment
```cmd
# Remove any existing venv
if exist .venv rmdir /s /q .venv

# Create new virtual environment
uv venv

# Activate virtual environment
.venv\Scripts\activate

# Install all dependencies
uv pip install -r requirements.txt

# Install package in development mode
uv pip install -e .
```

#### 4. Initialize Dev Databases
```cmd
# Create database directory if it doesn't exist
if not exist database mkdir database

# Initialize ComfyUI database
python -c "from comfyui_agent.db_manager import init_db; init_db('database/comfyui_agent.db')"

# Copy production audiobook database (optional - for testing with existing data)
copy D:\Projects\pheonix\prod\E3\E3\database\audiobook.db database\audiobook.db

# OR create fresh audiobook database - this will be created automatically when you run the pipeline
```

#### 5. Create Required Directories
```cmd
# Create essential directories
if not exist foundry\input mkdir foundry\input
if not exist foundry\processing mkdir foundry\processing
if not exist foundry\finished mkdir foundry\finished
if not exist jobs\processing\speech mkdir jobs\processing\speech
if not exist jobs\processing\image mkdir jobs\processing\image
if not exist jobs\finished\speech mkdir jobs\finished\speech
if not exist jobs\finished\image mkdir jobs\finished\image
if not exist audio_samples mkdir audio_samples
```

#### 6. Environment Configuration
```cmd
# Copy sample environment file if it exists
if exist .env.example copy .env.example .env

# Edit .env file with your settings:
# - API keys
# - ComfyUI endpoint
# - Audio sample paths
```

#### 7. Test Your Dev Environment
```cmd
# Verify virtual environment is active (should show .venv in prompt)
where python
# Should point to: D:\Projects\pheonix\dev\E3-dev\.venv\Scripts\python.exe

# Test ComfyUI agent
python -m comfyui_agent.cli --help

# Test audiobook pipeline
python generate_audiobook.py
```

#### 8. Dev vs Prod Differences
Your dev environment is now completely separate:
- **Dev Path**: `D:\Projects\pheonix\dev\E3-dev\`
- **Prod Path**: `D:\Projects\pheonix\prod\E3\E3\`
- **Separate databases**: No risk of corrupting prod data
- **Separate virtual environments**: Independent package versions
- **Separate logs and outputs**: Easy to distinguish dev vs prod

#### 9. Keeping Dev Updated
```cmd
# To sync changes from prod to dev:
cd D:\Projects\pheonix\dev\E3-dev

# Copy specific files you want to update
copy D:\Projects\pheonix\prod\E3\E3\generate_audiobook.py .
copy D:\Projects\pheonix\prod\E3\E3\requirements.txt .

# Or sync entire directories (be careful with databases)
robocopy D:\Projects\pheonix\prod\E3\E3\comfyui_agent comfyui_agent /E
```

### Prerequisites
1. Input file must exist at the specified path
2. Voice sample file should exist for TTS generation
3. Ensure `foundry/input/` directory exists
4. Book ID should be unique in the database

## Troubleshooting

### "Connection refused" error
- Make sure ComfyUI is running: `python main.py --port 8000`
- Check the port in `comfyui_agent/config/global_config.yaml`

### "Access denied" on Windows
- Close any programs using the .venv folder
- Run `rmdir /s /q .venv` to clean up
- Try creating venv again

### WSL to Windows ComfyUI
If running E3 in WSL but ComfyUI on Windows:
- Start ComfyUI with: `python main.py --listen 0.0.0.0 --port 8000`
- See WSL_COMFYUI_SETUP.md for details




Notes for me:

for now I run below 2 .. will bundle later for nwo individual testing i need to run thse below commands
.venv\Scripts\activate

python initialize.py - only once
python -m comfyui_agent.cli start --ui-port 8081
python audiobook_agent/audiobook_cli.py
python gutenberg_agent/gutenberg_cli.py