"""
File utility functions for ComfyUI Agent.

Provides safe file operations including atomic moves,
directory creation, and YAML file listing.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


def ensure_directories(paths: Dict[str, str]) -> None:
    """Create directories from paths dict if they don't exist.
    
    Idempotent operation - safe to call multiple times.
    Creates parent directories as needed.
    
    Args:
        paths: Dictionary mapping names to directory paths.
        
    Returns:
        None
        
    Examples:
        >>> paths = {"jobs": "/tmp/jobs", "db": "/tmp/database"}
        >>> ensure_directories(paths)
    """
    for path in paths.values():
        os.makedirs(path, exist_ok=True)


def list_yaml_under(root: str, *, media_types: Optional[List[str]] = None) -> List[str]:
    """List all YAML files under root directory.
    
    Recursively finds all .yaml and .yml files. Optionally filters
    by specific subdirectories (media types).
    
    Args:
        root: Root directory to search.
        media_types: Optional list of subdirectory names to filter by
                    (e.g., ["image", "video"]).
        
    Returns:
        List of absolute file paths to YAML files.
        
    Examples:
        >>> files = list_yaml_under("/jobs/processing")
        >>> files = list_yaml_under("/jobs", media_types=["image", "video"])
    """
    if not os.path.exists(root):
        return []
    
    yaml_files = []
    
    # If media_types specified and not empty, only search those subdirs
    if media_types:
        search_dirs = []
        for media_type in media_types:
            subdir = os.path.join(root, media_type)
            if os.path.exists(subdir):
                search_dirs.append(subdir)
    else:
        search_dirs = [root]
    
    # Walk through directories and find YAML files
    for search_dir in search_dirs:
        for dirpath, _, filenames in os.walk(search_dir):
            for filename in filenames:
                if filename.endswith(('.yaml', '.yml')):
                    yaml_files.append(os.path.abspath(os.path.join(dirpath, filename)))
    
    return yaml_files


def safe_move(src: str, dst: str) -> None:
    """Atomically move a file from src to dst.
    
    Uses temporary file and rename for atomicity. Creates destination
    directory if it doesn't exist. Preserves file permissions.
    
    Args:
        src: Source file path.
        dst: Destination file path.
        
    Raises:
        FileNotFoundError: If source file doesn't exist.
        
    Examples:
        >>> safe_move("/tmp/job.yaml", "/jobs/finished/job.yaml")
    """
    if not os.path.exists(src):
        raise FileNotFoundError(f"Source file not found: {src}")
    
    # Ensure destination directory exists
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
    
    # Get source file permissions
    src_stat = os.stat(src)
    
    # Use atomic move with temp file for safety
    # This ensures we don't have partial writes
    try:
        # Try direct rename first (fastest if on same filesystem)
        os.rename(src, dst)
    except OSError:
        # Cross-filesystem move required
        # Create temp file in destination directory for atomicity
        dst_dir = os.path.dirname(dst) or '.'
        with tempfile.NamedTemporaryFile(dir=dst_dir, delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Copy to temp file
            shutil.copy2(src, tmp_path)
            
            # Preserve permissions
            os.chmod(tmp_path, src_stat.st_mode)
            
            # Atomic rename from temp to final destination
            os.rename(tmp_path, dst)
            
            # Remove source after successful move
            os.remove(src)
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise