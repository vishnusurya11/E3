"""
Tests for UI server module (FastAPI).
Following TDD principles - tests written before implementation.
"""

import pytest
import json
from fastapi.testclient import TestClient
from typing import Dict, Any

# Import the module we're going to implement
from comfyui_agent.ui_server import app, set_db_path


class TestListQueue:
    """Tests for list_queue endpoint."""

    def setup_method(self):
        """Set up test client and database."""
        from comfyui_agent.db_manager import init_db, upsert_job
        import tempfile
        
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        init_db(self.db_path)
        set_db_path(self.db_path)
        
        # Insert test jobs
        upsert_job(self.db_path, {
            "config_name": "job1.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 10,
            "status": "pending"
        })
        upsert_job(self.db_path, {
            "config_name": "job2.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "done"
        })
        
        self.client = TestClient(app)

    def test_list_all_jobs(self) -> None:
        """Test listing all jobs."""
        # Act
        response = self.client.get("/api/queue")
        
        # Assert
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 2

    def test_list_jobs_by_status(self) -> None:
        """Test filtering jobs by status."""
        # Act
        response = self.client.get("/api/queue?status=pending")
        
        # Assert
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["status"] == "pending"

    def test_invalid_status_returns_error(self) -> None:
        """Test that invalid status returns error."""
        # Act
        response = self.client.get("/api/queue?status=invalid")
        
        # Assert
        assert response.status_code == 400


class TestSetPriority:
    """Tests for set_priority endpoint."""

    def setup_method(self):
        """Set up test client and database."""
        from comfyui_agent.db_manager import init_db, upsert_job
        import tempfile
        
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        init_db(self.db_path)
        set_db_path(self.db_path)
        
        upsert_job(self.db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        self.client = TestClient(app)

    def test_update_priority_success(self) -> None:
        """Test successful priority update."""
        # Act
        response = self.client.put("/api/queue/job.yaml/priority", json={"priority": 25})
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["config_name"] == "job.yaml"
        assert result["priority"] == 25

    def test_priority_clamped_to_range(self) -> None:
        """Test that priority is clamped to valid range."""
        # Act
        response = self.client.put("/api/queue/job.yaml/priority", json={"priority": 1500})
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["priority"] == 999  # Clamped to max

    def test_nonexistent_job_returns_404(self) -> None:
        """Test that non-existent job returns 404."""
        # Act
        response = self.client.put("/api/queue/nonexistent.yaml/priority", json={"priority": 50})
        
        # Assert
        assert response.status_code == 404


class TestRetryJob:
    """Tests for retry_job endpoint."""

    def setup_method(self):
        """Set up test client and database."""
        from comfyui_agent.db_manager import init_db, upsert_job
        import tempfile
        
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        init_db(self.db_path)
        set_db_path(self.db_path)
        
        # Insert failed job
        upsert_job(self.db_path, {
            "config_name": "failed.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "status": "failed"
        })
        
        # Insert successful job
        upsert_job(self.db_path, {
            "config_name": "done.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "status": "done"
        })
        
        self.client = TestClient(app)

    def test_retry_failed_job(self) -> None:
        """Test retrying a failed job."""
        # Act
        response = self.client.post("/api/queue/failed.yaml/retry")
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "pending"

    def test_cannot_retry_completed_job(self) -> None:
        """Test that completed job cannot be retried."""
        # Act
        response = self.client.post("/api/queue/done.yaml/retry")
        
        # Assert
        assert response.status_code == 400
        assert "not failed" in response.json()["detail"].lower()

    def test_nonexistent_job_returns_404(self) -> None:
        """Test that non-existent job returns 404."""
        # Act
        response = self.client.post("/api/queue/nonexistent.yaml/retry")
        
        # Assert
        assert response.status_code == 404


class TestJobDetails:
    """Tests for job_details endpoint."""

    def setup_method(self):
        """Set up test client and database."""
        from comfyui_agent.db_manager import init_db, upsert_job, complete_job
        import tempfile
        
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        init_db(self.db_path)
        set_db_path(self.db_path)
        
        job_id = upsert_job(self.db_path, {
            "config_name": "detailed.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 30,
            "status": "processing"
        })
        
        # Add some error info
        complete_job(self.db_path, job_id, success=False, updates={
            "error_trace": "Test error trace"
        })
        
        self.client = TestClient(app)

    def test_get_job_details(self) -> None:
        """Test getting full job details."""
        # Act
        response = self.client.get("/api/queue/detailed.yaml")
        
        # Assert
        assert response.status_code == 200
        job = response.json()
        assert job["config_name"] == "detailed.yaml"
        assert job["priority"] == 30
        assert "error_trace" in job

    def test_nonexistent_job_returns_404(self) -> None:
        """Test that non-existent job returns 404."""
        # Act
        response = self.client.get("/api/queue/nonexistent.yaml")
        
        # Assert
        assert response.status_code == 404


class TestGodMode:
    """Tests for god_mode endpoint."""

    def setup_method(self):
        """Set up test client and database."""
        from comfyui_agent.db_manager import init_db, upsert_job
        import tempfile
        
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test.db"
        init_db(self.db_path)
        set_db_path(self.db_path)
        
        upsert_job(self.db_path, {
            "config_name": "urgent.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        self.client = TestClient(app)

    def test_god_mode_sets_priority_to_one(self) -> None:
        """Test that god mode sets priority to 1."""
        # Act
        response = self.client.post("/api/queue/urgent.yaml/god-mode")
        
        # Assert
        assert response.status_code == 200
        result = response.json()
        assert result["priority"] == 1

    def test_nonexistent_job_returns_404(self) -> None:
        """Test that non-existent job returns 404."""
        # Act
        response = self.client.post("/api/queue/nonexistent.yaml/god-mode")
        
        # Assert
        assert response.status_code == 404


class TestHealthCheck:
    """Tests for health check endpoint."""

    def setup_method(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_health_check(self) -> None:
        """Test health check endpoint."""
        # Act
        response = self.client.get("/health")
        
        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"