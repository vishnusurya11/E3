"""
Tests for executor module (ComfyUI client).
Following TDD principles - tests written before implementation.
"""

import pytest
import json
import tempfile
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Import the module we're going to implement
from comfyui_agent.executor import (
    build_payload,
    invoke_comfyui,
    write_outputs,
    execute_job,
    run_once,
    ComfyUIClient
)


class TestBuildPayload:
    """Tests for build_payload function."""

    def test_builds_valid_payload(self) -> None:
        """Test building a valid ComfyUI payload."""
        # Arrange
        workflow_id = "wf_test"
        inputs = {
            "prompt": "test prompt",
            "seed": 12345,
            "steps": 30
        }
        workflows = {
            "wf_test": {
                "template_path": "workflows/test.json",
                "required_inputs": ["prompt", "seed", "steps"]
            }
        }
        
        # Act
        payload = build_payload(workflow_id, inputs, workflows)
        
        # Assert - payload should be the workflow template with inputs mapped
        assert isinstance(payload, dict)
        # Check that the workflow nodes exist
        assert "1" in payload  # CLIP Text Encode node
        assert "3" in payload  # KSampler node
        # Check that inputs were mapped correctly
        assert payload["1"]["inputs"]["text"] == "test prompt"
        assert payload["3"]["inputs"]["seed"] == 12345
        assert payload["3"]["inputs"]["steps"] == 30

    def test_validates_required_inputs(self) -> None:
        """Test that missing required inputs raise error."""
        # Arrange
        workflow_id = "wf_test"
        inputs = {"prompt": "test"}  # Missing seed and steps
        workflows = {
            "wf_test": {
                "template_path": "workflows/test.json",
                "required_inputs": ["prompt", "seed", "steps"]
            }
        }
        
        # Act & Assert
        with pytest.raises(ValueError, match="Missing required inputs"):
            build_payload(workflow_id, inputs, workflows)

    def test_unknown_workflow_raises_error(self) -> None:
        """Test that unknown workflow raises error."""
        # Arrange
        workflow_id = "wf_unknown"
        inputs = {}
        workflows = {"wf_other": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Unknown workflow"):
            build_payload(workflow_id, inputs, workflows)


class TestInvokeComfyUI:
    """Tests for invoke_comfyui function."""

    @patch('comfyui_agent.executor.httpx.Client')
    @patch('comfyui_agent.executor.websocket.WebSocket')
    def test_successful_invocation(self, mock_ws_class, mock_client_class) -> None:
        """Test successful ComfyUI invocation."""
        # Arrange
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_response = Mock()
        mock_response.json.return_value = {"prompt_id": "test-id-123"}
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        mock_ws = Mock()
        mock_ws.recv.side_effect = [
            json.dumps({"type": "executing", "data": {"prompt_id": "test-id-123", "node": "1"}}),
            json.dumps({"type": "executing", "data": {"prompt_id": "test-id-123", "node": None}})
        ]
        mock_ws_class.return_value = mock_ws
        
        payload = {"prompt": {}, "client_id": "test-client"}
        
        # Act
        result = invoke_comfyui("http://127.0.0.1:8188", payload, 60)
        
        # Assert
        assert result["prompt_id"] == "test-id-123"
        assert result["status"] == "completed"

    @patch('comfyui_agent.executor.httpx.Client')
    def test_timeout_raises_error(self, mock_client_class) -> None:
        """Test that timeout raises RuntimeError."""
        # Arrange
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client.post.side_effect = Exception("Connection timeout")
        mock_client_class.return_value = mock_client
        
        payload = {"prompt": {}, "client_id": "test-client"}
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="ComfyUI invocation failed"):
            invoke_comfyui("http://127.0.0.1:8188", payload, 1)

    @patch('comfyui_agent.executor.httpx.Client')
    def test_malformed_response_raises_error(self, mock_client_class) -> None:
        """Test that malformed response raises RuntimeError."""
        # Arrange
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_response = Mock()
        mock_response.json.return_value = {}  # Missing prompt_id
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        payload = {"prompt": {}, "client_id": "test-client"}
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="No prompt_id in response"):
            invoke_comfyui("http://127.0.0.1:8188", payload, 60)


class TestWriteOutputs:
    """Tests for write_outputs function."""

    def test_writes_output_files(self, tmp_path: Path) -> None:
        """Test writing output files to disk."""
        # Arrange
        result = {
            "outputs": [
                {"type": "image", "data": b"fake_image_data", "filename": "output.png"}
            ]
        }
        dest_paths = {
            "output_dir": str(tmp_path / "outputs")
        }
        
        # Act
        metadata = write_outputs(result, dest_paths)
        
        # Assert
        assert "saved" in metadata
        assert len(metadata["saved"]) == 1
        assert metadata["saved"][0].endswith("output.png")
        assert Path(metadata["saved"][0]).exists()

    def test_creates_missing_directories(self, tmp_path: Path) -> None:
        """Test that missing directories are created."""
        # Arrange
        result = {
            "outputs": [
                {"type": "image", "data": b"data", "filename": "test.png"}
            ]
        }
        dest_paths = {
            "output_dir": str(tmp_path / "deep" / "nested" / "path")
        }
        
        # Act
        metadata = write_outputs(result, dest_paths)
        
        # Assert
        output_file = Path(metadata["saved"][0])
        assert output_file.exists()
        assert output_file.parent.exists()

    def test_returns_metadata(self, tmp_path: Path) -> None:
        """Test that metadata is returned correctly."""
        # Arrange
        result = {
            "outputs": [
                {"type": "image", "data": b"test_data", "filename": "file1.png"},
                {"type": "image", "data": b"more_data", "filename": "file2.png"}
            ]
        }
        dest_paths = {"output_dir": str(tmp_path)}
        
        # Act
        metadata = write_outputs(result, dest_paths)
        
        # Assert
        assert len(metadata["saved"]) == 2
        assert metadata["bytes"] == len(b"test_data") + len(b"more_data")
        assert metadata["count"] == 2


class TestExecuteJob:
    """Tests for execute_job function."""

    @patch('comfyui_agent.executor.invoke_comfyui')
    @patch('comfyui_agent.executor.write_outputs')
    @patch('comfyui_agent.executor.build_payload')
    def test_successful_job_execution(self, mock_build, mock_write, mock_invoke,
                                     tmp_path: Path) -> None:
        """Test successful end-to-end job execution."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "T2I_20250809120030_1_test.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 50,
            "status": "processing"
        })
        
        # Create a test YAML file
        yaml_path = tmp_path / "processing" / "T2I_20250809120030_1_test.yaml"
        yaml_path.parent.mkdir(parents=True)
        yaml_path.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        job = {
            "id": job_id,
            "config_name": "T2I_20250809120030_1_test.yaml",
            "workflow_id": "wf_test"
        }
        
        cfg = {
            "paths": {
                "jobs_processing": str(tmp_path / "processing"),
                "jobs_finished": str(tmp_path / "finished")
            },
            "comfyui": {
                "api_base_url": "http://127.0.0.1:8188",
                "timeout_seconds": 60
            }
        }
        
        workflows = {
            "wf_test": {
                "template_path": "workflows/test.json",
                "required_inputs": ["prompt"]
            }
        }
        
        mock_build.return_value = {"prompt": {}, "client_id": "test"}
        mock_invoke.return_value = {"status": "completed", "outputs": []}
        mock_write.return_value = {"saved": ["/output/test.png"]}
        
        # Act
        execute_job(job, cfg, workflows, db_path)
        
        # Assert
        mock_build.assert_called_once()
        mock_invoke.assert_called_once()
        mock_write.assert_called_once()
        
        # Check file was moved
        finished_path = Path(cfg["paths"]["jobs_finished"]) / "T2I" / "T2I_20250809120030_1_test.yaml"
        assert finished_path.exists()

    @patch('comfyui_agent.executor.invoke_comfyui')
    def test_failed_job_execution(self, mock_invoke, tmp_path: Path) -> None:
        """Test handling of failed job execution."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job, get_job_by_config_name
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        job_id = upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "status": "processing",
            "retry_limit": 2,
            "retries_attempted": 0
        })
        
        # Create test YAML
        yaml_path = tmp_path / "processing" / "job.yaml"
        yaml_path.parent.mkdir(parents=True)
        yaml_path.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        job = {"id": job_id, "config_name": "job.yaml", "workflow_id": "wf_test"}
        cfg = {
            "paths": {
                "jobs_processing": str(tmp_path / "processing"),
                "jobs_finished": str(tmp_path / "finished")
            },
            "comfyui": {"api_base_url": "http://127.0.0.1:8188", "timeout_seconds": 60}
        }
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        
        mock_invoke.side_effect = RuntimeError("Connection failed")
        
        # Act
        execute_job(job, cfg, workflows, db_path)
        
        # Assert - Job should be back to pending for retry
        updated_job = get_job_by_config_name(db_path, "job.yaml")
        assert updated_job["status"] == "pending"
        assert updated_job["retries_attempted"] == 1
        assert "Connection failed" in updated_job["error_trace"]


class TestRunOnce:
    """Tests for run_once function."""

    def test_processes_pending_job(self, tmp_path: Path) -> None:
        """Test that pending job is processed."""
        # Arrange
        from comfyui_agent.db_manager import init_db, upsert_job
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        upsert_job(db_path, {
            "config_name": "job.yaml",
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "status": "pending"
        })
        
        # Create test YAML
        yaml_path = tmp_path / "processing" / "job.yaml"
        yaml_path.parent.mkdir(parents=True)
        yaml_path.write_text("""
job_type: T2I
workflow_id: wf_test
inputs:
  prompt: test
outputs:
  file_path: /output/test.png
""")
        
        cfg = {
            "paths": {
                "jobs_processing": str(tmp_path / "processing"),
                "jobs_finished": str(tmp_path / "finished")
            },
            "comfyui": {"api_base_url": "http://127.0.0.1:8188", "timeout_seconds": 60}
        }
        workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        
        with patch('comfyui_agent.executor.execute_job'):
            # Act
            result = run_once(cfg, workflows, db_path, "worker1")
            
            # Assert
            assert result is True  # Work was done

    def test_returns_false_when_no_work(self, tmp_path: Path) -> None:
        """Test that False is returned when no jobs available."""
        # Arrange
        from comfyui_agent.db_manager import init_db
        
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        
        cfg = {"paths": {}, "comfyui": {}}
        workflows = {}
        
        # Act
        result = run_once(cfg, workflows, db_path, "worker1")
        
        # Assert
        assert result is False  # No work done


class TestComfyUIClient:
    """Tests for ComfyUIClient class."""

    def test_client_initialization(self) -> None:
        """Test ComfyUIClient initialization."""
        # Act
        client = ComfyUIClient("http://127.0.0.1:8188")
        
        # Assert
        assert client.base_url == "http://127.0.0.1:8188"
        assert client.client_id is not None
        assert len(client.client_id) > 0