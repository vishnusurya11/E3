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

from comfyui_agent.db_manager import (
    get_job_by_config_name,
    list_jobs_by_status,
    get_db_connection
)
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
        raise RuntimeError("Database path not configured")
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
                UPDATE jobs
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
                FROM jobs
                GROUP BY status
            """)
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            # Get total jobs
            cursor.execute("SELECT COUNT(*) as total FROM jobs")
            total = cursor.fetchone()["total"]
            
            # Get average duration for completed jobs
            cursor.execute("""
                SELECT AVG(duration) as avg_duration
                FROM jobs
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


# Serve static files for web UI (if directory exists)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    import sys
    
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