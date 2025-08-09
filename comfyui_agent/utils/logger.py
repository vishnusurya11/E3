"""
Logging utilities for ComfyUI Agent.

Provides structured logging configuration for the project.
"""

import logging
import sys
from typing import Optional


# Track if logging has been set up to avoid duplicate handlers
_logging_configured = False


def setup_logging(
    level: str = "INFO",
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    date_format: str = "%Y-%m-%d %H:%M:%S"
) -> None:
    """Set up logging configuration for the project.
    
    Configures the root logger with specified level and format.
    Idempotent - safe to call multiple times.
    
    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        format: Log message format string.
        date_format: Date format for timestamps.
        
    Examples:
        >>> setup_logging(level="DEBUG")
        >>> logger = get_logger(__name__)
        >>> logger.debug("Debug message")
    """
    global _logging_configured
    
    # Convert level string to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Get root logger
    root_logger = logging.getLogger()
    
    # Set level
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    if _logging_configured:
        # If already configured, just update the level
        root_logger.setLevel(numeric_level)
        # Update formatter if handlers exist
        for handler in root_logger.handlers:
            formatter = logging.Formatter(format, date_format)
            handler.setFormatter(formatter)
        return
    
    # Clear any existing handlers
    root_logger.handlers = []
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    
    # Create formatter
    formatter = logging.Formatter(format, date_format)
    console_handler.setFormatter(formatter)
    
    # Add handler to root logger
    root_logger.addHandler(console_handler)
    
    # Mark as configured
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the specified module.
    
    Returns a logger configured with the project settings.
    If logging hasn't been set up yet, sets it up with defaults.
    
    Args:
        name: Name of the module/component requesting the logger.
        
    Returns:
        Configured logger instance.
        
    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting processing")
    """
    # Ensure logging is configured
    if not _logging_configured:
        setup_logging()
    
    # Return logger for the specified name
    return logging.getLogger(name)