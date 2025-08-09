"""
Configuration loader module for ComfyUI Agent.

Handles loading and validation of YAML configuration files
with proper defaults and error handling.
"""

import os
from pathlib import Path
from typing import Dict, Any
import yaml


def load_global_config(path: str) -> Dict[str, Any]:
    """Load and validate global configuration from YAML file.
    
    Loads the global configuration file, validates required fields,
    and applies default values for optional fields.
    
    Args:
        path: Path to the global configuration YAML file.
        
    Returns:
        Dictionary containing validated configuration with defaults applied.
        
    Raises:
        ValueError: If file not found, invalid YAML, or missing critical keys.
        
    Examples:
        >>> config = load_global_config("config/global_config.yaml")
        >>> print(config["default_priority"])
        50
    """
    # Check if file exists
    if not os.path.exists(path):
        raise ValueError(f"Config file not found: {path}")
    
    # Load YAML file
    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}")
    
    # Define defaults
    defaults = {
        "default_priority": 50,
        "retry_limit": 2,
        "poll_interval_ms": 1000,
        "paths": {},
        "comfyui": {}
    }
    
    # Check for critical keys
    if "paths" not in config:
        raise ValueError("Missing critical key: paths")
    if "comfyui" not in config:
        raise ValueError("Missing critical key: comfyui")
    
    # Check for required path keys
    required_path_keys = ["jobs_processing", "jobs_finished", "database"]
    for key in required_path_keys:
        if key not in config["paths"]:
            raise ValueError(f"Missing critical path key: {key}")
    
    # Check for required comfyui keys
    if "api_base_url" not in config["comfyui"]:
        raise ValueError("Missing critical comfyui key: api_base_url")
    
    # Apply defaults for optional fields
    result = defaults.copy()
    result.update(config)
    
    # Apply defaults for nested comfyui fields
    if "timeout_seconds" not in result["comfyui"]:
        result["comfyui"]["timeout_seconds"] = 300
    
    return result


def load_workflows(path: str) -> Dict[str, Dict[str, Any]]:
    """Load and validate workflows configuration from YAML file.
    
    Loads workflow definitions including template paths and required inputs.
    Each workflow must have a template_path and required_inputs list.
    
    Args:
        path: Path to the workflows YAML file.
        
    Returns:
        Dictionary keyed by workflow_id with template_path and required_inputs.
        
    Raises:
        ValueError: If file not found, invalid YAML, or invalid workflow entry.
        
    Examples:
        >>> workflows = load_workflows("config/workflows.yaml")
        >>> print(workflows["wf_realistic_portrait"]["template_path"])
        workflows/wf_realistic_portrait.json
    """
    # Check if file exists
    if not os.path.exists(path):
        raise ValueError(f"Workflows file not found: {path}")
    
    # Load YAML file
    try:
        with open(path, 'r') as f:
            workflows = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in workflows file: {e}")
    
    # Validate each workflow entry
    for workflow_id, workflow_data in workflows.items():
        if not isinstance(workflow_data, dict):
            raise ValueError(f"Workflow {workflow_id} must be a dictionary")
        
        if "template_path" not in workflow_data:
            raise ValueError(f"Workflow {workflow_id} missing template_path")
        
        if "required_inputs" not in workflow_data:
            raise ValueError(f"Workflow {workflow_id} missing required_inputs")
        
        if not isinstance(workflow_data["required_inputs"], list):
            raise ValueError(f"Workflow {workflow_id} required_inputs must be a list")
    
    return workflows