"""
Tests for monitor module.
Following TDD principles - tests written before implementation.
"""

import pytest
import yaml
import time
from pathlib import Path
from typing import Dict, Any, List
import threading

# Import the module we're going to implement
from comfyui_agent.monitor import (
    scan_once,
    run_monitor_loop,
    process_yaml_file
)


class TestProcessYamlFile:
    """Tests for process_yaml_file function."""

    def test_processes_valid_yaml(self, tmp_path: Path) -> None:
        """Test processing a valid YAML file."""
        # Arrange
        from comfyui_agent.db_manager import init_db, get_job_by_config_name
        
        yaml_file = tmp_path / "T2I_20250809120030_1_test.yaml"
        yaml_file.write_text("""
job_type: T2I
workflow_id: wf_test
priority: 30
inputs:
  prompt: test prompt
  seed: 12345
outputs:
  file_path: /output/test.png
""")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        workflows = {
            "wf_test": {
                "required_inputs": ["prompt", "seed"]
            }
        }
        
        defaults = {"default_priority": 50, "retry_limit": 2}
        
        # Act
        result = process_yaml_file(str(yaml_file), workflows, db_path, defaults)
        
        # Assert
        assert result["status"] == "accepted"
        assert result["path"] == str(yaml_file)
        
        # Check job was inserted
        job = get_job_by_config_name(db_path, "T2I_20250809120030_1_test.yaml")
        assert job is not None
        assert job["priority"] == 30

    def test_rejects_invalid_yaml_schema(self, tmp_path: Path) -> None:
        """Test rejection of YAML with invalid schema."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        yaml_file = tmp_path / "T2I_20250809120030_1_bad.yaml"
        yaml_file.write_text("""
job_type: INVALID_TYPE
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        defaults = {"default_priority": 50}
        
        # Act
        result = process_yaml_file(str(yaml_file), workflows, db_path, defaults)
        
        # Assert
        assert result["status"] == "rejected"
        assert "Invalid job_type" in result["reason"] or "Invalid job type" in result["reason"]

    def test_rejects_malformed_yaml(self, tmp_path: Path) -> None:
        """Test rejection of malformed YAML."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        yaml_file = tmp_path / "T2I_20250809120030_1_malformed.yaml"
        yaml_file.write_text("invalid: yaml: content: [")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Act
        result = process_yaml_file(str(yaml_file), {}, db_path, {})
        
        # Assert
        assert result["status"] == "rejected"
        assert "Invalid YAML" in result["reason"]


class TestScanOnce:
    """Tests for scan_once function."""

    def test_detects_and_processes_yaml_files(self, tmp_path: Path) -> None:
        """Test that YAML files are detected and processed."""
        # Arrange
        from comfyui_agent.db_manager import init_db, list_jobs_by_status
        
        processing_dir = tmp_path / "processing"
        (processing_dir / "image").mkdir(parents=True)
        (processing_dir / "video").mkdir(parents=True)
        
        # Create test YAML files
        yaml1 = processing_dir / "image" / "T2I_20250809120030_1_test.yaml"
        yaml1.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test1
outputs:
  file_path: /output/test1.png
""")
        
        yaml2 = processing_dir / "video" / "T2V_20250809120030_2_test.yaml"
        yaml2.write_text("""
job_type: T2V
workflow_id: wf_test
inputs:
  prompt: test2
outputs:
  file_path: /output/test2.mp4
""")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        cfg = {
            "paths": {"jobs_processing": str(processing_dir)},
            "default_priority": 50,
            "retry_limit": 2
        }
        
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        
        # Act
        results = scan_once(cfg, workflows, db_path)
        
        # Assert
        assert len(results) == 2
        accepted = [r for r in results if r["status"] == "accepted"]
        assert len(accepted) == 2
        
        # Check jobs were inserted
        jobs = list_jobs_by_status(db_path, None)
        assert len(jobs) == 2

    def test_ignores_non_yaml_files(self, tmp_path: Path) -> None:
        """Test that non-YAML files are ignored."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        processing_dir = tmp_path / "processing"
        processing_dir.mkdir()
        
        # Create non-YAML files
        (processing_dir / "test.txt").write_text("not yaml")
        (processing_dir / "test.json").write_text("{}")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        cfg = {"paths": {"jobs_processing": str(processing_dir)}}
        
        # Act
        results = scan_once(cfg, {}, db_path)
        
        # Assert
        assert len(results) == 0

    def test_handles_duplicate_config_names(self, tmp_path: Path) -> None:
        """Test that duplicate config names are handled gracefully."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job
        
        processing_dir = tmp_path / "processing"
        processing_dir.mkdir()
        
        yaml_file = processing_dir / "T2I_20250809120030_1_test.yaml"
        yaml_file.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Pre-insert the job
        upsert_job(db_path, {
            "config_name": "T2I_20250809120030_1_test.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "status": "pending"
        })
        
        cfg = {
            "paths": {"jobs_processing": str(processing_dir)},
            "default_priority": 50
        }
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        
        # Act
        results = scan_once(cfg, workflows, db_path)
        
        # Assert - Should still process but not duplicate
        assert len(results) == 1
        assert results[0]["status"] == "accepted"


class TestRunMonitorLoop:
    """Tests for run_monitor_loop function."""

    def test_loop_runs_and_stops(self, tmp_path: Path) -> None:
        """Test that monitor loop runs and can be stopped."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        processing_dir = tmp_path / "processing"
        processing_dir.mkdir()
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        cfg = {
            "paths": {"jobs_processing": str(processing_dir)},
            "poll_interval_ms": 100  # Fast polling for test
        }
        
        stop_event = threading.Event()
        
        # Act - Run loop in thread
        def run_loop():
            run_monitor_loop(cfg, {}, db_path, stop_event)
        
        thread = threading.Thread(target=run_loop)
        thread.start()
        
        # Let it run briefly
        time.sleep(0.3)
        
        # Stop the loop
        stop_event.set()
        thread.join(timeout=1.0)
        
        # Assert
        assert not thread.is_alive()

    def test_loop_processes_new_files(self, tmp_path: Path) -> None:
        """Test that loop detects and processes new files."""
        # Arrange
        from comfyui_agent.db_manager import init_db, list_jobs_by_status
        
        processing_dir = tmp_path / "processing"
        processing_dir.mkdir()
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        cfg = {
            "paths": {"jobs_processing": str(processing_dir)},
            "poll_interval_ms": 100,
            "default_priority": 50
        }
        
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        stop_event = threading.Event()
        
        # Start loop in thread
        def run_loop():
            run_monitor_loop(cfg, workflows, db_path, stop_event)
        
        thread = threading.Thread(target=run_loop)
        thread.start()
        
        # Wait a bit for loop to start
        time.sleep(0.2)
        
        # Add a new file
        yaml_file = processing_dir / "T2I_20250809120030_1_test.yaml"
        yaml_file.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        # Wait for processing
        time.sleep(0.3)
        
        # Stop loop
        stop_event.set()
        thread.join(timeout=1.0)
        
        # Assert - Job should be in database
        jobs = list_jobs_by_status(db_path, None)
        assert len(jobs) == 1
        assert jobs[0]["config_name"] == "T2I_20250809120030_1_test.yaml"