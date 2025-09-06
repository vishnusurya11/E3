"""
Monitor module for ComfyUI Agent.

Watches filesystem for new YAML configs and ingests them into the database.
"""

import os
import time
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path

from comfyui_agent.db_manager import upsert_job
from comfyui_agent.utils.file_utils import list_yaml_under
from comfyui_agent.utils.validation import (
    parse_config_name,
    validate_config_schema,
    normalize_config
)
from comfyui_agent.utils.logger import get_logger

logger = get_logger(__name__)


def process_yaml_file(yaml_path: str, workflows: Dict[str, Any],
                     db_path: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single YAML file.
    
    Validates, normalizes, and inserts into database.
    
    Args:
        yaml_path: Path to YAML file.
        workflows: Available workflow definitions.
        db_path: Database path.
        defaults: Default configuration values.
        
    Returns:
        Processing result dictionary with status and reason.
        
    Examples:
        >>> result = process_yaml_file("job.yaml", workflows, "db.sqlite", defaults)
        >>> print(result["status"])
        accepted
    """
    result = {"path": yaml_path, "status": "rejected", "reason": ""}
    
    try:
        # Parse filename
        basename = os.path.basename(yaml_path)
        parsed = parse_config_name(basename)
        
        # Load YAML content with UTF-8 encoding to handle special characters
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if not config:
            result["reason"] = "Empty YAML file"
            return result
        
        # Validate schema
        validate_config_schema(config, workflows)
        
        # Normalize config
        config = normalize_config(config, defaults)
        
        # Prepare job data for database
        job_data = {
            "config_name": basename,
            "job_type": parsed["job_type"],
            "workflow_id": config.get("workflow_id"),
            "priority": config.get("priority", defaults.get("default_priority", 50)),
            "status": "pending",
            "retry_limit": config.get("retry_limit", defaults.get("retry_limit", 2))
        }
        
        # Insert/update in database
        logger.info(f"[MONITOR] Upserting job {basename} to database...")
        job_id = upsert_job(db_path, job_data)
        
        result["status"] = "accepted"
        result["job_id"] = job_id
        logger.info(f"[MONITOR] Accepted job {basename} with ID {job_id}")
        
    except ValueError as e:
        result["reason"] = str(e)
        logger.warning(f"Rejected {yaml_path}: {e}")
    except yaml.YAMLError as e:
        result["reason"] = f"Invalid YAML: {e}"
        logger.warning(f"Invalid YAML in {yaml_path}: {e}")
    except Exception as e:
        result["reason"] = f"Unexpected error: {e}"
        logger.error(f"Error processing {yaml_path}: {e}")
    
    return result


def scan_once(cfg: Dict[str, Any], workflows: Dict[str, Any],
             db_path: str) -> List[Dict[str, Any]]:
    """Scan for new YAML files once.
    
    Detects new YAML files, validates them, and inserts into database.
    
    Args:
        cfg: Global configuration.
        workflows: Available workflow definitions.
        db_path: Database path.
        
    Returns:
        List of processing results.
        
    Examples:
        >>> results = scan_once(config, workflows, "db.sqlite")
        >>> accepted = [r for r in results if r["status"] == "accepted"]
    """
    results = []
    
    # Get processing directory
    processing_dir = cfg["paths"]["jobs_processing"]
    
    if not os.path.exists(processing_dir):
        logger.warning(f"Processing directory does not exist: {processing_dir}")
        return results
    
    # List all YAML files
    yaml_files = list_yaml_under(processing_dir)
    
    # Get defaults from config
    defaults = {
        "default_priority": cfg.get("default_priority", 50),
        "retry_limit": cfg.get("retry_limit", 2)
    }
    
    # Process each file with delay to prevent overwhelming the system
    for yaml_path in yaml_files:
        result = process_yaml_file(yaml_path, workflows, db_path, defaults)
        results.append(result)
        # Add 1 second delay after each file to allow sequential processing
        time.sleep(1)
    
    if results:
        accepted = len([r for r in results if r["status"] == "accepted"])
        rejected = len([r for r in results if r["status"] == "rejected"])
        logger.info(f"Scan complete: {accepted} accepted, {rejected} rejected")
    
    return results


def run_monitor_loop(cfg: Dict[str, Any], workflows: Dict[str, Any],
                    db_path: str, stop_event=None) -> None:
    """Run continuous monitor loop.
    
    Keeps scanning for new files until stop_event is set.
    
    Args:
        cfg: Global configuration.
        workflows: Available workflow definitions.
        db_path: Database path.
        stop_event: Optional threading event to stop loop.
        
    Examples:
        >>> import threading
        >>> stop = threading.Event()
        >>> run_monitor_loop(config, workflows, "db.sqlite", stop)
    """
    poll_interval = cfg.get("poll_interval_ms", 1000) / 1000.0
    
    logger.info("Starting monitor loop")
    logger.info(f"Watching: {cfg['paths']['jobs_processing']}")
    logger.info(f"Poll interval: {poll_interval}s")
    
    # Track processed files to avoid reprocessing
    processed_files = set()
    
    while stop_event is None or not stop_event.is_set():
        try:
            # Get current YAML files
            processing_dir = cfg["paths"]["jobs_processing"]
            if os.path.exists(processing_dir):
                current_files = set(list_yaml_under(processing_dir))
                
                # Find new files
                new_files = current_files - processed_files
                
                if new_files:
                    logger.info(f"Found {len(new_files)} new files")
                    
                    # Process new files
                    defaults = {
                        "default_priority": cfg.get("default_priority", 50),
                        "retry_limit": cfg.get("retry_limit", 2)
                    }
                    
                    for yaml_path in new_files:
                        result = process_yaml_file(yaml_path, workflows, db_path, defaults)
                        if result["status"] == "accepted":
                            processed_files.add(yaml_path)
                        # Keep rejected files in the set to avoid reprocessing
                        # unless they're modified
                        processed_files.add(yaml_path)
                
                # Remove files that no longer exist from tracking
                processed_files = processed_files & current_files
            
            # Sleep before next scan
            if stop_event:
                stop_event.wait(poll_interval)
            else:
                time.sleep(poll_interval)
                
        except KeyboardInterrupt:
            logger.info("Monitor loop interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            time.sleep(poll_interval)
    
    logger.info("Monitor loop stopped")