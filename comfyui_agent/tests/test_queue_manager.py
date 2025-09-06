"""
Tests for queue manager module.
Following TDD principles - tests written before implementation.
"""

import pytest
from typing import Dict, Any

# Import the module we're going to implement
from comfyui_agent.queue_manager import (
    should_run_next,
    apply_god_mode,
    set_job_priority
)


class TestShouldRunNext:
    """Tests for should_run_next function."""

    def test_returns_true_when_idle(self) -> None:
        """Test that True is returned when system is idle."""
        # Act
        result = should_run_next(current_busy=False)
        
        # Assert
        assert result is True

    def test_returns_false_when_busy(self) -> None:
        """Test that False is returned when system is busy."""
        # Act
        result = should_run_next(current_busy=True)
        
        # Assert
        assert result is False


class TestApplyGodMode:
    """Tests for apply_god_mode function."""

    def test_sets_priority_to_one(self, tmp_path) -> None:
        """Test that god mode sets priority to 1."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job, get_job_by_config_name
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Insert job with normal priority
        upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf",
            "priority": 50,
            "status": "pending"
        })
        
        # Act
        apply_god_mode(db_path, "job.yaml")
        
        # Assert
        job = get_job_by_config_name(db_path, "job.yaml")
        assert job["priority"] == 1

    def test_handles_nonexistent_job_gracefully(self, tmp_path) -> None:
        """Test that non-existent job is handled without error."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Act & Assert - should not raise
        apply_god_mode(db_path, "nonexistent.yaml")


class TestSetJobPriority:
    """Tests for set_job_priority function."""

    def test_updates_priority_within_bounds(self, tmp_path) -> None:
        """Test that priority is updated within valid bounds."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job, get_job_by_config_name
        
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
        set_job_priority(db_path, "job.yaml", 25)
        
        # Assert
        job = get_job_by_config_name(db_path, "job.yaml")
        assert job["priority"] == 25

    def test_clamps_priority_to_valid_range(self, tmp_path) -> None:
        """Test that priority is clamped to 1-999 range."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job, get_job_by_config_name
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
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
            "priority": 50,
            "status": "pending"
        })
        
        # Act - Try to set out of bounds priorities
        set_job_priority(db_path, "job1.yaml", -10)
        set_job_priority(db_path, "job2.yaml", 1500)
        
        # Assert
        job1 = get_job_by_config_name(db_path, "job1.yaml")
        job2 = get_job_by_config_name(db_path, "job2.yaml")
        assert job1["priority"] == 1  # Clamped to minimum
        assert job2["priority"] == 999  # Clamped to maximum

    def test_raises_on_invalid_priority_type(self, tmp_path) -> None:
        """Test that invalid priority type raises error."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Act & Assert
        with pytest.raises(ValueError, match="Priority must be an integer"):
            set_job_priority(db_path, "job.yaml", "high")  # type: ignore

    def test_handles_nonexistent_job(self, tmp_path) -> None:
        """Test handling of non-existent job."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        # Act & Assert - should not raise but log warning
        set_job_priority(db_path, "nonexistent.yaml", 50)