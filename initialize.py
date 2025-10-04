#!/usr/bin/env python3
"""
E3 Environment Initialization Script

Automatically detects environment from E3_ENV variable and initializes:
- Correct database with proper naming (alpha_comfyui_agent.db, comfyui_agent.db, etc.)
- Required directory structure for jobs and workflows
- Environment-specific configurations
- Database schema validation

Usage:
    python initialize.py

Environment is determined by E3_ENV variable in .env file or environment:
- E3_ENV=alpha → database/alpha_comfyui_agent.db
- E3_ENV=prod → database/comfyui_agent.db  
- No E3_ENV → database/comfyui_agent.db (default)
"""

import os
import sys
import sqlite3
from pathlib import Path
from typing import Optional

# Import shared utility
from comfyui_agent.utils.config_loader import load_env_file


def create_database_schema(db_path: str) -> None:
    """Create complete database schema for E3 system."""
    
    # Configure WAL mode for optimal performance
    with sqlite3.connect(db_path) as conn:
        # Enable WAL mode for concurrent readers + single writer
        conn.execute("PRAGMA journal_mode=WAL")
        # Increase cache size for better performance (10MB)
        conn.execute("PRAGMA cache_size=10000")
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")
        # Set synchronous to NORMAL for better performance
        conn.execute("PRAGMA synchronous=NORMAL")
        # Set WAL checkpoint size
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        # Additional read/write optimization
        conn.execute("PRAGMA read_uncommitted=TRUE")   # Allow dirty reads (faster)
        conn.execute("PRAGMA temp_store=MEMORY")       # Store temp tables in memory  
        conn.execute("PRAGMA mmap_size=268435456")     # 256MB memory mapping
        conn.commit()
    
    # Create all tables
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Create ComfyUI jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comfyui_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_name TEXT NOT NULL UNIQUE,
                job_type TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                priority INTEGER DEFAULT 50,
                status TEXT CHECK(status IN ('pending','processing','done','failed')) NOT NULL,
                run_count INTEGER DEFAULT 0,
                retries_attempted INTEGER DEFAULT 0,
                retry_limit INTEGER DEFAULT 2,
                start_time TEXT,
                end_time TEXT,
                duration REAL,
                error_trace TEXT,
                metadata TEXT,
                worker_id TEXT,
                lease_expires_at TEXT
            )
        """)
        
        # Create books table (Book Catalog from AUDIOBOOK_CLI_PLAN.md)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id VARCHAR(14) PRIMARY KEY,
                book_id VARCHAR(20) UNIQUE NOT NULL,
                book_name VARCHAR(255) NOT NULL,
                author VARCHAR(255),
                language CHAR(3) NOT NULL,
                year_published INTEGER,
                genre VARCHAR(100),
                summary TEXT
            )
        """)
        
        # Create narrators table (Voice Talent Registry from AUDIOBOOK_CLI_PLAN.md)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS narrators (
                narrator_id VARCHAR(100) PRIMARY KEY,
                narrator_name VARCHAR(255) NOT NULL,
                gender VARCHAR(20),
                sample_filepath VARCHAR(500),
                language CHAR(3) NOT NULL,
                accent VARCHAR(50)
            )
        """)
        
        # Create audiobook_productions table (Generation Master from AUDIOBOOK_CLI_PLAN.md)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audiobook_productions (
                audiobook_id VARCHAR(14) PRIMARY KEY,
                book_id VARCHAR(20) NOT NULL,
                narrator_id VARCHAR(100) NOT NULL,
                language CHAR(3) NOT NULL,
                status TEXT CHECK(status IN ('pending','processing','failed','success')) NOT NULL,
                publish_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(book_id),
                FOREIGN KEY (narrator_id) REFERENCES narrators(narrator_id)
            )
        """)
        
        # Create audiobook_process_events table (Pipeline Tracker from AUDIOBOOK_CLI_PLAN.md)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audiobook_process_events (
                audiobook_id VARCHAR(14) NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                step_number VARCHAR(100) NOT NULL,
                status TEXT CHECK(status IN ('pending','processing','failed','success')) NOT NULL,
                PRIMARY KEY (audiobook_id, timestamp),
                FOREIGN KEY (audiobook_id) REFERENCES audiobook_productions(audiobook_id)
            )
        """)

        # Create gutenberg_books table (Project Gutenberg Catalog with JSON support)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gutenberg_books (
                id INTEGER PRIMARY KEY,                    -- Project Gutenberg book ID (1342, 74, etc.)
                title TEXT NOT NULL,                       -- "Pride and Prejudice"
                raw_metadata JSON,                         -- Complete original JSON from catalog

                -- Extracted fields for fast queries (generated columns with STORED for performance)
                download_count INTEGER GENERATED ALWAYS AS (json_extract(raw_metadata, '$.download_count')) STORED,
                primary_author TEXT GENERATED ALWAYS AS (json_extract(raw_metadata, '$.authors[0].name')) STORED,
                language TEXT GENERATED ALWAYS AS (json_extract(raw_metadata, '$.languages[0]')) STORED,

                -- Timestamps for tracking
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_version TEXT DEFAULT 'v1'             -- Track weekly updates
            )
        """)

        # Create gutenberg_process_events table (Gutenberg CLI Pipeline Tracker)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gutenberg_process_events (
                timestamp TIMESTAMP NOT NULL,
                step_name VARCHAR(100) NOT NULL,
                status TEXT CHECK(status IN ('pending','processing','failed','success')) NOT NULL,
                PRIMARY KEY (timestamp, step_name)
            )
        """)
        
        # Create performance indices
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_books_book_id ON books(book_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_language ON books(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_genre ON books(genre)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_narrators_language ON narrators(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_productions_book_id ON audiobook_productions(book_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_productions_status ON audiobook_productions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_audiobook_id ON audiobook_process_events(audiobook_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comfyui_jobs_status_priority ON comfyui_jobs(status, priority)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comfyui_jobs_config_name ON comfyui_jobs(config_name)")

        # Create gutenberg_books performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_author ON gutenberg_books(primary_author)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_language ON gutenberg_books(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_downloads ON gutenberg_books(download_count DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_title ON gutenberg_books(title)")

        # Create gutenberg_process_events performance indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_events_step ON gutenberg_process_events(step_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gutenberg_events_status ON gutenberg_process_events(status)")
        
        conn.commit()


def validate_database_schema(db_path: str) -> bool:
    """Validate that the database has the expected schema structure for both tables.
    
    Args:
        db_path: Path to SQLite database file.
        
    Returns:
        True if schema is valid, False otherwise.
    """
    expected_comfyui_columns = {
        'id', 'config_name', 'job_type', 'workflow_id', 'priority', 'status',
        'run_count', 'retries_attempted', 'retry_limit', 'start_time', 'end_time',
        'duration', 'error_trace', 'metadata', 'worker_id', 'lease_expires_at'
    }
    
    # Expected normalized table schemas
    expected_books_columns = {
        'id', 'book_id', 'book_name', 'author', 'language', 'year_published',
        'genre', 'summary'
    }
    
    expected_narrators_columns = {
        'narrator_id', 'narrator_name', 'gender', 'sample_filepath', 'language', 'accent'
    }
    
    expected_audiobook_productions_columns = {
        'audiobook_id', 'book_id', 'narrator_id', 'language', 'status', 
        'publish_date', 'created_at', 'updated_at'
    }
    
    expected_audiobook_process_events_columns = {
        'audiobook_id', 'timestamp', 'step_number', 'status'
    }

    expected_gutenberg_books_columns = {
        'id', 'title', 'raw_metadata', 'download_count', 'primary_author',
        'language', 'created_at', 'updated_at', 'data_version'
    }

    expected_gutenberg_process_events_columns = {
        'timestamp', 'step_name', 'status'
    }
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Validate comfyui_jobs table
            cursor.execute("PRAGMA table_info(comfyui_jobs)")
            comfyui_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_comfyui_columns - comfyui_columns
            if missing:
                print(f"❌ Missing columns in comfyui_jobs table: {missing}")
                return False
            
            extra = comfyui_columns - expected_comfyui_columns
            if extra:
                print(f"⚠️  Extra columns in comfyui_jobs table: {extra}")
            
            print(f"✅ ComfyUI jobs table validated - {len(comfyui_columns)} columns present")
            
            # Validate books table
            cursor.execute("PRAGMA table_info(books)")
            books_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_books_columns - books_columns
            if missing:
                print(f"❌ Missing columns in books table: {missing}")
                return False
                
            extra = books_columns - expected_books_columns
            if extra:
                print(f"⚠️  Extra columns in books table: {extra}")
                
            print(f"✅ Books table validated - {len(books_columns)} columns present")
            
            # Validate narrators table
            cursor.execute("PRAGMA table_info(narrators)")
            narrators_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_narrators_columns - narrators_columns
            if missing:
                print(f"❌ Missing columns in narrators table: {missing}")
                return False
                
            extra = narrators_columns - expected_narrators_columns
            if extra:
                print(f"⚠️  Extra columns in narrators table: {extra}")
                
            print(f"✅ Narrators table validated - {len(narrators_columns)} columns present")
            
            # Validate audiobook_productions table
            cursor.execute("PRAGMA table_info(audiobook_productions)")
            productions_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_audiobook_productions_columns - productions_columns
            if missing:
                print(f"❌ Missing columns in audiobook_productions table: {missing}")
                return False
                
            extra = productions_columns - expected_audiobook_productions_columns  
            if extra:
                print(f"⚠️  Extra columns in audiobook_productions table: {extra}")
            
            print(f"✅ Audiobook productions table validated - {len(productions_columns)} columns present")
            
            # Validate audiobook_process_events table
            cursor.execute("PRAGMA table_info(audiobook_process_events)")
            events_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_audiobook_process_events_columns - events_columns
            if missing:
                print(f"❌ Missing columns in audiobook_process_events table: {missing}")
                return False
                
            extra = events_columns - expected_audiobook_process_events_columns
            if extra:
                print(f"⚠️  Extra columns in audiobook_process_events table: {extra}")
                
            print(f"✅ Audiobook process events table validated - {len(events_columns)} columns present")

            # Validate gutenberg_books table (use table_xinfo to see generated columns)
            cursor.execute("PRAGMA table_xinfo(gutenberg_books)")
            gutenberg_columns = {row[1] for row in cursor.fetchall()}

            missing = expected_gutenberg_books_columns - gutenberg_columns
            if missing:
                print(f"❌ Missing columns in gutenberg_books table: {missing}")
                return False

            extra = gutenberg_columns - expected_gutenberg_books_columns
            if extra:
                print(f"⚠️  Extra columns in gutenberg_books table: {extra}")

            print(f"✅ Gutenberg books table validated - {len(gutenberg_columns)} columns present")

            # Validate gutenberg_process_events table
            cursor.execute("PRAGMA table_info(gutenberg_process_events)")
            gutenberg_events_columns = {row[1] for row in cursor.fetchall()}

            missing = expected_gutenberg_process_events_columns - gutenberg_events_columns
            if missing:
                print(f"❌ Missing columns in gutenberg_process_events table: {missing}")
                return False

            extra = gutenberg_events_columns - expected_gutenberg_process_events_columns
            if extra:
                print(f"⚠️  Extra columns in gutenberg_process_events table: {extra}")

            print(f"✅ Gutenberg process events table validated - {len(gutenberg_events_columns)} columns present")

            # Check WAL mode
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            if journal_mode.upper() == 'WAL':
                print(f"✅ WAL mode enabled for concurrent access")
            else:
                print(f"⚠️  Journal mode is {journal_mode}, not WAL")
            
            return True
            
    except Exception as e:
        print(f"❌ Schema validation failed: {e}")
        return False


def create_directories(config: dict) -> None:
    """Create all required directories based on configuration.
    
    Args:
        config: Configuration dictionary with paths.
    """
    directories = [
        Path(config['paths']['database']).parent,  # database/ directory
        Path(config['paths']['jobs_processing']),
        Path(config['paths']['jobs_finished']),
        Path(config['paths']['jobs_processing']) / 'image',
        Path(config['paths']['jobs_processing']) / 'speech',
        Path(config['paths']['jobs_processing']) / 'video',
        Path(config['paths']['jobs_processing']) / 'audio', 
        Path(config['paths']['jobs_processing']) / '3d',
        Path(config['paths']['jobs_finished']) / 'image',
        Path(config['paths']['jobs_finished']) / 'speech',
        Path(config['paths']['jobs_finished']) / 'video',
        Path(config['paths']['jobs_finished']) / 'audio',
        Path(config['paths']['jobs_finished']) / '3d',
        Path('foundry'),  # Base foundry directory - books create their own folders
        Path('workflows'),
        Path('logs')
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"📁 Created directory: {directory}")


def main():
    """Main initialization function."""
    print("🚀 E3 ComfyUI Agent - Environment Initialization")
    print("=" * 50)
    
    # Load .env file first
    load_env_file()
    
    # Get environment
    env = os.getenv('E3_ENV')
    env_display = env if env else 'default'
    
    print(f"🔧 Environment: {env_display}")
    
    try:
        # Import after ensuring we're in the right environment
        from comfyui_agent.utils.config_loader import load_global_config
        from comfyui_agent.db_manager import init_db
        
        # Load environment-aware configuration
        print("📖 Loading configuration...")
        config = load_global_config()  # Uses E3_ENV to load config/global_{env}.yaml
        
        db_path = config['paths']['database']
        print(f"📊 Database: {db_path}")
        
        # Create directories
        print("\n📁 Creating directory structure...")
        create_directories(config)
        
        # Initialize database with complete schema
        print(f"\n📊 Initializing database: {db_path}")
        create_database_schema(db_path)
        
        # Validate database schema
        print("\n🔍 Validating database schema...")
        if validate_database_schema(db_path):
            print("✅ Database schema validation passed")
        else:
            print("❌ Database schema validation failed")
            sys.exit(1)
        
        # Summary
        print("\n" + "=" * 50)
        print("✅ E3 Environment Initialized Successfully!")
        print(f"   Environment: {env_display}")
        print(f"   Database: {db_path}")
        print(f"   Config: config/global_{env}.yaml")
        
        print("\n🚀 Ready to run:")
        print("   python -m comfyui_agent.cli start --ui-port 8080")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Make sure you've installed the package: uv pip install -e .")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()