"""
Database manager for ComfyUI Agent.

Handles all SQLite database operations including job lifecycle,
leasing, and recovery mechanisms.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from contextlib import contextmanager


def configure_wal_mode(db_path: str) -> None:
    """Configure database for optimal concurrent access with WAL mode.
    
    Enables WAL (Write-Ahead Logging) mode for concurrent readers + single writer,
    optimizes cache size and synchronization settings for better performance.
    
    Args:
        db_path: Path to SQLite database file.
    """
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


@contextmanager
def get_db_connection(db_path: str):
    """Context manager for database connections.
    
    Ensures connections are properly closed and commits are handled.
    
    Args:
        db_path: Path to SQLite database file.
        
    Yields:
        Database connection object.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    """Initialize database schema - delegates to initialize.py.
    
    Schema creation is now handled by initialize.py for complete workspace setup.
    This function maintained for backward compatibility.
    
    Args:
        db_path: Path to SQLite database file.
    """
    # All schema creation is now handled by initialize.py
    # This function kept for backward compatibility with existing code
    pass


def upsert_job(db_path: str, job_data: Dict[str, Any]) -> int:
    """Insert or update job by config_name.
    
    If job exists, updates non-status fields unless the job is terminal
    (done/failed). Returns the job ID.
    
    Args:
        db_path: Path to SQLite database file.
        job_data: Job data dictionary with required fields.
        
    Returns:
        Job ID (primary key).
        
    Examples:
        >>> job_id = upsert_job("db.sqlite", {"config_name": "job.yaml", ...})
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Check if job exists
        cursor.execute("SELECT id, status FROM comfyui_jobs WHERE config_name = ?",
                      (job_data["config_name"],))
        existing = cursor.fetchone()
        
        if existing:
            job_id = existing["id"]
            existing_status = existing["status"]
            
            # Handle terminal states
            if existing_status == "done":
                # Don't reprocess completed jobs - only update priority if provided
                if "priority" in job_data:
                    cursor.execute(
                        "UPDATE comfyui_jobs SET priority = ? WHERE id = ?",
                        (job_data["priority"], job_id)
                    )
            elif existing_status == "failed":
                # Reset failed jobs so they can be retried
                cursor.execute(
                    "UPDATE comfyui_jobs SET status = 'pending', retries_attempted = 0, priority = ? WHERE id = ?",
                    (job_data.get("priority", 50), job_id)
                )
            else:
                # Update all provided fields
                update_fields = []
                update_values = []
                for field in ["job_type", "workflow_id", "priority", "status",
                            "retry_limit", "metadata"]:
                    if field in job_data:
                        update_fields.append(f"{field} = ?")
                        update_values.append(job_data[field])
                
                if update_fields:
                    update_values.append(job_id)
                    cursor.execute(
                        f"UPDATE comfyui_jobs SET {', '.join(update_fields)} WHERE id = ?",
                        update_values
                    )
        else:
            # Insert new job
            fields = ["config_name", "job_type", "workflow_id", "priority",
                     "status", "retry_limit", "run_count", "retries_attempted"]
            values = []
            placeholders = []
            
            for field in fields:
                if field in job_data:
                    values.append(job_data[field])
                    placeholders.append("?")
                elif field == "status":
                    values.append("pending")
                    placeholders.append("?")
                elif field == "run_count":
                    values.append(0)
                    placeholders.append("?")
                elif field == "retries_attempted":
                    values.append(0)
                    placeholders.append("?")
                elif field == "retry_limit":
                    values.append(2)
                    placeholders.append("?")
                elif field == "priority":
                    values.append(50)
                    placeholders.append("?")
            
            cursor.execute(
                f"INSERT INTO comfyui_jobs ({', '.join(fields[:len(values)])}) "
                f"VALUES ({', '.join(placeholders)})",
                values
            )
            job_id = cursor.lastrowid
        
        return job_id


def lease_next_job(db_path: str, worker_id: str, lease_seconds: int) -> Optional[Dict[str, Any]]:
    """Atomically lease the next pending job.
    
    Selects job by priority (ascending) then ID (FIFO).
    Marks as processing and sets lease expiration.
    
    Args:
        db_path: Path to SQLite database file.
        worker_id: Unique identifier for the worker.
        lease_seconds: Lease duration in seconds.
        
    Returns:
        Leased job dictionary or None if no jobs available.
        
    Examples:
        >>> job = lease_next_job("db.sqlite", "worker1", 300)
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Select next pending job ordered by priority then config_name (for sequential processing)
        # This ensures s0001 is processed before s0002 for SPEECH jobs
        cursor.execute("""
            SELECT * FROM comfyui_jobs
            WHERE status = 'pending'
            ORDER BY priority ASC, config_name ASC
            LIMIT 1
        """)
        
        job = cursor.fetchone()
        if not job:
            return None
        
        # Calculate lease expiration
        lease_expires = (datetime.now() + timedelta(seconds=lease_seconds)).isoformat()
        
        # Update job to processing with lease
        cursor.execute("""
            UPDATE comfyui_jobs
            SET status = 'processing',
                worker_id = ?,
                lease_expires_at = ?,
                start_time = ?,
                run_count = run_count + 1
            WHERE id = ?
        """, (worker_id, lease_expires, datetime.now().isoformat(), job["id"]))
        
        # Return updated job as dictionary
        cursor.execute("SELECT * FROM comfyui_jobs WHERE id = ?", (job["id"],))
        updated_job = cursor.fetchone()
        
        return dict(updated_job)


def complete_job(db_path: str, job_id: int, *, success: bool,
                updates: Dict[str, Any]) -> None:
    """Mark job as complete (success or failure).
    
    On success: marks as done, sets end_time and duration.
    On failure: increments retries, requeues if under limit, else marks failed.
    
    Args:
        db_path: Path to SQLite database file.
        job_id: Job ID to complete.
        success: Whether job completed successfully.
        updates: Additional fields to update (metadata, error_trace, etc).
        
    Examples:
        >>> complete_job("db.sqlite", 1, success=True, updates={"metadata": "..."})
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # Get current job state
        cursor.execute("""
            SELECT start_time, retries_attempted, retry_limit
            FROM comfyui_jobs WHERE id = ?
        """, (job_id,))
        job = cursor.fetchone()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        end_time = datetime.now().isoformat()
        duration = None
        
        if job["start_time"]:
            start = datetime.fromisoformat(job["start_time"])
            duration = (datetime.now() - start).total_seconds()
        
        if success:
            # Mark as done
            cursor.execute("""
                UPDATE comfyui_jobs
                SET status = 'done',
                    end_time = ?,
                    duration = ?,
                    metadata = ?,
                    worker_id = NULL,
                    lease_expires_at = NULL
                WHERE id = ?
            """, (end_time, duration, updates.get("metadata"), job_id))
        else:
            # Handle failure
            retries_attempted = job["retries_attempted"] + 1
            retry_limit = job["retry_limit"]
            
            if retries_attempted < retry_limit:
                # Requeue for retry
                cursor.execute("""
                    UPDATE comfyui_jobs
                    SET status = 'pending',
                        retries_attempted = ?,
                        error_trace = ?,
                        worker_id = NULL,
                        lease_expires_at = NULL
                    WHERE id = ?
                """, (retries_attempted, updates.get("error_trace"), job_id))
            else:
                # Mark as failed
                cursor.execute("""
                    UPDATE comfyui_jobs
                    SET status = 'failed',
                        end_time = ?,
                        duration = ?,
                        retries_attempted = ?,
                        error_trace = ?,
                        worker_id = NULL,
                        lease_expires_at = NULL
                    WHERE id = ?
                """, (end_time, duration, retries_attempted,
                     updates.get("error_trace"), job_id))


def recover_orphans(db_path: str, now: datetime) -> int:
    """Recover jobs with expired leases.
    
    Finds processing jobs where lease has expired and resets
    them to pending status.
    
    Args:
        db_path: Path to SQLite database file.
        now: Current datetime for comparison.
        
    Returns:
        Number of jobs recovered.
        
    Examples:
        >>> recovered = recover_orphans("db.sqlite", datetime.now())
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        now_str = now.isoformat()
        
        # Find and update orphaned jobs
        cursor.execute("""
            UPDATE comfyui_jobs
            SET status = 'pending',
                worker_id = NULL,
                lease_expires_at = NULL
            WHERE status = 'processing'
            AND lease_expires_at < ?
        """, (now_str,))
        
        return cursor.rowcount


def get_job_by_config_name(db_path: str, config_name: str) -> Optional[Dict[str, Any]]:
    """Get job by config name.
    
    Args:
        db_path: Path to SQLite database file.
        config_name: Config filename to search for.
        
    Returns:
        Job dictionary or None if not found.
        
    Examples:
        >>> job = get_job_by_config_name("db.sqlite", "job.yaml")
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM comfyui_jobs WHERE config_name = ?", (config_name,))
        job = cursor.fetchone()
        return dict(job) if job else None


def list_jobs_by_status(db_path: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List jobs filtered by status.
    
    Args:
        db_path: Path to SQLite database file.
        status: Status to filter by, or None for all jobs.
        
    Returns:
        List of job dictionaries.
        
    Examples:
        >>> pending_jobs = list_jobs_by_status("db.sqlite", "pending")
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        if status:
            cursor.execute("""
                SELECT * FROM comfyui_jobs
                WHERE status = ?
                ORDER BY priority ASC, config_name ASC
            """, (status,))
        else:
            cursor.execute("""
                SELECT * FROM comfyui_jobs
                ORDER BY priority ASC, config_name ASC
            """)
        
        return [dict(row) for row in cursor.fetchall()]