from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hooks.validate_json import main


def _write_json(path: Path, data: object) -> None:
    """Write JSON test data to a file."""
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def sample_json_file(tmp_path: Path) -> Path:
    """Create a valid sample JSON file."""
    data = {
        "id": "2026-06-01-github-understand-anything",
        "title": "Example AI Project",
        "source_url": "https://github.com/example/example-ai-project",
        "summary": "这是一个足够长的中文摘要，用于通过校验。",
        "tags": ["ai", "llm"],
        "status": "draft",
        "score": 8,
        "audience": "intermediate",
    }
    file_path = tmp_path / "valid.json"
    _write_json(file_path, data)
    return file_path


@pytest.fixture()
def invalid_json_file(tmp_path: Path) -> Path:
    """Create an invalid sample JSON file."""
    data = [
        {
            "id": "bad-id",
            "title": "Example AI Project",
            "source_url": "ftp://example.com",
            "summary": "太短",
            "tags": [],
            "status": "bad_status",
            "score": 20,
            "audience": "expert",
        }
    ]
    file_path = tmp_path / "invalid.json"
    _write_json(file_path, data)
    return file_path


def test_validate_json_passes_for_valid_file(
    sample_json_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Validate that a correct file passes."""
    caplog.set_level(logging.INFO)

    exit_code = main(["validate_json.py", str(sample_json_file)])

    assert exit_code == 0
    assert "Validation passed" in caplog.text


def test_validate_json_fails_for_invalid_file(
    invalid_json_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Validate that an incorrect file fails with errors."""
    caplog.set_level(logging.ERROR)

    exit_code = main(["validate_json.py", str(invalid_json_file)])

    assert exit_code == 1
    assert "invalid id format" in caplog.text
    assert "summary must be at least 20 characters" in caplog.text
    assert "Validation failed" in caplog.text
