"""Quality scoring for knowledge entry JSON files.

This script supports single-file and glob-pattern inputs, scores each entry
across five dimensions, prints a visual progress bar, and exits non-zero when
any entry receives grade C.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

TECH_KEYWORDS = {
    "api",
    "architecture",
    "cache",
    "ci",
    "database",
    "debug",
    "docker",
    "kubernetes",
    "llm",
    "model",
    "optimization",
    "performance",
    "prompt",
    "python",
    "react",
    "security",
    "testing",
    "vector",
}

VALID_TAGS = {
    "ai",
    "agent",
    "backend",
    "database",
    "devops",
    "frontend",
    "learning",
    "llm",
    "productivity",
    "python",
    "research",
    "security",
    "tools",
}

VAGUE_WORDS_ZH = {
    "赋能",
    "抓手",
    "闭环",
    "打通",
    "全链路",
    "底层逻辑",
    "颗粒度",
    "对齐",
    "拉通",
    "沉淀",
    "强大的",
    "革命性的",
}

VAGUE_WORDS_EN = {
    "groundbreaking",
    "revolutionary",
    "game-changing",
    "cutting-edge",
}

REQUIRED_FIELDS = ("id", "title", "source_url", "status")
TIMESTAMP_FIELDS = ("published_at", "created_at", "updated_at")
URL_PATTERN = re.compile(r"^https?://.+")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: int
    max_score: int
    note: str = ""


@dataclass(frozen=True)
class QualityReport:
    path: Path
    title: str
    total_score: int
    grade: str
    dimensions: tuple[DimensionScore, ...]
    summary: str


@dataclass(frozen=True)
class EntryResult:
    path: Path
    report: QualityReport | None
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.report is not None and not self.errors


def expand_inputs(args: list[str]) -> list[Path]:
    files: set[Path] = set()
    for arg in args:
        matches = glob.glob(arg, recursive=True) if any(ch in arg for ch in "*?[]") else [arg]
        for match in matches:
            path = Path(match)
            if path.is_file() and path.suffix.lower() == ".json":
                files.add(path.resolve())
    return sorted(files)


def load_json(path: Path) -> tuple[Any | None, list[str]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), []
    except FileNotFoundError:
        return None, [f"File not found: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})"]


def normalize_entries(data: Any, path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(data, dict):
        return [data], []
    if isinstance(data, list):
        errors = []
        entries: list[dict[str, Any]] = []
        for index, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                errors.append(f"{path} [item {index}]: each entry must be an object")
                continue
            entries.append(item)
        return entries, errors
    return [], [f"{path}: root JSON value must be a list or object"]


def score_summary(summary: str | None) -> DimensionScore:
    text = (summary or "").strip()
    length = len(text)
    score = 0
    note_parts: list[str] = []
    if length >= 50:
        score = 25
        note_parts.append("length>=50")
    elif length >= 20:
        score = 15
        note_parts.append("length>=20")
    elif length > 0:
        score = 5
        note_parts.append("short summary")
    else:
        note_parts.append("missing summary")

    lower_text = text.lower()
    if any(keyword in lower_text for keyword in TECH_KEYWORDS):
        score = min(25, score + 3)
        note_parts.append("tech keyword bonus")

    return DimensionScore("摘要质量", score, 25, "; ".join(note_parts))


def score_technical_depth(item: dict[str, Any]) -> DimensionScore:
    raw_score = item.get("score")
    numeric = 0
    if isinstance(raw_score, int):
        numeric = max(0, min(10, raw_score))
    score = int(round(numeric / 10 * 25))
    note = f"source score={raw_score!r}"
    return DimensionScore("技术深度", score, 25, note)


def score_format(item: dict[str, Any]) -> DimensionScore:
    score = 0
    checks = [
        ("id", isinstance(item.get("id"), str) and bool(item.get("id", "").strip()) and bool(ID_PATTERN.match(str(item.get("id"))))),
        ("title", isinstance(item.get("title"), str) and bool(item.get("title", "").strip())),
        ("source_url", isinstance(item.get("source_url"), str) and bool(URL_PATTERN.match(str(item.get("source_url"))))),
        ("status", isinstance(item.get("status"), str) and bool(item.get("status", "").strip())),
        ("timestamp", any(isinstance(item.get(field), str) and bool(item.get(field, "").strip()) for field in TIMESTAMP_FIELDS)),
    ]
    for _, passed in checks:
        if passed:
            score += 4
    note = ", ".join(name for name, passed in checks if passed) or "no format checks passed"
    return DimensionScore("格式规范", score, 20, note)


def score_tags(tags: Any) -> DimensionScore:
    if not isinstance(tags, list):
        return DimensionScore("标签精度", 0, 15, "tags missing or invalid")

    cleaned = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
    valid_count = sum(1 for tag in cleaned if tag in VALID_TAGS)
    if 1 <= len(cleaned) <= 3 and valid_count == len(cleaned):
        score = 15
        note = "1-3 valid tags"
    elif 1 <= len(cleaned) <= 3:
        score = max(5, 15 - (len(cleaned) - valid_count) * 3)
        note = f"{valid_count}/{len(cleaned)} tags valid"
    elif len(cleaned) == 0:
        score = 0
        note = "no tags"
    else:
        score = max(0, 10 - max(0, len(cleaned) - 3) * 2)
        note = f"tag count={len(cleaned)}"
    return DimensionScore("标签精度", score, 15, note)


def score_vague_words(item: dict[str, Any]) -> DimensionScore:
    combined = " ".join(
        str(item.get(field, "")) for field in ("title", "summary", "content", "description")
    ).lower()
    zh_hits = [word for word in VAGUE_WORDS_ZH if word in combined]
    en_hits = [word for word in VAGUE_WORDS_EN if word in combined]
    penalty = min(15, (len(zh_hits) + len(en_hits)) * 4)
    score = 15 - penalty
    note = "clean" if not (zh_hits or en_hits) else f"zh={zh_hits}, en={en_hits}"
    return DimensionScore("空洞词检测", score, 15, note)


def classify_grade(total_score: int) -> str:
    if total_score >= 80:
        return "A"
    if total_score >= 60:
        return "B"
    return "C"


def build_report(item: dict[str, Any], path: Path) -> QualityReport:
    dimensions = (
        score_summary(item.get("summary")),
        score_technical_depth(item),
        score_format(item),
        score_tags(item.get("tags")),
        score_vague_words(item),
    )
    total_score = sum(d.score for d in dimensions)
    grade = classify_grade(total_score)
    title = str(item.get("title") or item.get("id") or path.stem)
    summary = " | ".join(f"{d.name}:{d.score}/{d.max_score}" for d in dimensions)
    return QualityReport(path=path, title=title, total_score=total_score, grade=grade, dimensions=dimensions, summary=summary)


def validate_file(path: Path) -> EntryResult:
    data, errors = load_json(path)
    if errors:
        return EntryResult(path=path, report=None, errors=tuple(errors))

    entries, normalize_errors = normalize_entries(data, path)
    reports: list[QualityReport] = []
    all_errors = list(normalize_errors)
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            all_errors.append(f"{path} [item {index}]: each entry must be an object")
            continue
        reports.append(build_report(item, path))

    if reports:
        # Single-file mode can contain one object; multi-file mode can also be one object per file.
        # We keep the first report for structured output and print all reports during execution.
        return EntryResult(path=path, report=reports[0], errors=tuple(all_errors))
    return EntryResult(path=path, report=None, errors=tuple(all_errors or [f"{path}: no valid entries found"]))


def render_progress(score: int, max_score: int = 100, width: int = 30) -> str:
    ratio = 0 if max_score <= 0 else max(0.0, min(1.0, score / max_score))
    filled = int(round(ratio * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {score:>3}/{max_score}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score knowledge entry JSON files.")
    parser.add_argument("json_files", nargs="+", help="JSON files or glob patterns to score")
    return parser


def print_report(report: QualityReport) -> None:
    LOGGER.info("%s", report.path)
    LOGGER.info("  title: %s", report.title)
    LOGGER.info("  score: %s  grade: %s  %s", report.total_score, report.grade, render_progress(report.total_score))
    for dimension in report.dimensions:
        LOGGER.info("  - %s: %s/%s (%s)", dimension.name, dimension.score, dimension.max_score, dimension.note)
    LOGGER.info("  summary: %s", report.summary)


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    files = expand_inputs(args.json_files)
    if not files:
        LOGGER.error("No JSON files matched the provided input.")
        return 1

    any_c_grade = False
    total_reports = 0
    for path in files:
        result = validate_file(path)
        if result.errors:
            for error in result.errors:
                LOGGER.error("%s", error)
        if result.report is not None:
            print_report(result.report)
            total_reports += 1
            if result.report.grade == "C":
                any_c_grade = True

    if total_reports == 0:
        LOGGER.error("No valid knowledge entries were found.")
        return 1

    if any_c_grade:
        LOGGER.error("Quality check failed: at least one entry received grade C.")
        return 1

    LOGGER.info("Quality check passed for %s file(s).", total_reports)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main(sys.argv))
