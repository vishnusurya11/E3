"""
Tests for validation utilities module.
Following TDD principles - tests written before implementation.
"""

import pytest
from typing import Dict, Any

# Import the module we're going to implement
from comfyui_agent.utils.validation import (
    parse_config_name,
    validate_config_schema,
    normalize_config
)


class TestParseConfigName:
    """Tests for parse_config_name function."""

    def test_parse_valid_config_name(self) -> None:
        """Test parsing a valid config filename."""
        # Arrange
        filename = "T2I_20250809120030_1_portrait.yaml"
        
        # Act
        result = parse_config_name(filename)
        
        # Assert
        assert result["job_type"] == "T2I"
        assert result["timestamp"] == "20250809120030"
        assert result["index"] == 1
        assert result["jobname"] == "portrait"

    def test_parse_with_full_path(self) -> None:
        """Test parsing with full path (should extract basename)."""
        # Arrange
        filename = "/jobs/processing/image/T2V_20250809143045_5_animation.yaml"
        
        # Act
        result = parse_config_name(filename)
        
        # Assert
        assert result["job_type"] == "T2V"
        assert result["timestamp"] == "20250809143045"
        assert result["index"] == 5
        assert result["jobname"] == "animation"

    def test_parse_with_underscore_in_jobname(self) -> None:
        """Test parsing jobname that contains underscores."""
        # Arrange
        filename = "AUDIO_20250809100000_2_background_music_v2.yaml"
        
        # Act
        result = parse_config_name(filename)
        
        # Assert
        assert result["job_type"] == "AUDIO"
        assert result["timestamp"] == "20250809100000"
        assert result["index"] == 2
        assert result["jobname"] == "background_music_v2"

    def test_invalid_job_type_raises_error(self) -> None:
        """Test that invalid job type raises ValueError."""
        # Arrange
        filename = "INVALID_20250809120030_1_test.yaml"
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid job type"):
            parse_config_name(filename)

    def test_malformed_timestamp_raises_error(self) -> None:
        """Test that malformed timestamp raises ValueError."""
        # Arrange
        filename = "T2I_2025080_1_test.yaml"  # Too short
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid timestamp"):
            parse_config_name(filename)

    def test_non_integer_index_raises_error(self) -> None:
        """Test that non-integer index raises ValueError."""
        # Arrange
        filename = "T2I_20250809120030_abc_test.yaml"
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid index"):
            parse_config_name(filename)

    def test_missing_parts_raises_error(self) -> None:
        """Test that missing parts raises ValueError."""
        # Arrange
        filename = "T2I_20250809120030.yaml"  # Missing index and jobname
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid config name format"):
            parse_config_name(filename)

    def test_non_yaml_extension_raises_error(self) -> None:
        """Test that non-yaml extension raises ValueError."""
        # Arrange
        filename = "T2I_20250809120030_1_test.txt"
        
        # Act & Assert
        with pytest.raises(ValueError, match="must have .yaml extension"):
            parse_config_name(filename)


class TestValidateConfigSchema:
    """Tests for validate_config_schema function."""

    def test_valid_config_passes_validation(self) -> None:
        """Test that a valid config passes validation."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_realistic_portrait",
            "priority": 30,
            "inputs": {
                "prompt": "test prompt",
                "seed": 12345,
                "steps": 30
            },
            "outputs": {
                "file_path": "/jobs/finished/image/test.png"
            }
        }
        workflows = {
            "wf_realistic_portrait": {
                "template_path": "workflows/portrait.json",
                "required_inputs": ["prompt", "seed", "steps"]
            }
        }
        
        # Act & Assert - should not raise
        validate_config_schema(config, workflows)

    def test_missing_job_type_raises_error(self) -> None:
        """Test that missing job_type raises ValueError."""
        # Arrange
        config = {
            "workflow_id": "wf_test",
            "inputs": {},
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {"wf_test": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Missing required field: job_type"):
            validate_config_schema(config, workflows)

    def test_missing_workflow_id_raises_error(self) -> None:
        """Test that missing workflow_id raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "inputs": {},
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Missing required field: workflow_id"):
            validate_config_schema(config, workflows)

    def test_unknown_workflow_id_raises_error(self) -> None:
        """Test that unknown workflow_id raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_unknown",
            "inputs": {},
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {"wf_other": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Unknown workflow_id"):
            validate_config_schema(config, workflows)

    def test_missing_required_inputs_raises_error(self) -> None:
        """Test that missing required inputs raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "inputs": {
                "prompt": "test"
                # Missing "seed" and "steps"
            },
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {
            "wf_test": {
                "required_inputs": ["prompt", "seed", "steps"]
            }
        }
        
        # Act & Assert
        with pytest.raises(ValueError, match="Missing required inputs"):
            validate_config_schema(config, workflows)

    def test_missing_outputs_file_path_raises_error(self) -> None:
        """Test that missing outputs.file_path raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "inputs": {},
            "outputs": {}  # Missing file_path
        }
        workflows = {"wf_test": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Missing outputs.file_path"):
            validate_config_schema(config, workflows)

    def test_invalid_priority_raises_error(self) -> None:
        """Test that invalid priority raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 1000,  # Too high
            "inputs": {},
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {"wf_test": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Priority must be between 1 and 999"):
            validate_config_schema(config, workflows)

    def test_negative_priority_raises_error(self) -> None:
        """Test that negative priority raises ValueError."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": -1,
            "inputs": {},
            "outputs": {"file_path": "/test.png"}
        }
        workflows = {"wf_test": {"required_inputs": []}}
        
        # Act & Assert
        with pytest.raises(ValueError, match="Priority must be between 1 and 999"):
            validate_config_schema(config, workflows)


class TestNormalizeConfig:
    """Tests for normalize_config function."""

    def test_applies_default_priority(self) -> None:
        """Test that default priority is applied when missing."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test"
        }
        defaults = {
            "default_priority": 50,
            "retry_limit": 2
        }
        
        # Act
        result = normalize_config(config, defaults)
        
        # Assert
        assert result["priority"] == 50

    def test_preserves_provided_priority(self) -> None:
        """Test that provided priority is preserved."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "priority": 10
        }
        defaults = {
            "default_priority": 50,
            "retry_limit": 2
        }
        
        # Act
        result = normalize_config(config, defaults)
        
        # Assert
        assert result["priority"] == 10

    def test_applies_default_retry_limit(self) -> None:
        """Test that default retry_limit is applied when missing."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test"
        }
        defaults = {
            "default_priority": 50,
            "retry_limit": 3
        }
        
        # Act
        result = normalize_config(config, defaults)
        
        # Assert
        assert result["retry_limit"] == 3

    def test_clamps_priority_to_valid_range(self) -> None:
        """Test that priority is clamped to valid range."""
        # Arrange
        config1 = {"priority": 0}
        config2 = {"priority": 1000}
        defaults = {"default_priority": 50}
        
        # Act
        result1 = normalize_config(config1, defaults)
        result2 = normalize_config(config2, defaults)
        
        # Assert
        assert result1["priority"] == 1  # Clamped to minimum
        assert result2["priority"] == 999  # Clamped to maximum

    def test_preserves_existing_fields(self) -> None:
        """Test that existing fields are preserved during normalization."""
        # Arrange
        config = {
            "job_type": "T2I",
            "workflow_id": "wf_test",
            "custom_field": "custom_value",
            "metadata": {"key": "value"}
        }
        defaults = {"default_priority": 50}
        
        # Act
        result = normalize_config(config, defaults)
        
        # Assert
        assert result["custom_field"] == "custom_value"
        assert result["metadata"] == {"key": "value"}

    def test_returns_new_dict_not_modifying_original(self) -> None:
        """Test that original config is not modified."""
        # Arrange
        config = {"job_type": "T2I"}
        defaults = {"default_priority": 50}
        
        # Act
        result = normalize_config(config, defaults)
        
        # Assert
        assert "priority" in result
        assert "priority" not in config  # Original unchanged