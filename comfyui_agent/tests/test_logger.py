"""
Tests for logger module.
Following TDD principles - tests written before implementation.
"""

import pytest
import logging
from typing import Any

# Import the module we're going to implement
from comfyui_agent.utils.logger import get_logger, setup_logging


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_with_correct_name(self) -> None:
        """Test that logger has the requested name."""
        # Act
        logger = get_logger("test_module")
        
        # Assert
        assert logger.name == "test_module"
        assert isinstance(logger, logging.Logger)

    def test_returns_same_logger_for_same_name(self) -> None:
        """Test that same logger instance is returned for same name."""
        # Act
        logger1 = get_logger("same_name")
        logger2 = get_logger("same_name")
        
        # Assert
        assert logger1 is logger2

    def test_different_loggers_for_different_names(self) -> None:
        """Test that different loggers are created for different names."""
        # Act
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        # Assert
        assert logger1 is not logger2
        assert logger1.name == "module1"
        assert logger2.name == "module2"

    def test_logger_has_handlers(self) -> None:
        """Test that logger has at least one handler configured."""
        # Arrange
        setup_logging()  # Ensure logging is setup
        
        # Act
        logger = get_logger("test_with_handlers")
        
        # Assert
        # Check either the logger or its parent has handlers
        has_handlers = len(logger.handlers) > 0 or (
            logger.parent and len(logger.parent.handlers) > 0
        )
        assert has_handlers


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_configures_root_logger(self) -> None:
        """Test that setup configures the root logger."""
        # Act
        setup_logging(level="DEBUG")
        
        # Assert
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_setup_with_different_levels(self) -> None:
        """Test setup with different log levels."""
        # Act & Assert
        setup_logging(level="INFO")
        assert logging.getLogger().level == logging.INFO
        
        setup_logging(level="WARNING")
        assert logging.getLogger().level == logging.WARNING
        
        setup_logging(level="ERROR")
        assert logging.getLogger().level == logging.ERROR

    def test_setup_idempotent_no_duplicate_handlers(self) -> None:
        """Test that multiple setups don't create duplicate handlers."""
        # Arrange
        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)
        
        # Act - Call setup multiple times
        setup_logging()
        setup_logging()
        setup_logging()
        
        # Assert - Handler count should not grow
        final_handler_count = len(root_logger.handlers)
        assert final_handler_count <= initial_handler_count + 1

    def test_setup_with_format_string(self) -> None:
        """Test that custom format string is applied."""
        # Act
        setup_logging(
            format="%(levelname)s - %(message)s"
        )
        
        # Assert - Check that handlers have the format
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0
        handler = root_logger.handlers[0]
        if handler.formatter:
            # Format string should be set
            assert handler.formatter._fmt == "%(levelname)s - %(message)s"

    def test_logger_output_format(self, caplog) -> None:
        """Test that logger produces expected output format."""
        # Arrange
        setup_logging(level="INFO")
        logger = get_logger("test_output")
        
        # Act
        with caplog.at_level(logging.INFO):
            logger.info("Test message")
        
        # Assert
        assert "Test message" in caplog.text
        assert "INFO" in caplog.text or "info" in caplog.text.lower()