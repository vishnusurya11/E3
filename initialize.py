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
    expected_titles_columns = {
        'book_id', 'title', 'author', 'genre', 'language', 'publication_year',
        'source_url', 'input_file_path', 'audiobook_complete', 'audiobook_narrator_id',
        'created_at', 'updated_at'
    }
    
    expected_narrators_columns = {
        'narrator_id', 'narrator_name', 'voice_sample_path', 'voice_model',
        'language', 'gender', 'description', 'active', 'created_at'
    }
    
    expected_audiobook_production_columns = {
        'id', 'book_id', 'narrator_id', 'status', 'parse_novel_status',
        'parse_novel_completed_at', 'metadata_status', 'metadata_completed_at',
        'total_chapters', 'total_chunks', 'total_words', 'audio_generation_status',
        'audio_generation_completed_at', 'audio_jobs_completed', 'total_audio_files',
        'audio_duration_seconds', 'audio_file_size_bytes', 'audio_files_moved_status',
        'audio_files_moved_completed_at', 'audio_combination_planned_status',
        'audio_combination_planned_completed_at', 'audio_combination_status',
        'audio_combination_completed_at', 'image_prompts_status', 'image_prompts_started_at',
        'image_prompts_completed_at', 'image_jobs_generation_status',
        'image_jobs_generation_completed_at', 'image_jobs_completed', 'total_image_jobs',
        'image_generation_status', 'image_generation_completed_at',
        'subtitle_generation_status', 'subtitle_generation_completed_at',
        'video_generation_status', 'video_generation_started_at',
        'video_generation_completed_at', 'total_videos_created', 'metadata',
        'retry_count', 'max_retries', 'created_at', 'updated_at'
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
            
            # Validate titles table
            cursor.execute("PRAGMA table_info(titles)")
            titles_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_titles_columns - titles_columns
            if missing:
                print(f"❌ Missing columns in titles table: {missing}")
                return False
                
            extra = titles_columns - expected_titles_columns
            if extra:
                print(f"⚠️  Extra columns in titles table: {extra}")
                
            print(f"✅ Titles table validated - {len(titles_columns)} columns present")
            
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
            
            # Validate audiobook_production table
            cursor.execute("PRAGMA table_info(audiobook_production)")
            audiobook_columns = {row[1] for row in cursor.fetchall()}
            
            missing = expected_audiobook_production_columns - audiobook_columns
            if missing:
                print(f"❌ Missing columns in audiobook_production table: {missing}")
                return False
                
            extra = audiobook_columns - expected_audiobook_production_columns  
            if extra:
                print(f"⚠️  Extra columns in audiobook_production table: {extra}")
            
            print(f"✅ Audiobook production table validated - {len(audiobook_columns)} columns present")
            
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
        
        # Initialize database
        print(f"\n📊 Initializing database: {db_path}")
        init_db(db_path)
        
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