"""Validate knowledge entry JSON files.

This script validates one or more JSON files containing knowledge entries.
It supports direct file paths and glob patterns.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# 必填字段及其对应类型
REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}
# 允许的状态值
VALID_STATUS = {"draft", "review", "published", "archived"}
# 允许的受众值
VALID_AUDIENCE = {"beginner", "intermediate", "advanced"}
# ID 格式：兼容两种常见写法
# 1) {source}-{YYYYMMDD}-{NNN}
# 2) {YYYY-MM-DD}-{source}-{slug}
ID_PATTERN = re.compile(
    r"^(?:[a-z0-9-]+-\d{8}-\d{3}|\d{4}-\d{2}-\d{2}-[a-z0-9-]+-[a-z0-9-]+(?:-[a-z0-9-]+)*)$"
)
# URL 格式：以 http:// 或 https:// 开头
URL_PATTERN = re.compile(r"^https?://.+")
# 当前模块日志对象
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    """存储单个文件的校验结果。"""

    path: Path
    errors: list[str]

    @property
    def is_valid(self) -> bool:
        """判断当前文件是否通过校验。"""
        return not self.errors


def expand_inputs(args: list[str]) -> list[Path]:
    """将命令行参数展开为 JSON 文件列表。

    Args:
        args: 不包含脚本名的命令行参数。

    Returns:
        去重并排序后的 JSON 文件路径列表。
    """
    files: set[Path] = set()
    for arg in args:
        # 如果参数包含通配符，则按模式展开；否则按单文件处理
        path = Path(arg)
        if any(char in arg for char in "*?[]"):
            matches = [Path(match) for match in glob.glob(arg, recursive=True)]
        else:
            matches = [path]

        # 只保留存在的 .json 文件
        for match in matches:
            if match.is_file() and match.suffix.lower() == ".json":
                files.add(match.resolve())

    return sorted(files)


def load_json(path: Path) -> tuple[Any | None, list[str]]:
    """读取并解析 JSON 文件。

    Args:
        path: JSON 文件路径。

    Returns:
        解析后的对象或 None，以及错误列表。
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), []
    except FileNotFoundError:
        return None, [f"File not found: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})"]


def validate_item(item: dict[str, Any], path: Path, index: int) -> list[str]:
    """校验单条知识条目。

    Args:
        item: 待校验的 JSON 对象。
        path: 来源文件路径。
        index: 条目在文件中的序号。

    Returns:
        错误列表。
    """
    errors: list[str] = []
    prefix = f"{path} [item {index}]"

    # 逐个检查必填字段是否存在且类型正确
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in item:
            errors.append(f"{prefix}: missing required field '{field}'")
            continue
        if not isinstance(item[field], expected_type):
            errors.append(
                f"{prefix}: field '{field}' must be {expected_type.__name__}, got {type(item[field]).__name__}"
            )

    # 检查 ID 格式是否符合 source-YYYYMMDD-NNN
    item_id = item.get("id")
    if isinstance(item_id, str) and not ID_PATTERN.match(item_id):
        errors.append(f"{prefix}: invalid id format '{item_id}'")

    # 检查 source_url 是否是合法的 http/https 链接
    source_url = item.get("source_url")
    if isinstance(source_url, str) and not URL_PATTERN.match(source_url):
        errors.append(f"{prefix}: invalid source_url '{source_url}'")

    # 摘要长度至少 20 字，避免过短信息
    summary = item.get("summary")
    if isinstance(summary, str) and len(summary.strip()) < 20:
        errors.append(f"{prefix}: summary must be at least 20 characters")

    # 标签至少需要 1 个
    tags = item.get("tags")
    if isinstance(tags, list) and len(tags) < 1:
        errors.append(f"{prefix}: tags must contain at least 1 item")

    # 状态值必须在允许范围内
    status = item.get("status")
    if isinstance(status, str) and status not in VALID_STATUS:
        errors.append(f"{prefix}: invalid status '{status}'")

    # 如果存在 score，则范围必须在 1 到 10 之间
    score = item.get("score")
    if score is not None and (not isinstance(score, int) or not 1 <= score <= 10):
        errors.append(f"{prefix}: score must be an integer between 1 and 10")

    # 如果存在 audience，则必须是允许的受众值之一
    audience = item.get("audience")
    if audience is not None and (not isinstance(audience, str) or audience not in VALID_AUDIENCE):
        errors.append(f"{prefix}: audience must be one of {sorted(VALID_AUDIENCE)}")

    return errors


def validate_file(path: Path) -> ValidationResult:
    """校验单个 JSON 文件。

    Args:
        path: JSON 文件路径。

    Returns:
        包含错误信息的校验结果。
    """
    data, errors = load_json(path)
    if errors:
        return ValidationResult(path=path, errors=errors)

    # 兼容两种结构：
    # 1) 根节点是 list，表示多条知识条目
    # 2) 根节点是单个 dict，表示一条知识条目
    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        return ValidationResult(path=path, errors=[f"{path}: root JSON value must be a list or object"])

    all_errors = errors[:]
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            all_errors.append(f"{path} [item {index}]: each entry must be an object")
            continue
        all_errors.extend(validate_item(item, path, index))

    return ValidationResult(path=path, errors=all_errors)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Validate knowledge entry JSON files.",
        add_help=True,
    )
    parser.add_argument("json_files", nargs="+", help="JSON files or glob patterns to validate")
    return parser


def main(argv: list[str]) -> int:
    """运行 JSON 校验命令行程序。

    Args:
        argv: 命令行参数，包含脚本名。

    Returns:
        进程退出码。
    """
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    files = expand_inputs(args.json_files)
    if not files:
        LOGGER.error("No JSON files matched the provided input.")
        return 1

    results = [validate_file(path) for path in files]
    failures = [result for result in results if not result.is_valid]

    total_files = len(results)
    valid_files = total_files - len(failures)
    total_errors = sum(len(result.errors) for result in failures)

    if failures:
        for result in failures:
            for error in result.errors:
                LOGGER.error("%s", error)
        LOGGER.error(
            "Validation failed: %s/%s files passed, %s files failed, %s total errors.",
            valid_files,
            total_files,
            len(failures),
            total_errors,
        )
        return 1

    LOGGER.info("Validation passed: %s/%s files passed, 0 errors.", valid_files, total_files)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main(sys.argv))
