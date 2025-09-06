"""
Tests for configuration loader module.
Following TDD principles - tests written before implementation.
"""

import pytest
import tempfile
import os
from pathlib import Path
from typing import Dict, Any
import yaml


# Import the module we're going to implement
# This will fail initially (TDD step 1)
from comfyui_agent.utils.config_loader import load_global_config, load_workflows


class TestLoadGlobalConfig:
    """Tests for load_global_config function."""

    def test_load_valid_yaml_with_all_fields(self, tmp_path: Path) -> None:
        """Test loading a valid YAML file with all expected fields."""
        # Arrange
        config_file = tmp_path / "config.yaml"
        config_data = {
            "default_priority": 30,
            "retry_limit": 3,
            "poll_interval_ms": 2000,
            "paths": {
                "jobs_processing": "custom/processing",
                "jobs_finished": "custom/finished",
                "database": "custom/db.sqlite"
            },
            "comfyui": {
                "api_base_url": "http://192.168.1.100:8188",
                "timeout_seconds": 600
            }
        }
        config_file.write_text(yaml.dump(config_data))

        # Act
        result = load_global_config(str(config_file))

        # Assert
        assert result["default_priority"] == 30
        assert result["retry_limit"] == 3
        assert result["poll_interval_ms"] == 2000
        assert result["paths"]["jobs_processing"] == "custom/processing"
        assert result["paths"]["jobs_finished"] == "custom/finished"
        assert result["paths"]["database"] == "custom/db.sqlite"
        assert result["comfyui"]["api_base_url"] == "http://192.168.1.100:8188"
        assert result["comfyui"]["timeout_seconds"] == 600

    def test_load_yaml_with_missing_optional_fields_applies_defaults(self, tmp_path: Path) -> None:
        """Test that missing optional fields get default values."""
        # Arrange
        config_file = tmp_path / "config.yaml"
        config_data = {
            "paths": {
                "jobs_processing": "jobs/processing",
                "jobs_finished": "jobs/finished",
                "database": "database/comfyui_agent.db"
            },
            "comfyui": {
                "api_base_url": "http://127.0.0.1:8188"
            }
        }
        config_file.write_text(yaml.dump(config_data))

        # Act
        result = load_global_config(str(config_file))

        # Assert - defaults should be applied
        assert result["default_priority"] == 50  # default
        assert result["retry_limit"] == 2  # default
        assert result["poll_interval_ms"] == 1000  # default
        assert result["comfyui"]["timeout_seconds"] == 300  # default

    def test_load_invalid_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """Test that invalid YAML syntax raises ValueError."""
        # Arrange
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_global_config(str(config_file))

    def test_missing_critical_paths_raises_value_error(self, tmp_path: Path) -> None:
        """Test that missing critical 'paths' section raises ValueError."""
        # Arrange
        config_file = tmp_path / "config.yaml"
        config_data = {
            "comfyui": {
                "api_base_url": "http://127.0.0.1:8188"
            }
        }
        config_file.write_text(yaml.dump(config_data))

        # Act & Assert
        with pytest.raises(ValueError, match="Missing critical key: paths"):
            load_global_config(str(config_file))

    def test_missing_critical_comfyui_raises_value_error(self, tmp_path: Path) -> None:
        """Test that missing critical 'comfyui' section raises ValueError."""
        # Arrange
        config_file = tmp_path / "config.yaml"
        config_data = {
            "paths": {
                "jobs_processing": "jobs/processing",
                "jobs_finished": "jobs/finished",
                "database": "database/comfyui_agent.db"
            }
        }
        config_file.write_text(yaml.dump(config_data))

        # Act & Assert
        with pytest.raises(ValueError, match="Missing critical key: comfyui"):
            load_global_config(str(config_file))

    def test_nonexistent_file_raises_value_error(self) -> None:
        """Test that a nonexistent file raises ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="Config file not found"):
            load_global_config("/nonexistent/path/config.yaml")


class TestLoadWorkflows:
    """Tests for load_workflows function."""

    def test_load_valid_workflows_yaml(self, tmp_path: Path) -> None:
        """Test loading a valid workflows YAML file."""
        # Arrange
        workflows_file = tmp_path / "workflows.yaml"
        workflows_data = {
            "wf_realistic_portrait": {
                "template_path": "workflows/wf_realistic_portrait.json",
                "required_inputs": ["prompt", "seed", "steps"]
            },
            "wf_t2v_cinematic": {
                "template_path": "workflows/wf_t2v_cinematic.json",
                "required_inputs": ["prompt", "seed"]
            }
        }
        workflows_file.write_text(yaml.dump(workflows_data))

        # Act
        result = load_workflows(str(workflows_file))

        # Assert
        assert "wf_realistic_portrait" in result
        assert result["wf_realistic_portrait"]["template_path"] == "workflows/wf_realistic_portrait.json"
        assert result["wf_realistic_portrait"]["required_inputs"] == ["prompt", "seed", "steps"]
        assert "wf_t2v_cinematic" in result
        assert result["wf_t2v_cinematic"]["template_path"] == "workflows/wf_t2v_cinematic.json"
        assert result["wf_t2v_cinematic"]["required_inputs"] == ["prompt", "seed"]

    def test_workflow_missing_template_path_raises_value_error(self, tmp_path: Path) -> None:
        """Test that a workflow entry missing template_path raises ValueError."""
        # Arrange
        workflows_file = tmp_path / "workflows.yaml"
        workflows_data = {
            "wf_invalid": {
                "required_inputs": ["prompt"]
            }
        }
        workflows_file.write_text(yaml.dump(workflows_data))

        # Act & Assert
        with pytest.raises(ValueError, match="missing template_path"):
            load_workflows(str(workflows_file))

    def test_workflow_missing_required_inputs_raises_value_error(self, tmp_path: Path) -> None:
        """Test that a workflow entry missing required_inputs raises ValueError."""
        # Arrange
        workflows_file = tmp_path / "workflows.yaml"
        workflows_data = {
            "wf_invalid": {
                "template_path": "workflows/test.json"
            }
        }
        workflows_file.write_text(yaml.dump(workflows_data))

        # Act & Assert
        with pytest.raises(ValueError, match="missing required_inputs"):
            load_workflows(str(workflows_file))

    def test_empty_workflows_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        """Test that an empty workflows YAML returns an empty dictionary."""
        # Arrange
        workflows_file = tmp_path / "workflows.yaml"
        workflows_file.write_text("")

        # Act
        result = load_workflows(str(workflows_file))

        # Assert
        assert result == {}

    def test_invalid_yaml_syntax_raises_value_error(self, tmp_path: Path) -> None:
        """Test that invalid YAML syntax raises ValueError."""
        # Arrange
        workflows_file = tmp_path / "workflows.yaml"
        workflows_file.write_text("invalid: yaml: [unclosed")

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_workflows(str(workflows_file))

    def test_nonexistent_file_raises_value_error(self) -> None:
        """Test that a nonexistent file raises ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="Workflows file not found"):
            load_workflows("/nonexistent/workflows.yaml")