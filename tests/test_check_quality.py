from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hooks.check_quality import main


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def high_quality_json_file(tmp_path: Path) -> Path:
    data = {
        "id": "2026-06-01-ai-understand-anything",
        "title": "High Quality AI Article",
        "source_url": "https://github.com/example/high-quality-ai-article",
        "summary": "这是一段足够长且包含技术关键词的摘要，用于测试质量评分脚本是否可以给出更高分数。",
        "tags": ["ai", "llm", "research"],
        "status": "published",
        "score": 9,
        "published_at": "2026-06-01T12:00:00Z",
    }
    file_path = tmp_path / "high_quality.json"
    _write_json(file_path, data)
    return file_path


@pytest.fixture()
def low_quality_json_file(tmp_path: Path) -> Path:
    data = {
        "id": "bad-id",
        "title": "Bad Quality Article",
        "source_url": "https://example.com/bad",
        "summary": "赋能全链路闭环打通。",
        "tags": ["unknown", "misc", "foo", "bar"],
        "status": "draft",
        "score": 1,
        "published_at": "2026-06-01T12:00:00Z",
    }
    file_path = tmp_path / "low_quality.json"
    _write_json(file_path, data)
    return file_path


@pytest.fixture()
def mixed_json_dir(tmp_path: Path) -> Path:
    good = {
        "id": "2026-06-01-good-entry",
        "title": "Good Entry",
        "source_url": "https://github.com/example/good-entry",
        "summary": "这是一段足够长的摘要，包含 Python 和 API 关键字，用于验证脚本的批量处理能力。",
        "tags": ["ai", "python"],
        "status": "published",
        "score": 8,
        "published_at": "2026-06-01T12:00:00Z",
    }
    bad = {
        "id": "bad-id-2",
        "title": "Bad Entry",
        "source_url": "ftp://example.com/bad",
        "summary": "打通闭环。",
        "tags": ["x", "y", "z", "w"],
        "status": "draft",
        "score": 2,
        "published_at": "2026-06-01T12:00:00Z",
    }
    _write_json(tmp_path / "good.json", good)
    _write_json(tmp_path / "bad.json", bad)
    return tmp_path


def test_check_quality_passes_for_high_quality_file(
    high_quality_json_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    exit_code = main(["check_quality.py", str(high_quality_json_file)])

    assert exit_code == 0
    assert "grade: A" in caplog.text
    assert "Quality check passed" in caplog.text


def test_check_quality_fails_for_low_quality_file(
    low_quality_json_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    exit_code = main(["check_quality.py", str(low_quality_json_file)])

    assert exit_code == 1
    assert "grade: C" in caplog.text
    assert "Quality check failed" in caplog.text
    assert "空洞词检测" in caplog.text


def test_check_quality_supports_glob_patterns(
    mixed_json_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    pattern = str(mixed_json_dir / "*.json")
    exit_code = main(["check_quality.py", pattern])

    assert exit_code == 1
    assert "Good Entry" in caplog.text
    assert "Bad Entry" in caplog.text
    assert "grade: C" in caplog.text
