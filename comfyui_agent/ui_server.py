"""
UI server module for ComfyUI Agent.

Provides FastAPI REST endpoints for job management and monitoring.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from datetime import datetime

from comfyui_agent.db_manager import (
    get_job_by_config_name,
    list_jobs_by_status,
    get_db_connection
)

# Import audiobook helper functions
try:
    import sys
    import os
    # Add parent directory to path for imports
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    
    from audiobook_agent.audiobook_helper import get_all_books
    print("✅ Audiobook helper functions imported successfully")
    
    # Test database access
    test_books = get_all_books()
    print(f"📊 Database test: Found {len(test_books)} books")
    AUDIOBOOKS_AVAILABLE = True
    
except ImportError as e:
    AUDIOBOOKS_AVAILABLE = False
    print(f"❌ Import error: {e}")
except Exception as e:
    AUDIOBOOKS_AVAILABLE = False
    print(f"❌ Database error: {e}")
from comfyui_agent.queue_manager import set_job_priority, apply_god_mode
from comfyui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="ComfyUI Agent API",
    description="REST API for E3 ComfyUI Agent job management",
    version="1.0.0"
)

# Add CORS middleware for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global database path (set by main application)
_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    """Set the database path for the UI server.
    
    Args:
        path: Path to SQLite database file.
    """
    global _db_path
    _db_path = path


def get_db_path() -> str:
    """Get the configured database path.
    
    Returns:
        Database path.
        
    Raises:
        RuntimeError: If database path not set.
    """
    if _db_path is None:
        # Fallback: try default database path
        default_path = "database/comfyui_agent.db"
        if os.path.exists(default_path):
            print(f"⚠️  Using fallback database path: {default_path}")
            return default_path
        else:
            raise RuntimeError(f"Database path not configured and default not found: {default_path}")
    return _db_path


# Pydantic models for request/response
class PriorityUpdate(BaseModel):
    """Model for priority update request."""
    priority: int


class JobResponse(BaseModel):
    """Model for job response."""
    config_name: str
    job_type: str
    workflow_id: str
    priority: int
    status: str
    run_count: Optional[int] = 0
    retries_attempted: Optional[int] = 0
    error_trace: Optional[str] = None
    metadata: Optional[str] = None


# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint.
    
    Returns:
        Health status dictionary.
    """
    return {"status": "healthy", "service": "ComfyUI Agent"}


@app.get("/api/queue", response_model=List[Dict[str, Any]])
async def list_queue(status: Optional[str] = Query(None, description="Filter by status")):
    """List jobs in the queue.
    
    Args:
        status: Optional status filter (pending, processing, done, failed).
        
    Returns:
        List of jobs.
        
    Raises:
        HTTPException: If invalid status provided.
    """
    valid_statuses = {"pending", "processing", "done", "failed"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {valid_statuses}")
    
    try:
        db_path = get_db_path()
        jobs = list_jobs_by_status(db_path, status)
        return jobs
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/queue/{config_name}", response_model=Dict[str, Any])
async def job_details(config_name: str):
    """Get detailed information about a specific job.
    
    Args:
        config_name: Config filename of the job.
        
    Returns:
        Job details dictionary.
        
    Raises:
        HTTPException: If job not found.
    """
    try:
        db_path = get_db_path()
        job = get_job_by_config_name(db_path, config_name)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return job
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/queue/{config_name}/priority")
async def update_priority(config_name: str, update: PriorityUpdate):
    """Update job priority.
    
    Args:
        config_name: Config filename of the job.
        update: Priority update request.
        
    Returns:
        Updated job information.
        
    Raises:
        HTTPException: If job not found or update fails.
    """
    try:
        db_path = get_db_path()
        
        # Check job exists
        job = get_job_by_config_name(db_path, config_name)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Update priority
        set_job_priority(db_path, config_name, update.priority)
        
        # Return updated job
        updated_job = get_job_by_config_name(db_path, config_name)
        return updated_job
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/queue/{config_name}/retry")
async def retry_job(config_name: str):
    """Retry a failed job.
    
    Args:
        config_name: Config filename of the job.
        
    Returns:
        Updated job information.
        
    Raises:
        HTTPException: If job not found or not in failed state.
    """
    try:
        db_path = get_db_path()
        
        # Check job exists and is failed
        job = get_job_by_config_name(db_path, config_name)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job["status"] != "failed":
            raise HTTPException(status_code=400, detail="Job is not failed, cannot retry")
        
        # Reset job to pending
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE comfyui_jobs
                SET status = 'pending',
                    error_trace = NULL,
                    worker_id = NULL,
                    lease_expires_at = NULL
                WHERE config_name = ?
            """, (config_name,))
        
        # Return updated job
        updated_job = get_job_by_config_name(db_path, config_name)
        return updated_job
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/queue/{config_name}/god-mode")
async def god_mode(config_name: str):
    """Apply god mode to a job (set priority to 1).
    
    Args:
        config_name: Config filename of the job.
        
    Returns:
        Updated job information.
        
    Raises:
        HTTPException: If job not found.
    """
    try:
        db_path = get_db_path()
        
        # Check job exists
        job = get_job_by_config_name(db_path, config_name)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Apply god mode
        apply_god_mode(db_path, config_name)
        
        # Return updated job
        updated_job = get_job_by_config_name(db_path, config_name)
        return updated_job
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying god mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Get system statistics.
    
    Returns:
        Statistics dictionary.
    """
    try:
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            
            # Get counts by status
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM comfyui_jobs
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            # Get total jobs
            cursor.execute("SELECT COUNT(*) as total FROM comfyui_jobs")
            total = cursor.fetchone()["total"]
            
            # Get average duration for completed jobs
            cursor.execute("""
                SELECT AVG(duration) as avg_duration
                FROM comfyui_jobs
                WHERE status = 'done' AND duration IS NOT NULL
            """)
            avg_duration = cursor.fetchone()["avg_duration"]
            
            return {
                "total_jobs": total,
                "by_status": status_counts,
                "avg_duration_seconds": avg_duration
            }
            
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs")
async def list_all_jobs():
    """List all jobs with full details for dashboard.
    
    Returns:
        List of all jobs with complete information.
    """
    try:
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id, config_name, job_type, workflow_id, priority, status,
                    retries_attempted, retry_limit, error_trace, metadata,
                    worker_id, lease_expires_at, start_time, end_time,
                    duration
                FROM comfyui_jobs
                ORDER BY id DESC
            """)
            
            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                # Convert timestamps to ISO format for JS
                for field in ['start_time', 'end_time', 'lease_expires_at']:
                    if job.get(field):
                        job[field] = job[field]
                jobs.append(job)
            
            return jobs
            
    except Exception as e:
        logger.error(f"Error listing all jobs: {e}")
        import traceback
        traceback.print_exc()
        
        # Return detailed error for debugging
        error_detail = {
            "error": str(e),
            "type": type(e).__name__,
            "db_path_set": _db_path is not None,
            "db_path": _db_path,
            "timestamp": datetime.now().isoformat()
        }
        
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/job/{job_id}/retry")
async def retry_job_by_id(job_id: int):
    """Retry a job by ID.
    
    Args:
        job_id: Job ID to retry.
        
    Returns:
        Updated job information.
    """
    try:
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            
            # Check if job exists
            cursor.execute("SELECT * FROM comfyui_jobs WHERE id = ?", (job_id,))
            job = cursor.fetchone()
            
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
            
            # Reset job to pending
            cursor.execute("""
                UPDATE comfyui_jobs
                SET status = 'pending',
                    error_trace = NULL,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    start_time = NULL,
                    end_time = NULL,
                    duration = NULL
                WHERE id = ?
            """, (job_id,))
            
            return {"status": "success", "message": f"Job {job_id} queued for retry"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/retry-failed")
async def retry_all_failed():
    """Retry all failed jobs.
    
    Returns:
        Number of jobs queued for retry.
    """
    try:
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            
            # Reset all failed jobs to pending
            cursor.execute("""
                UPDATE comfyui_jobs
                SET status = 'pending',
                    error_trace = NULL,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    start_time = NULL,
                    end_time = NULL,
                    duration = NULL
                WHERE status = 'failed'
            """)
            
            retry_count = cursor.rowcount
            
            return {"status": "success", "retried": retry_count}
            
    except Exception as e:
        logger.error(f"Error retrying failed jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/cancel-all")
async def cancel_all_pending():
    """Cancel all pending jobs.
    
    Returns:
        Number of jobs cancelled.
    """
    try:
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            
            # Mark all pending jobs as cancelled
            cursor.execute("""
                UPDATE jobs
                SET status = 'cancelled',
                    error_trace = 'Cancelled by user'
                WHERE status = 'pending'
            """)
            
            cancel_count = cursor.rowcount
            
            return {"status": "success", "cancelled": cancel_count}
            
    except Exception as e:
        logger.error(f"Error cancelling pending jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/export")
async def export_jobs_csv():
    """Export jobs to CSV format.
    
    Returns:
        CSV file download.
    """
    try:
        from fastapi.responses import StreamingResponse
        import csv
        import io
        
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    id, config_name, job_type, workflow_id, priority, status,
                    retries_attempted, retry_limit, error_trace,
                    worker_id, created_at, start_time, end_time, duration
                FROM comfyui_jobs
                ORDER BY id DESC
            """)
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'ID', 'Config Name', 'Job Type', 'Workflow', 'Priority', 'Status',
                'Retries', 'Retry Limit', 'Error', 'Worker', 
                'Created', 'Started', 'Ended', 'Duration (s)'
            ])
            
            # Write data
            for row in cursor.fetchall():
                writer.writerow([
                    row['id'], row['config_name'], row['job_type'], 
                    row['workflow_id'], row['priority'], row['status'],
                    row['retries_attempted'], row['retry_limit'], row['error_trace'],
                    row['worker_id'], row['created_at'], row['start_time'],
                    row['end_time'], row['duration']
                ])
            
            output.seek(0)
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode()),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=jobs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                }
            )
            
    except Exception as e:
        logger.error(f"Error exporting jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/update")
async def update_job(job: Dict[str, Any]):
    """Update a job's fields.
    
    Args:
        job: Job dictionary with updated values.
        
    Returns:
        Success status.
    """
    try:
        db_path = get_db_path()
        job_id = job.get('id')
        
        if not job_id:
            raise HTTPException(status_code=400, detail="Job ID required")
        
        # Build update query dynamically
        updateable_fields = ['config_name', 'job_type', 'workflow_id', 'priority', 
                           'status', 'retries_attempted', 'retry_limit', 'error_trace']
        
        updates = []
        values = []
        for field in updateable_fields:
            if field in job:
                updates.append(f"{field} = ?")
                values.append(job[field])
        
        if not updates:
            return {"status": "success", "message": "No fields to update"}
        
        values.append(job_id)
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            query = f"UPDATE comfyui_jobs SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, values)
            
            return {"status": "success", "updated": cursor.rowcount}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/bulk-delete")
async def bulk_delete_jobs(request: Dict[str, Any]):
    """Delete multiple jobs by ID.
    
    Args:
        request: Dictionary with 'ids' key containing list of job IDs.
        
    Returns:
        Number of deleted jobs.
    """
    try:
        ids = request.get('ids', [])
        
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(ids))
            cursor.execute(f"DELETE FROM comfyui_jobs WHERE id IN ({placeholders})", ids)
            
            return {"status": "success", "deleted": cursor.rowcount}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs/bulk-retry")
async def bulk_retry_jobs(request: Dict[str, Any]):
    """Retry multiple failed jobs.
    
    Args:
        request: Dictionary with 'ids' key containing list of job IDs.
        
    Returns:
        Number of jobs queued for retry.
    """
    try:
        ids = request.get('ids', [])
        
        if not ids:
            raise HTTPException(status_code=400, detail="No IDs provided")
        
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(ids))
            cursor.execute(f"""
                UPDATE comfyui_jobs
                SET status = 'pending',
                    error_trace = NULL,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    start_time = NULL,
                    end_time = NULL,
                    duration = NULL
                WHERE id IN ({placeholders}) AND status = 'failed'
            """, ids)
            
            return {"status": "success", "retried": cursor.rowcount}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sql")
async def execute_sql(request: Dict[str, Any]):
    """Execute SQL query on the database.
    
    WARNING: This endpoint can modify data. Use with caution.
    
    Args:
        request: Dictionary with 'query' key containing SQL to execute.
        
    Returns:
        Query results or affected rows count.
    """
    try:
        from fastapi import Request
        
        query = request.get("query", "").strip()
        
        if not query:
            raise HTTPException(status_code=400, detail="No query provided")
        
        # Basic safety check - warn about destructive operations
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER"]
        is_dangerous = any(keyword in query.upper() for keyword in dangerous_keywords)
        
        db_path = get_db_path()
        
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            
            # Check if it's a SELECT query
            is_select = query.upper().startswith("SELECT")
            
            try:
                cursor.execute(query)
                
                if is_select:
                    # Return query results
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    rows = []
                    for row in cursor.fetchall():
                        rows.append(dict(zip(columns, row)) if columns else list(row))
                    
                    return {
                        "type": "select",
                        "columns": columns,
                        "rows": rows,
                        "count": len(rows),
                        "warning": is_dangerous
                    }
                else:
                    # Return affected rows for non-SELECT queries
                    affected = cursor.rowcount
                    conn.commit()
                    
                    return {
                        "type": "update",
                        "affected_rows": affected,
                        "warning": is_dangerous,
                        "message": f"Query executed successfully. {affected} rows affected."
                    }
                    
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"SQL Error: {str(e)}")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing SQL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


################################################################################
# AUDIOBOOKS DASHBOARD API ROUTES
################################################################################

@app.get("/api/audiobooks")
async def get_audiobooks():
    """Get all audiobooks with pipeline status."""
    try:
        # Debug logging
        print(f"🔍 Audiobooks API called. Available: {AUDIOBOOKS_AVAILABLE}")
        
        if not AUDIOBOOKS_AVAILABLE:
            print("❌ Audiobook functions not available")
            raise HTTPException(status_code=503, detail="Audiobook functions not available")
        
        print("📚 Getting all books from database...")
        books = get_all_books()
        print(f"📊 Retrieved {len(books)} books from database")
        
        # Add pipeline progress calculation
        for i, book in enumerate(books):
            try:
                # Calculate pipeline stage and progress
                stage = get_pipeline_stage(book)
                total_steps = 12  # Total pipeline steps (now includes image generation)
                
                # Map stages to progress percentage (12-step pipeline)
                stage_progress = {
                    1: 100,   # Fully completed 
                    12: 95,   # Image job completion check
                    11: 90,   # Image job creation
                    10: 85,   # Image prompt generation
                    9: 80,    # Audio combination
                    8: 70,    # Subtitle generation
                    7: 60,    # Plan audio combinations
                    6: 50,    # Move audio files
                    5: 40,    # Audio completion checks
                    4: 30,    # Audio job generation
                    3: 20,    # Metadata addition
                    2: 10     # Novel parsing
                }
                
                book['pipeline_progress'] = stage_progress.get(stage, 0)
                book['current_stage'] = stage
                book['total_steps'] = total_steps
                book['status_summary'] = get_book_status_summary(book)
                
                print(f"  📖 Book {i+1}: {book.get('book_title', 'Unknown')} - Stage {stage}, Progress {book['pipeline_progress']}%")
                
            except Exception as book_error:
                print(f"⚠️  Error processing book {i+1}: {book_error}")
                import traceback
                traceback.print_exc()
                # Set default values for failed book processing
                book['pipeline_progress'] = 0
                book['current_stage'] = 1
                book['total_steps'] = 12
                book['status_summary'] = "❓ Status unknown"
        
        print(f"✅ Successfully processed {len(books)} books")
        return {"books": books}
        
    except Exception as e:
        print(f"❌ Critical error in audiobooks API: {e}")
        logger.error(f"Error getting audiobooks: {e}")
        import traceback
        traceback.print_exc()
        
        # Return detailed error for debugging
        error_detail = {
            "error": str(e),
            "type": type(e).__name__,
            "audiobooks_available": AUDIOBOOKS_AVAILABLE,
            "timestamp": datetime.now().isoformat()
        }
        
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/api/audiobooks/{book_id}")
async def get_audiobook_details(book_id: str):
    """Get detailed information for a specific audiobook."""
    if not AUDIOBOOKS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Audiobook functions not available")
    
    try:
        books = get_all_books()
        book = next((b for b in books if b['book_id'] == book_id), None)
        
        if not book:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        
        # Add detailed step information
        book['pipeline_steps'] = get_detailed_pipeline_steps(book)
        
        return book
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting audiobook details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def get_pipeline_stage(book: Dict) -> int:
    """Calculate pipeline stage for a book (copied from generate_audiobook.py)."""
    
    # Use actual database field names
    parse_status = book.get('parse_novel_status', 'pending')
    metadata_status = book.get('metadata_status', 'pending')
    audio_status = book.get('audio_generation_status', 'pending')
    audio_moved_status = book.get('audio_files_moved_status', 'pending')
    combination_planned_status = book.get('audio_combination_planned_status', 'pending')
    subtitle_status = book.get('subtitle_generation_status', 'pending')
    audio_combination_status = book.get('audio_combination_status', 'pending')
    image_prompts_status = book.get('image_prompts_status', 'pending')
    image_jobs_generation_status = book.get('image_jobs_generation_status', 'pending')
    image_generation_status = book.get('image_generation_status', 'pending')
    
    # PRIORITY: Check completion from highest step backwards
    # If final step is completed, book is fully completed regardless of intermediate inconsistencies
    if (audio_combination_status == 'completed' and 
        image_prompts_status == 'completed' and
        image_jobs_generation_status == 'completed' and
        image_generation_status == 'completed'):
        return 1  # Fully completed
    
    # Stage 12: Image job completion check (after image jobs created)
    if (audio_combination_status == 'completed' and 
        image_prompts_status == 'completed' and
        image_jobs_generation_status == 'completed'):
        return 12
    
    # Stage 11: Image job creation (after image prompts)
    if (audio_combination_status == 'completed' and 
        image_prompts_status == 'completed'):
        return 11
    
    # Stage 10: Image prompts (after audio combination)
    if audio_combination_status == 'completed':
        return 10
    
    # Stage 9: Audio combination (highest priority after subtitles)
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status == 'completed' and
        audio_moved_status == 'completed' and
        combination_planned_status == 'completed' and
        subtitle_status == 'completed'):
        return 9
    
    # Stage 8: Subtitle generation (after combination planning)
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status == 'completed' and
        audio_moved_status == 'completed' and
        combination_planned_status == 'completed'):
        return 8
    
    # Stage 7: Plan audio combinations (after files moved)
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status == 'completed' and
        audio_moved_status == 'completed'):
        return 7
    
    # Stage 6: Move audio files (ONLY after ALL audio jobs verified complete)
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status == 'completed' and
        audio_moved_status != 'completed'):
        # CRITICAL: Only allow Stage 6 if audio jobs are ACTUALLY complete
        total_jobs = book.get('total_audio_files', 0)
        completed_jobs = book.get('audio_jobs_completed', 0)
        if total_jobs > 0 and completed_jobs >= total_jobs:
            return 6  # Safe to move files
        else:
            return 5  # Must check/wait for audio job completion first
    
    # Stage 5: Audio completion checks
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status in ['processing', 'completed']):
        return 5
        
    # Stage 4: Audio job generation 
    if (parse_status == 'completed' and 
        metadata_status == 'completed' and 
        audio_status == 'pending'):
        return 4
        
    # Stage 3: Metadata addition
    if (parse_status == 'completed' and 
        metadata_status != 'completed'):
        return 3
        
    # Stage 2: Novel parsing
    if parse_status != 'completed':
        return 2
        
    # Stage 1: Fully completed (should not be selected)
    return 1


def get_book_status_summary(book: Dict) -> str:
    """Get human-readable status summary for a book."""
    stage = get_pipeline_stage(book)
    
    stage_descriptions = {
        1: "✅ All steps completed",
        12: "🔄 Checking image completion", 
        11: "🔄 Creating image jobs",
        10: "🔄 Generating image prompts",
        9: "🔄 Combining audio files",
        8: "🔄 Generating subtitles",
        7: "🔄 Planning audio combinations",
        6: "🔄 Moving audio files",
        5: "🔄 Checking audio completion",
        4: "🔄 Creating TTS jobs",
        3: "🔄 Adding metadata",
        2: "🔄 Parsing novel"
    }
    
    return stage_descriptions.get(stage, "❓ Unknown status")


def get_detailed_pipeline_steps(book: Dict) -> List[Dict]:
    """Get detailed step information for pipeline visualization."""
    steps = [
        {
            "step": 1,
            "name": "Parse Novel",
            "status": get_step_status(book, 'parse_novel_status'),
            "started_at": book.get('parse_novel_started_at'),
            "completed_at": book.get('parse_novel_completed_at'),
            "description": "Extract and chunk novel text"
        },
        {
            "step": 2,
            "name": "Add Metadata", 
            "status": get_step_status(book, 'metadata_status'),
            "started_at": book.get('metadata_started_at'),
            "completed_at": book.get('metadata_completed_at'),
            "description": "Add book metadata to first chunk"
        },
        {
            "step": 3,
            "name": "Generate TTS Jobs",
            "status": get_step_status(book, 'audio_generation_status'),
            "started_at": book.get('audio_generation_started_at'),
            "completed_at": book.get('audio_generation_completed_at'),
            "description": "Create text-to-speech audio jobs"
        },
        {
            "step": 4,
            "name": "Process Audio",
            "status": get_step_status(book, 'audio_files_moved_status'),
            "description": "Process and organize audio files"
        },
        {
            "step": 5,
            "name": "Generate Subtitles",
            "status": get_step_status(book, 'subtitle_generation_status'),
            "started_at": book.get('subtitle_generation_started_at'),
            "completed_at": book.get('subtitle_generation_completed_at'),
            "description": "Generate subtitle timing files"
        },
        {
            "step": 6,
            "name": "Combine Audio",
            "status": get_step_status(book, 'audio_combination_status'),
            "started_at": book.get('audio_combination_started_at'),
            "completed_at": book.get('audio_combination_completed_at'), 
            "description": "Combine audio files into video parts"
        },
        {
            "step": 7,
            "name": "Generate Thumbnail Prompts",
            "status": get_step_status(book, 'image_prompts_status'),
            "started_at": book.get('image_prompts_started_at'),
            "completed_at": book.get('image_prompts_completed_at'),
            "description": "Generate AI thumbnail prompts for all parts"
        },
        {
            "step": 8,
            "name": "Create Image Jobs",
            "status": get_step_status(book, 'image_jobs_generation_status'),
            "started_at": book.get('image_jobs_generation_started_at'),
            "completed_at": book.get('image_jobs_generation_completed_at'),
            "description": "Create ComfyUI image generation jobs"
        },
        {
            "step": 9,
            "name": "Generate Images",
            "status": get_step_status(book, 'image_generation_status'),
            "started_at": book.get('image_generation_started_at'),
            "completed_at": book.get('image_generation_completed_at'),
            "description": f"Process image generation jobs ({book.get('image_jobs_completed', 0)}/{book.get('total_image_jobs', 0)})"
        },
        {
            "step": 10,
            "name": "Generate Videos",
            "status": get_step_status(book, 'video_generation_status'),
            "started_at": book.get('video_generation_started_at'),
            "completed_at": book.get('video_generation_completed_at'),
            "description": "Create video files from audio and images"
        }
    ]
    
    return steps


def get_step_status(book: Dict, status_field: str) -> str:
    """Get standardized status for a pipeline step."""
    status = book.get(status_field, 'pending')
    
    if status == 'completed':
        return 'completed'
    elif status == 'failed':
        return 'failed'
    elif status == 'processing':
        return 'processing'
    else:
        return 'pending'


# Serve static files for web UI (if directory exists)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # Set database path for standalone operation
    default_db_path = "database/comfyui_agent.db"
    if os.path.exists(default_db_path):
        set_db_path(default_db_path)
        print(f"✅ Database path set: {default_db_path}")
    else:
        print(f"❌ Warning: Database not found at {default_db_path}")
        print("   UI server will still start but some features may not work")
    
    # Get port from command line or environment variable
    port = 8080  # Default port
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    elif os.environ.get("UI_PORT"):
        try:
            port = int(os.environ["UI_PORT"])
        except ValueError:
            pass
    
    print(f"Starting UI server on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)