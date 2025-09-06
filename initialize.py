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
    """Validate that the database has the expected schema structure.
    
    Args:
        db_path: Path to SQLite database file.
        
    Returns:
        True if schema is valid, False otherwise.
    """
    expected_columns = {
        'id', 'config_name', 'job_type', 'workflow_id', 'priority', 'status',
        'run_count', 'retries_attempted', 'retry_limit', 'start_time', 'end_time',
        'duration', 'error_trace', 'metadata', 'worker_id', 'lease_expires_at'
    }
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(jobs)")
            columns = {row[1] for row in cursor.fetchall()}  # row[1] is column name
            
            missing = expected_columns - columns
            if missing:
                print(f"❌ Missing columns in jobs table: {missing}")
                return False
                
            extra = columns - expected_columns
            if extra:
                print(f"⚠️  Extra columns in jobs table: {extra}")
            
            print(f"✅ Database schema validated - {len(columns)} columns present")
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
        Path('foundry/input'),
        Path('foundry/processing'),
        Path('foundry/finished'),
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