"""
Configuration loader module for ComfyUI Agent.

Handles loading and validation of YAML configuration files
with proper defaults and error handling.
"""

import os
from pathlib import Path
from typing import Dict, Any
import yaml


def load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


def load_global_config(path: str = None) -> Dict[str, Any]:
    """Load and validate global configuration with environment support.
    
    Automatically loads .env file and uses E3_ENV variable to determine which 
    config file to load from root-level config directory.
    
    Args:
        path: Legacy parameter for backward compatibility. If None, uses new config structure.
        
    Returns:
        Dictionary containing validated configuration with environment variable interpolation.
        
    Raises:
        ValueError: If config file not found, invalid YAML, or missing critical keys.
        
    Examples:
        >>> config = load_global_config()  # Auto-loads .env, then uses E3_ENV
        >>> print(config["comfyui"]["default_priority"])
        50
        
        # With E3_ENV=alpha in .env file, loads config/global_alpha.yaml
        >>> config = load_global_config()
        >>> print(config["databases"]["comfyui"])  # alpha_comfyui_agent.db
    """
    # Load .env file first to get E3_ENV
    load_env_file()
    
    # Get environment
    env = os.getenv('E3_ENV')
    if not env:
        raise ValueError("E3_ENV environment variable not set. Please set E3_ENV=alpha or E3_ENV=prod in .env file")
    
    # Use new config structure
    config_path = f"config/global_{env}.yaml"
    
    # Check if config file exists
    if not os.path.exists(config_path):
        raise ValueError(f"Config file not found: {config_path}. Available environments: alpha, prod")
    
    # Load environment-specific YAML file
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        raise ValueError(f"Invalid YAML in config file {config_path}: {e}")
    
    # Apply environment variable interpolation
    config = _interpolate_env_vars(config)
    
    # Validate and transform config for backward compatibility
    validated_config = _validate_and_transform_config(config, env)
    
    return validated_config


def _interpolate_env_vars(obj):
    """Recursively interpolate environment variables in config values.
    
    Replaces ${VAR} or ${VAR:-default} with environment variable values.
    """
    if isinstance(obj, dict):
        return {key: _interpolate_env_vars(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_interpolate_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        # Handle ${VAR} and ${VAR:-default} syntax
        import re
        def replace_var(match):
            var_expr = match.group(1)
            if ':-' in var_expr:
                var_name, default_value = var_expr.split(':-', 1)
                return os.getenv(var_name, default_value)
            else:
                return os.getenv(var_expr, match.group(0))  # Return original if not found
        
        return re.sub(r'\$\{([^}]+)\}', replace_var, obj)
    else:
        return obj


def _validate_and_transform_config(config: Dict[str, Any], env: str) -> Dict[str, Any]:
    """Validate new config structure and transform for backward compatibility.
    
    Args:
        config: Raw config dictionary from YAML file.
        env: Environment name.
        
    Returns:
        Validated config with backward-compatible structure.
    """
    # Create backward-compatible structure
    result = {
        "default_priority": config["comfyui"].get("default_priority", 50),
        "retry_limit": config["comfyui"].get("retry_limit", 2), 
        "poll_interval_ms": config["comfyui"].get("poll_interval_ms", 1000),
        "paths": {
            "jobs_processing": config["paths"]["jobs_processing"],
            "jobs_finished": config["paths"]["jobs_finished"],
            "database": config["databases"]["main"]  # Map databases.main -> paths.database
        },
        "comfyui": {
            "api_base_url": config["comfyui"]["api_base_url"],
            "timeout_seconds": config["comfyui"].get("timeout_seconds", 300)
        }
    }
    
    # Validate required keys exist
    required_sections = ["databases", "paths", "comfyui"]
    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required section: {section}")
    
    # Validate required database paths
    required_db_keys = ["main"]
    for key in required_db_keys:
        if key not in config["databases"]:
            raise ValueError(f"Missing required database key: {key}")
    
    # Validate required path keys
    required_path_keys = ["jobs_processing", "jobs_finished"]
    for key in required_path_keys:
        if key not in config["paths"]:
            raise ValueError(f"Missing required path key: {key}")
    
    # Validate required comfyui keys
    if "api_base_url" not in config["comfyui"]:
        raise ValueError("Missing required comfyui key: api_base_url")
    
    # Store full config for future use
    result["_full_config"] = config
    
    return result


# Old helper functions removed - using new config structure


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
        with open(path, 'r', encoding='utf-8') as f:
            workflows = yaml.safe_load(f) or {}
    except Exception as e:
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