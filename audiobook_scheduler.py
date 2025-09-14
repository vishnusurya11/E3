#!/usr/bin/env python3
"""
Audiobook CLI Automation Scheduler

Python-based scheduler for running audiobook CLI at configurable intervals.
Provides better logging and error handling than batch scripts.
"""

import subprocess
import time
import os
import json
from datetime import datetime
from pathlib import Path


# Configuration
INTERVAL_MINUTES = 5  # Configurable interval in minutes
PROJECT_DIR = r"D:\Projects\pheonix\alpha\E3"
LOG_FILE = "logs/batch_automation.log"
CONFIG_FILE = "config/automation_config.json"


def load_config():
    """Load automation configuration from file."""
    config_path = Path(PROJECT_DIR) / CONFIG_FILE
    
    # Default configuration
    default_config = {
        "interval_minutes": 5,
        "log_file": "logs/batch_automation.log",
        "max_log_size_mb": 100,
        "enable_email_alerts": False,
        "python_executable": ".venv/Scripts/python.exe",
        "cli_script": "audiobook_agent/audiobook_cli.py"
    }
    
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            # Merge with defaults
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            return config
        except Exception as e:
            print(f"Error loading config: {e}, using defaults")
            return default_config
    else:
        # Create default config file
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        print(f"Created default config: {config_path}")
        return default_config


def setup_logging(log_file):
    """Ensure log directory exists and rotate logs if needed."""
    log_path = Path(PROJECT_DIR) / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Simple log rotation - if file > 100MB, rename to .old
    if log_path.exists() and log_path.stat().st_size > 100 * 1024 * 1024:  # 100MB
        old_log = log_path.with_suffix('.old.log')
        if old_log.exists():
            old_log.unlink()  # Remove old backup
        log_path.rename(old_log)
        print(f"Rotated log file: {log_path} -> {old_log}")
    
    return log_path


def run_audiobook_cli(config, log_path):
    """Execute the audiobook CLI and capture output."""
    
    # Change to project directory
    original_dir = os.getcwd()
    os.chdir(PROJECT_DIR)
    
    try:
        timestamp = datetime.now().isoformat()
        
        # Log start
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f"\n{'='*60}\n")
            log.write(f"[{timestamp}] STARTING AUDIOBOOK CLI AUTOMATION\n")
            log.write(f"Working Directory: {os.getcwd()}\n")
            log.write(f"Python Executable: {config['python_executable']}\n")
            log.write(f"CLI Script: {config['cli_script']}\n")
            log.write(f"{'='*60}\n\n")
        
        # Run CLI with virtual environment
        result = subprocess.run([
            config['python_executable'], 
            config['cli_script']
        ], 
        capture_output=True, 
        text=True, 
        timeout=3600,  # 1 hour timeout
        encoding='utf-8',
        errors='replace'  # Handle any encoding issues
        )
        
        # Log results
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f"STDOUT:\n{result.stdout}\n")
            
            if result.stderr:
                log.write(f"\nSTDERR:\n{result.stderr}\n")
            
            completion_time = datetime.now().isoformat()
            log.write(f"\n[{completion_time}] CLI completed with exit code: {result.returncode}\n")
            
            if result.returncode == 0:
                log.write(f"✅ SUCCESS: CLI run completed successfully\n")
            else:
                log.write(f"❌ ERROR: CLI run failed with exit code {result.returncode}\n")
        
        print(f"[{timestamp}] CLI run completed with exit code: {result.returncode}")
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        error_msg = f"[{datetime.now().isoformat()}] TIMEOUT: CLI run exceeded 1 hour timeout"
        print(error_msg)
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f"{error_msg}\n")
        return False
        
    except Exception as e:
        error_msg = f"[{datetime.now().isoformat()}] ERROR: {str(e)}"
        print(error_msg)
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f"{error_msg}\n")
        return False
        
    finally:
        os.chdir(original_dir)


def main():
    """Main scheduler loop."""
    print("🤖 AUDIOBOOK CLI AUTOMATION SCHEDULER")
    print("=" * 50)
    
    # Load configuration
    config = load_config()
    interval_minutes = config['interval_minutes']
    
    print(f"📋 Configuration loaded:")
    print(f"   Interval: {interval_minutes} minutes")
    print(f"   Log file: {config['log_file']}")
    print(f"   Project: {PROJECT_DIR}")
    print()
    
    # Setup logging
    log_path = setup_logging(config['log_file'])
    print(f"📝 Logging to: {log_path}")
    
    # Initial log entry
    with open(log_path, 'a', encoding='utf-8') as log:
        log.write(f"\n🚀 SCHEDULER STARTED at {datetime.now().isoformat()}\n")
        log.write(f"Interval: {interval_minutes} minutes\n")
        log.write(f"Project Directory: {PROJECT_DIR}\n\n")
    
    print(f"🚀 Starting scheduler - running every {interval_minutes} minutes")
    print("Press Ctrl+C to stop")
    
    run_count = 0
    try:
        while True:
            run_count += 1
            print(f"\n[Run #{run_count}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            success = run_audiobook_cli(config, log_path)
            
            if success:
                print(f"✅ CLI run #{run_count} completed successfully")
            else:
                print(f"❌ CLI run #{run_count} failed")
            
            print(f"⏰ Waiting {interval_minutes} minutes until next run...")
            time.sleep(interval_minutes * 60)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Scheduler stopped by user after {run_count} runs")
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f"\n🛑 SCHEDULER STOPPED at {datetime.now().isoformat()} after {run_count} runs\n")


if __name__ == "__main__":
    main()