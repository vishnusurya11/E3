"""
End-to-end integration tests for ComfyUI Agent.
"""

import pytest
import tempfile
import shutil
import os
import time
import threading
import yaml
from pathlib import Path

from comfyui_agent.db_manager import init_db, list_jobs_by_status
from comfyui_agent.monitor import scan_once
from comfyui_agent.executor import run_once
from comfyui_agent.utils.config_loader import load_global_config


class TestEndToEnd:
    """End-to-end integration tests."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create directory structure
        self.processing_dir = Path(self.temp_dir) / "jobs" / "processing"
        self.finished_dir = Path(self.temp_dir) / "jobs" / "finished"
        self.db_path = str(Path(self.temp_dir) / "test.db")
        
        (self.processing_dir / "image").mkdir(parents=True)
        (self.processing_dir / "video").mkdir(parents=True)
        (self.finished_dir / "image").mkdir(parents=True)
        (self.finished_dir / "video").mkdir(parents=True)
        
        # Initialize database
        init_db(self.db_path)
        
        # Create test config
        self.config = {
            "paths": {
                "jobs_processing": str(self.processing_dir),
                "jobs_finished": str(self.finished_dir),
                "database": self.db_path
            },
            "comfyui": {
                "api_base_url": "http://127.0.0.1:8188",
                "timeout_seconds": 60
            },
            "default_priority": 50,
            "retry_limit": 2,
            "poll_interval_ms": 100
        }
        
        # Create test workflows
        self.workflows = {
            "wf_test": {
                "template_path": "workflows/test.json",
                "required_inputs": ["prompt", "seed"]
            }
        }

    def teardown_method(self):
        """Clean up test environment."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_full_job_lifecycle(self):
        """Test complete job lifecycle from ingestion to completion."""
        # Create a test job YAML
        job_yaml = self.processing_dir / "image" / "T2I_20250809150000_1_test.yaml"
        job_content = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 30,
            "inputs": {
                "prompt": "test prompt",
                "seed": 12345
            },
            "outputs": {
                "file_path": str(self.finished_dir / "image" / "output.png")
            }
        }
        
        with open(job_yaml, 'w') as f:
            yaml.dump(job_content, f)
        
        # Step 1: Monitor should detect and ingest the job
        results = scan_once(self.config, self.workflows, self.db_path)
        assert len(results) == 1
        assert results[0]["status"] == "accepted"
        
        # Verify job is in database as pending
        jobs = list_jobs_by_status(self.db_path, "pending")
        assert len(jobs) == 1
        assert jobs[0]["config_name"] == "T2I_20250809150000_1_test.yaml"
        assert jobs[0]["priority"] == 30
        
        # Step 2: Executor should lease and process the job
        # Note: This will fail without actual ComfyUI connection
        # but we can test the leasing mechanism
        from unittest.mock import patch
        
        with patch('comfyui_agent.executor.invoke_comfyui') as mock_invoke:
            mock_invoke.return_value = {"status": "completed", "outputs": []}
            
            with patch('comfyui_agent.executor.write_outputs') as mock_write:
                mock_write.return_value = {"saved": ["/fake/output.png"]}
                
                # Run executor once
                did_work = run_once(self.config, self.workflows, self.db_path, "test_worker")
                assert did_work is True
        
        # Verify job is completed
        jobs = list_jobs_by_status(self.db_path, "done")
        assert len(jobs) == 1
        
        # Verify YAML was moved to finished directory
        finished_yaml = self.finished_dir / "T2I" / "T2I_20250809150000_1_test.yaml"
        assert finished_yaml.exists()
        assert not job_yaml.exists()

    def test_priority_ordering(self):
        """Test that jobs are processed in priority order."""
        # Create multiple jobs with different priorities
        jobs_data = [
            ("T2I_20250809150001_1_low.yaml", 80),
            ("T2I_20250809150002_1_high.yaml", 10),
            ("T2I_20250809150003_1_medium.yaml", 50),
        ]
        
        for filename, priority in jobs_data:
            job_yaml = self.processing_dir / "image" / filename
            job_content = {
                "job_type": "T2I",
                "workflow_id": "wf_test",
                "priority": priority,
                "inputs": {"prompt": "test", "seed": 1},
                "outputs": {"file_path": "/output.png"}
            }
            with open(job_yaml, 'w') as f:
                yaml.dump(job_content, f)
        
        # Ingest all jobs
        results = scan_once(self.config, self.workflows, self.db_path)
        assert len(results) == 3
        
        # Check processing order
        from comfyui_agent.db_manager import lease_next_job
        
        # First job should be high priority (10)
        job1 = lease_next_job(self.db_path, "worker", 60)
        assert "high" in job1["config_name"]
        
        # Second job should be medium priority (50)
        job2 = lease_next_job(self.db_path, "worker", 60)
        assert "medium" in job2["config_name"]
        
        # Third job should be low priority (80)
        job3 = lease_next_job(self.db_path, "worker", 60)
        assert "low" in job3["config_name"]

    def test_retry_mechanism(self):
        """Test job retry on failure."""
        # Create a job
        job_yaml = self.processing_dir / "image" / "T2I_20250809150004_1_retry.yaml"
        job_content = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "retry_limit": 2,
            "inputs": {"prompt": "test", "seed": 1},
            "outputs": {"file_path": "/output.png"}
        }
        
        with open(job_yaml, 'w') as f:
            yaml.dump(job_content, f)
        
        # Ingest job
        scan_once(self.config, self.workflows, self.db_path)
        
        # Simulate failure with retry
        from comfyui_agent.db_manager import lease_next_job, complete_job
        
        # First attempt
        job = lease_next_job(self.db_path, "worker", 60)
        assert job["run_count"] == 1
        
        # Fail the job
        complete_job(self.db_path, job["id"], success=False,
                    updates={"error_trace": "Test failure"})
        
        # Job should be back to pending
        jobs = list_jobs_by_status(self.db_path, "pending")
        assert len(jobs) == 1
        assert jobs[0]["retries_attempted"] == 1
        
        # Second attempt
        job = lease_next_job(self.db_path, "worker", 60)
        assert job["run_count"] == 2
        
        # Fail again
        complete_job(self.db_path, job["id"], success=False,
                    updates={"error_trace": "Test failure 2"})
        
        # Job should now be failed (retry limit reached)
        failed_jobs = list_jobs_by_status(self.db_path, "failed")
        assert len(failed_jobs) == 1
        assert failed_jobs[0]["retries_attempted"] == 2

    def test_god_mode(self):
        """Test God Mode priority override."""
        from comfyui_agent.queue_manager import apply_god_mode
        
        # Create a normal priority job
        job_yaml = self.processing_dir / "image" / "T2I_20250809150005_1_normal.yaml"
        job_content = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 50,
            "inputs": {"prompt": "test", "seed": 1},
            "outputs": {"file_path": "/output.png"}
        }
        
        with open(job_yaml, 'w') as f:
            yaml.dump(job_content, f)
        
        # Ingest job
        scan_once(self.config, self.workflows, self.db_path)
        
        # Apply God Mode
        apply_god_mode(self.db_path, "T2I_20250809150005_1_normal.yaml")
        
        # Check priority is now 1
        from comfyui_agent.db_manager import get_job_by_config_name
        job = get_job_by_config_name(self.db_path, "T2I_20250809150005_1_normal.yaml")
        assert job["priority"] == 1

    def test_concurrent_operations(self):
        """Test concurrent monitor and executor operations."""
        # This is a simplified test - full concurrency testing would require
        # more sophisticated setup
        
        # Create initial job
        job_yaml = self.processing_dir / "image" / "T2I_20250809150006_1_concurrent.yaml"
        job_content = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "inputs": {"prompt": "test", "seed": 1},
            "outputs": {"file_path": "/output.png"}
        }
        
        with open(job_yaml, 'w') as f:
            yaml.dump(job_content, f)
        
        # Run monitor
        scan_once(self.config, self.workflows, self.db_path)
        
        # Verify no race conditions in database operations
        from comfyui_agent.db_manager import lease_next_job
        
        # Multiple workers trying to lease
        job1 = lease_next_job(self.db_path, "worker1", 60)
        job2 = lease_next_job(self.db_path, "worker2", 60)
        
        # Only one should get the job
        assert job1 is not None
        assert job2 is None