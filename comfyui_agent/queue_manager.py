"""
Queue manager for ComfyUI Agent.

Handles queue logic, priority management, and god mode operations.
"""

import sqlite3
from typing import Any, Optional
from comfyui_agent.db_manager import get_db_connection


def should_run_next(current_busy: bool) -> bool:
    """Determine if next job should be executed.
    
    Gate for single-GPU sequential execution.
    
    Args:
        current_busy: Whether system is currently processing a job.
        
    Returns:
        True if system can run next job, False otherwise.
        
    Examples:
        >>> if should_run_next(False):
        ...     # Execute next job
    """
    return not current_busy


def apply_god_mode(db_path: str, config_name: str) -> None:
    """Apply god mode to a job (set priority to 1).
    
    God mode gives a job highest priority without interrupting
    the currently running job.
    
    Args:
        db_path: Path to SQLite database file.
        config_name: Config filename of job to prioritize.
        
    Examples:
        >>> apply_god_mode("db.sqlite", "urgent_job.yaml")
    """
    set_job_priority(db_path, config_name, 1)


def set_job_priority(db_path: str, config_name: str, priority: Any) -> None:
    """Set priority for a specific job.
    
    Priority is clamped to valid range (1-999).
    Lower number = higher priority.
    
    Args:
        db_path: Path to SQLite database file.
        config_name: Config filename of job to update.
        priority: New priority value (will be clamped to 1-999).
        
    Raises:
        ValueError: If priority is not an integer.
        
    Examples:
        >>> set_job_priority("db.sqlite", "job.yaml", 25)
    """
    # Validate priority type
    if not isinstance(priority, int):
        raise ValueError("Priority must be an integer")
    
    # Clamp priority to valid range
    priority = max(1, min(999, priority))
    
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Update priority for the job
        cursor.execute("""
            UPDATE jobs
            SET priority = ?
            WHERE config_name = ?
        """, (priority, config_name))
        
        # Log if job doesn't exist (rowcount will be 0)
        if cursor.rowcount == 0:
            # In production, this would log a warning
            # For now, silently handle it
            pass