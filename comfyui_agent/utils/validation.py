"""
Validation utilities for ComfyUI Agent.

Handles parsing and validation of YAML config files,
ensuring they meet the required schema.
"""

import os
import re
from typing import Dict, Any, List
from copy import deepcopy


# Valid job types as per PRD
VALID_JOB_TYPES = {"T2I", "T2V", "SPEECH", "AUDIO", "3D"}


def parse_config_name(filename: str) -> Dict[str, Any]:
    """Parse and validate config filename format.
    
    Expected format: TYPE_IDENTIFIER_X_jobname.yaml
    where:
    - TYPE is one of the valid job types
    - IDENTIFIER is either a 14-digit timestamp (YYYYMMDDHHMMSS) or alphanumeric string
    - X is an integer index
    
    Args:
        filename: Config filename (with or without path).
        
    Returns:
        Dictionary with parsed components:
        - job_type: The job type (T2I, T2V, etc.)
        - timestamp: Timestamp string (YYYYMMDDHHMMSS) or identifier (alphanumeric)
        - index: Integer index
        - jobname: Job name string
        
    Raises:
        ValueError: If filename doesn't match expected format.
        
    Examples:
        >>> result = parse_config_name("T2I_20250809120030_1_portrait.yaml")
        >>> print(result["job_type"])
        T2I
    """
    # Extract basename if full path provided
    basename = os.path.basename(filename)
    
    # Check extension
    if not basename.endswith(".yaml"):
        raise ValueError(f"Config file must have .yaml extension: {basename}")
    
    # Remove extension
    name_without_ext = basename[:-5]
    
    # Parse using regex - be more specific about errors
    # First check basic structure
    parts = name_without_ext.split("_")
    if len(parts) < 4:
        raise ValueError(f"Invalid config name format: {basename}")
    
    job_type = parts[0]
    timestamp_str = parts[1]
    index_str = parts[2]
    jobname = "_".join(parts[3:])  # Jobname can contain underscores
    
    # Validate job type
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"Invalid job type: {job_type}. Must be one of {VALID_JOB_TYPES}")
    
    # Validate timestamp OR identifier format
    # Accept either 14-digit timestamp or alphanumeric identifier
    if not (len(timestamp_str) == 14 and timestamp_str.isdigit()):
        # Also accept alphanumeric identifiers (e.g., pg159, book123, etc.)
        if not re.match(r'^[a-zA-Z0-9]+$', timestamp_str):
            raise ValueError(f"Invalid timestamp/identifier: {timestamp_str}")
    
    # Parse index
    try:
        index = int(index_str)
    except ValueError:
        raise ValueError(f"Invalid index: {index_str}")
    
    return {
        "job_type": job_type,
        "timestamp": timestamp_str,
        "index": index,
        "jobname": jobname
    }


def validate_config_schema(cfg: Dict[str, Any], workflows: Dict[str, Any]) -> None:
    """Validate config against required schema.
    
    Ensures all required fields exist and have valid values.
    Checks workflow_id exists and required inputs are present.
    
    Args:
        cfg: Config dictionary to validate.
        workflows: Available workflows mapping.
        
    Raises:
        ValueError: If validation fails.
        
    Examples:
        >>> config = {"job_type": "T2I", "workflow_id": "wf_test", ...}
        >>> workflows = {"wf_test": {"required_inputs": ["prompt"]}}
        >>> validate_config_schema(config, workflows)
    """
    # Check required top-level fields
    required_fields = ["job_type", "workflow_id", "inputs", "outputs"]
    for field in required_fields:
        if field not in cfg:
            raise ValueError(f"Missing required field: {field}")
    
    # Validate job type
    if cfg["job_type"] not in VALID_JOB_TYPES:
        raise ValueError(f"Invalid job_type: {cfg['job_type']}")
    
    # Validate workflow_id exists
    workflow_id = cfg["workflow_id"]
    if workflow_id not in workflows:
        raise ValueError(f"Unknown workflow_id: {workflow_id}")
    
    # Check required inputs for workflow
    if "required_inputs" in workflows[workflow_id]:
        required_inputs = workflows[workflow_id]["required_inputs"]
        provided_inputs = cfg.get("inputs", {})
        
        # Check for both generic and node-specific inputs
        missing_inputs = []
        for inp in required_inputs:
            # First check if generic input exists
            if inp not in provided_inputs:
                # Check if any node-specific version exists
                node_specific_found = False
                
                # Special case: "prompt" can be satisfied by "_text" fields
                if inp == "prompt":
                    node_specific_found = any(
                        "_text" in key for key in provided_inputs.keys()
                    )
                
                # General case: check for node-specific version (e.g., "31_seed" for "seed")
                if not node_specific_found:
                    node_specific_found = any(
                        key.endswith(f"_{inp}") for key in provided_inputs.keys()
                    )
                
                if not node_specific_found:
                    missing_inputs.append(inp)
        
        if missing_inputs:
            raise ValueError(f"Missing required inputs: {missing_inputs}")
    
    # Validate outputs has file_path
    if "outputs" not in cfg or "file_path" not in cfg.get("outputs", {}):
        raise ValueError("Missing outputs.file_path")
    
    # Validate priority if present
    if "priority" in cfg:
        priority = cfg["priority"]
        if not isinstance(priority, int) or priority < 1 or priority > 999:
            raise ValueError(f"Priority must be between 1 and 999, got: {priority}")


def normalize_config(cfg: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Apply default values and normalize config.
    
    Fills in missing optional fields with defaults and ensures
    values are within valid ranges.
    
    Args:
        cfg: Config dictionary to normalize.
        defaults: Default values from global config.
        
    Returns:
        New normalized config dictionary (original unchanged).
        
    Examples:
        >>> config = {"job_type": "T2I"}
        >>> defaults = {"default_priority": 50, "retry_limit": 2}
        >>> normalized = normalize_config(config, defaults)
        >>> print(normalized["priority"])
        50
    """
    # Create a deep copy to avoid modifying original
    result = deepcopy(cfg)
    
    # Apply default priority if missing
    if "priority" not in result:
        result["priority"] = defaults.get("default_priority", 50)
    
    # Clamp priority to valid range
    if "priority" in result:
        priority = result["priority"]
        result["priority"] = max(1, min(999, priority))
    
    # Apply default retry_limit if missing
    if "retry_limit" not in result:
        result["retry_limit"] = defaults.get("retry_limit", 2)
    
    return result