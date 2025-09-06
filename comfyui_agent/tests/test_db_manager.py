"""
Tests for database manager module.
Following TDD principles - tests written before implementation.
"""

import pytest
import tempfile
import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

# Import the module we're going to implement
from comfyui_agent.db_manager import (
    init_db,
    upsert_job,
    lease_next_job,
    complete_job,
    recover_orphans,
    get_job_by_config_name,
    list_jobs_by_status
)


class TestInitDb:
    """Tests for init_db function."""

    def test_creates_tables_and_indices(self, tmp_path: Path) -> None:
        """Test that database schema is created correctly."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        
        # Act
        init_db(db_path)
        
        # Assert - Check tables exist
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check jobs table exists with all columns
        cursor.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in cursor.fetchall()}
        expected_columns = {
            "id", "config_name", "job_type", "workflow_id", "priority",
            "status", "run_count", "retries_attempted", "retry_limit",
            "start_time", "end_time", "duration", "error_trace", "metadata",
            "worker_id", "lease_expires_at"
        }
        assert expected_columns.issubset(columns)
        
        # Check indices exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {row[0] for row in cursor.fetchall()}
        assert "idx_jobs_status_priority" in indices
        assert "idx_jobs_started" in indices
        
        conn.close()

    def test_idempotent_multiple_calls(self, tmp_path: Path) -> None:
        """Test that init_db can be called multiple times safely."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        
        # Act - Call multiple times
        init_db(db_path)
        init_db(db_path)
        init_db(db_path)
        
        # Assert - Should not raise and db should be valid
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM comfyui_jobs")
        assert cursor.fetchone()[0] == 0  # No jobs yet
        conn.close()


class TestUpsertJob:
    """Tests for upsert_job function."""

    def test_insert_new_job(self, tmp_path: Path) -> None:
        """Test inserting a new job."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_data = {
            "config_name": "T2I_20250809120030_1_test.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 50,
            "status": "pending",
            "retry_limit": 2
        }
        
        # Act
        job_id = upsert_job(db_path, job_data)
        
        # Assert
        assert job_id > 0
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM comfyui_jobs WHERE id=?", (job_id,))
        row = cursor.fetchone()
        assert row is not None
        conn.close()

    def test_update_existing_job_preserves_status(self, tmp_path: Path) -> None:
        """Test that updating existing job doesn't regress status."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_data = {
            "config_name": "T2I_20250809120030_1_test.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 50,
            "status": "done"
        }
        
        # Insert job as done
        job_id1 = upsert_job(db_path, job_data)
        
        # Try to update with pending status
        job_data["status"] = "pending"
        job_data["priority"] = 10  # Change something else
        
        # Act
        job_id2 = upsert_job(db_path, job_data)
        
        # Assert - Should be same job, status should remain done
        assert job_id1 == job_id2
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, priority FROM comfyui_jobs WHERE id=?", (job_id1,))
        status, priority = cursor.fetchone()
        assert status == "done"  # Not regressed
        assert priority == 10  # Other field updated
        conn.close()

    def test_duplicate_config_name_returns_same_id(self, tmp_path: Path) -> None:
        """Test that duplicate config_name doesn't create new job."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_data = {
            "config_name": "T2I_20250809120030_1_test.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 50,
            "status": "pending"
        }
        
        # Act
        job_id1 = upsert_job(db_path, job_data)
        job_id2 = upsert_job(db_path, job_data)
        
        # Assert
        assert job_id1 == job_id2


class TestLeaseNextJob:
    """Tests for lease_next_job function."""

    def test_leases_job_by_priority_then_fifo(self, tmp_path: Path) -> None:
        """Test that jobs are leased in correct order."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Insert jobs with different priorities
        upsert_job(db_path, {
            "config_name": "job1.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        upsert_job(db_path, {
            "config_name": "job2.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 10,  # Higher priority (lower number)
            "status": "pending"
        })
        upsert_job(db_path, {
            "config_name": "job3.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 10,  # Same as job2, but inserted later
            "status": "pending"
        })
        
        # Act
        job1 = lease_next_job(db_path, "worker1", 60)
        job2 = lease_next_job(db_path, "worker1", 60)
        job3 = lease_next_job(db_path, "worker1", 60)
        
        # Assert - Should get job2, then job3, then job1
        assert job1["config_name"] == "job2.yaml"
        assert job2["config_name"] == "job3.yaml"
        assert job3["config_name"] == "job1.yaml"

    def test_leased_job_marked_as_processing(self, tmp_path: Path) -> None:
        """Test that leased job status changes to processing."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        # Act
        job = lease_next_job(db_path, "worker1", 60)
        
        # Assert
        assert job["status"] == "processing"
        assert job["worker_id"] == "worker1"
        assert job["lease_expires_at"] is not None

    def test_returns_none_when_no_pending_jobs(self, tmp_path: Path) -> None:
        """Test that None is returned when no jobs available."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Act
        job = lease_next_job(db_path, "worker1", 60)
        
        # Assert
        assert job is None

    def test_skips_already_processing_jobs(self, tmp_path: Path) -> None:
        """Test that jobs already processing are not leased again."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        upsert_job(db_path, {
            "config_name": "job1.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 10,
            "status": "processing"  # Already processing
        })
        upsert_job(db_path, {
            "config_name": "job2.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        # Act
        job = lease_next_job(db_path, "worker2", 60)
        
        # Assert - Should get job2, not job1
        assert job["config_name"] == "job2.yaml"

    def test_increments_run_count_on_lease(self, tmp_path: Path) -> None:
        """Test that run_count is incremented when job is leased."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        # Act
        job = lease_next_job(db_path, "worker1", 60)
        
        # Assert
        assert job["run_count"] == 1


class TestCompleteJob:
    """Tests for complete_job function."""

    def test_complete_job_success(self, tmp_path: Path) -> None:
        """Test marking job as successfully completed."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "processing"
        })
        
        updates = {
            "metadata": '{"output": "/path/to/file.png"}'
        }
        
        # Act
        complete_job(db_path, job_id, success=True, updates=updates)
        
        # Assert
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, metadata, end_time FROM comfyui_jobs WHERE id=?", (job_id,))
        status, metadata, end_time = cursor.fetchone()
        assert status == "done"
        assert metadata == '{"output": "/path/to/file.png"}'
        assert end_time is not None
        conn.close()

    def test_complete_job_failure_with_retries_remaining(self, tmp_path: Path) -> None:
        """Test marking job as failed with retries remaining."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "processing",
            "retry_limit": 2,
            "retries_attempted": 0
        })
        
        updates = {
            "error_trace": "Connection timeout"
        }
        
        # Act
        complete_job(db_path, job_id, success=False, updates=updates)
        
        # Assert
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, retries_attempted, error_trace FROM comfyui_jobs WHERE id=?",
            (job_id,)
        )
        status, retries, error = cursor.fetchone()
        assert status == "pending"  # Back to pending for retry
        assert retries == 1
        assert error == "Connection timeout"
        conn.close()

    def test_complete_job_failure_no_retries_left(self, tmp_path: Path) -> None:
        """Test marking job as failed with no retries remaining."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "processing",
            "retry_limit": 2,
            "retries_attempted": 2  # Already at limit
        })
        
        updates = {
            "error_trace": "Final failure"
        }
        
        # Act
        complete_job(db_path, job_id, success=False, updates=updates)
        
        # Assert
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, error_trace FROM comfyui_jobs WHERE id=?", (job_id,))
        status, error = cursor.fetchone()
        assert status == "failed"
        assert error == "Final failure"
        conn.close()


class TestRecoverOrphans:
    """Tests for recover_orphans function."""

    def test_recovers_expired_leases(self, tmp_path: Path) -> None:
        """Test that jobs with expired leases are recovered."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Insert job with expired lease
        past_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO comfyui_jobs (config_name, job_type, workflow_id, priority, status,
                            worker_id, lease_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("job.yaml", "T2I", "wf", 50, "processing", "worker1", past_time))
        conn.commit()
        conn.close()
        
        # Act
        recovered = recover_orphans(db_path, datetime.now())
        
        # Assert
        assert recovered == 1
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, worker_id FROM comfyui_jobs WHERE config_name=?", ("job.yaml",))
        status, worker_id = cursor.fetchone()
        assert status == "pending"
        assert worker_id is None
        conn.close()

    def test_doesnt_recover_active_leases(self, tmp_path: Path) -> None:
        """Test that jobs with active leases are not recovered."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Insert job with future lease
        future_time = (datetime.now() + timedelta(minutes=5)).isoformat()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO comfyui_jobs (config_name, job_type, workflow_id, priority, status,
                            worker_id, lease_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("job.yaml", "T2I", "wf", 50, "processing", "worker1", future_time))
        conn.commit()
        conn.close()
        
        # Act
        recovered = recover_orphans(db_path, datetime.now())
        
        # Assert
        assert recovered == 0


class TestHelperFunctions:
    """Tests for helper query functions."""

    def test_get_job_by_config_name(self, tmp_path: Path) -> None:
        """Test retrieving job by config name."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        upsert_job(db_path, {
            "config_name": "target.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 30,
            "status": "pending"
        })
        
        # Act
        job = get_job_by_config_name(db_path, "target.yaml")
        
        # Assert
        assert job is not None
        assert job["config_name"] == "target.yaml"
        assert job["priority"] == 30

    def test_list_jobs_by_status(self, tmp_path: Path) -> None:
        """Test listing jobs filtered by status."""
        # Arrange
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        upsert_job(db_path, {"config_name": "job1.yaml", "job_type": "T2I",
                            "workflow_id": "wf", "status": "pending"})
        upsert_job(db_path, {"config_name": "job2.yaml", "job_type": "T2I",
                            "workflow_id": "wf", "status": "done"})
        upsert_job(db_path, {"config_name": "job3.yaml", "job_type": "T2I",
                            "workflow_id": "wf", "status": "pending"})
        
        # Act
        pending_jobs = list_jobs_by_status(db_path, "pending")
        done_jobs = list_jobs_by_status(db_path, "done")
        all_jobs = list_jobs_by_status(db_path, None)
        
        # Assert
        assert len(pending_jobs) == 2
        assert len(done_jobs) == 1
        assert len(all_jobs) == 3