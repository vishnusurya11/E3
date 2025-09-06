"""
Tests for file utilities module.
Following TDD principles - tests written before implementation.
"""

import pytest
import tempfile
import os
import shutil
from pathlib import Path
from typing import List
import yaml

# Import the module we're going to implement
from comfyui_agent.utils.file_utils import (
    ensure_directories,
    list_yaml_under,
    safe_move
)


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_missing_directories(self, tmp_path: Path) -> None:
        """Test that missing directories are created."""
        # Arrange
        paths = {
            "jobs_processing": str(tmp_path / "jobs" / "processing"),
            "jobs_finished": str(tmp_path / "jobs" / "finished"),
            "database": str(tmp_path / "database")
        }
        
        # Act
        ensure_directories(paths)
        
        # Assert
        assert os.path.exists(paths["jobs_processing"])
        assert os.path.exists(paths["jobs_finished"])
        assert os.path.exists(paths["database"])

    def test_idempotent_when_directories_exist(self, tmp_path: Path) -> None:
        """Test that existing directories are not affected."""
        # Arrange
        paths = {
            "test_dir": str(tmp_path / "existing")
        }
        os.makedirs(paths["test_dir"])
        test_file = Path(paths["test_dir"]) / "test.txt"
        test_file.write_text("content")
        
        # Act
        ensure_directories(paths)  # Should not raise or delete content
        
        # Assert
        assert os.path.exists(paths["test_dir"])
        assert test_file.read_text() == "content"

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        """Test creation of deeply nested directory structures."""
        # Arrange
        paths = {
            "deep": str(tmp_path / "a" / "b" / "c" / "d" / "e")
        }
        
        # Act
        ensure_directories(paths)
        
        # Assert
        assert os.path.exists(paths["deep"])

    def test_handles_empty_dict(self) -> None:
        """Test that empty dict is handled gracefully."""
        # Act & Assert - should not raise
        ensure_directories({})


class TestListYamlUnder:
    """Tests for list_yaml_under function."""

    def test_lists_yaml_files_in_directory(self, tmp_path: Path) -> None:
        """Test listing YAML files in a directory."""
        # Arrange
        (tmp_path / "file1.yaml").write_text("test: 1")
        (tmp_path / "file2.yml").write_text("test: 2")
        (tmp_path / "file3.txt").write_text("not yaml")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file4.yaml").write_text("test: 4")
        
        # Act
        result = list_yaml_under(str(tmp_path))
        
        # Assert
        result_names = [os.path.basename(p) for p in result]
        assert "file1.yaml" in result_names
        assert "file2.yml" in result_names
        assert "file3.txt" not in result_names
        assert "file4.yaml" in result_names
        assert all(os.path.isabs(p) for p in result)  # All paths absolute

    def test_filters_by_media_types(self, tmp_path: Path) -> None:
        """Test filtering by specific subdirectories."""
        # Arrange
        (tmp_path / "image").mkdir()
        (tmp_path / "video").mkdir()
        (tmp_path / "audio").mkdir()
        (tmp_path / "image" / "img.yaml").write_text("type: image")
        (tmp_path / "video" / "vid.yaml").write_text("type: video")
        (tmp_path / "audio" / "aud.yaml").write_text("type: audio")
        
        # Act
        result = list_yaml_under(str(tmp_path), media_types=["image", "video"])
        
        # Assert
        result_names = [os.path.basename(p) for p in result]
        assert "img.yaml" in result_names
        assert "vid.yaml" in result_names
        assert "aud.yaml" not in result_names

    def test_returns_empty_list_for_no_yaml_files(self, tmp_path: Path) -> None:
        """Test that empty list is returned when no YAML files exist."""
        # Arrange
        (tmp_path / "file.txt").write_text("not yaml")
        (tmp_path / "file.json").write_text("{}")
        
        # Act
        result = list_yaml_under(str(tmp_path))
        
        # Assert
        assert result == []

    def test_handles_nonexistent_directory(self) -> None:
        """Test handling of non-existent directory."""
        # Act
        result = list_yaml_under("/nonexistent/directory")
        
        # Assert
        assert result == []

    def test_handles_empty_media_types(self, tmp_path: Path) -> None:
        """Test that empty media_types list returns all YAML files."""
        # Arrange
        (tmp_path / "file.yaml").write_text("test: 1")
        
        # Act
        result = list_yaml_under(str(tmp_path), media_types=[])
        
        # Assert
        assert len(result) == 1


class TestSafeMove:
    """Tests for safe_move function."""

    def test_moves_file_successfully(self, tmp_path: Path) -> None:
        """Test moving a file to a new location."""
        # Arrange
        src = tmp_path / "source.txt"
        dst = tmp_path / "destination.txt"
        src.write_text("content")
        
        # Act
        safe_move(str(src), str(dst))
        
        # Assert
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "content"

    def test_creates_destination_directory_if_missing(self, tmp_path: Path) -> None:
        """Test that destination directory is created if it doesn't exist."""
        # Arrange
        src = tmp_path / "source.txt"
        dst = tmp_path / "new_dir" / "destination.txt"
        src.write_text("content")
        
        # Act
        safe_move(str(src), str(dst))
        
        # Assert
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "content"

    def test_atomic_move_using_temp_file(self, tmp_path: Path) -> None:
        """Test that move is atomic using temporary file."""
        # Arrange
        src = tmp_path / "source.txt"
        dst_dir = tmp_path / "dest_dir"
        dst = dst_dir / "destination.txt"
        dst_dir.mkdir()
        src.write_text("new content")
        
        # Create an existing destination file
        dst.write_text("old content")
        
        # Act
        safe_move(str(src), str(dst))
        
        # Assert
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "new content"  # Should be overwritten

    def test_handles_cross_filesystem_move(self, tmp_path: Path) -> None:
        """Test moving across different directories (simulating cross-filesystem)."""
        # Arrange
        src_dir = tmp_path / "src_mount"
        dst_dir = tmp_path / "dst_mount"
        src_dir.mkdir()
        dst_dir.mkdir()
        
        src = src_dir / "file.txt"
        dst = dst_dir / "file.txt"
        src.write_text("cross-fs content")
        
        # Act
        safe_move(str(src), str(dst))
        
        # Assert
        assert not src.exists()
        assert dst.exists()
        assert dst.read_text() == "cross-fs content"

    def test_raises_on_nonexistent_source(self, tmp_path: Path) -> None:
        """Test that moving non-existent source raises error."""
        # Arrange
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "destination.txt"
        
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            safe_move(str(src), str(dst))

    def test_preserves_file_permissions(self, tmp_path: Path) -> None:
        """Test that file permissions are preserved during move."""
        # Arrange
        src = tmp_path / "source.txt"
        dst = tmp_path / "destination.txt"
        src.write_text("content")
        src.chmod(0o600)  # Read/write for owner only
        original_mode = src.stat().st_mode
        
        # Act
        safe_move(str(src), str(dst))
        
        # Assert
        assert dst.stat().st_mode == original_mode