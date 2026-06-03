"""GitHub API 工具模块.

封装 GitHub REST API v3 调用，提供获取仓库基本信息的能力。
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# GitHub REST API v3 基础地址
GITHUB_API_BASE = "https://api.github.com"

# 默认 HTTP 请求超时（秒）
DEFAULT_TIMEOUT = 10


def get_repo_info(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """获取指定 GitHub 仓库的基本信息.

    调用 ``GET /repos/{owner}/{repo}`` 端点，提取并标准化仓库核心元数据。

    Args:
        owner: 仓库所属用户名或组织名.
        repo: 仓库名称（不含 owner 前缀）.
        token: 可选的 GitHub Personal Access Token。携带后可将 API 速率上限
            从未认证的 60 次/小时提升至 5000 次/小时.
        timeout: HTTP 请求超时秒数，默认 10.

    Returns:
        包含以下字段的字典:
            - name (str): 仓库全名，格式 ``"{owner}/{repo}"``。
            - description (str | None): 仓库描述，可能为 ``None``。
            - stars (int): Star 总数。
            - forks (int): Fork 总数。
            - url (str): 仓库 HTML 地址。

    Raises:
        requests.HTTPError: 仓库不存在（404）、权限不足（403）或
            其他 4xx/5xx 错误。
        requests.RequestException: 网络异常或请求超时。

    Examples:
        >>> info = get_repo_info("openai", "openai-python")
        >>> info["name"]
        'openai/openai-python'
        >>> info["stars"] >= 0
        True
    """
    if not owner or not repo:
        raise ValueError("owner 和 repo 不能为空")

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    logger.info("获取 GitHub 仓库信息: %s", url)

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()

    payload = response.json()
    logger.info("成功获取仓库 %s/%s 信息", owner, repo)

    return {
        "name": payload.get("full_name", f"{owner}/{repo}"),
        "description": payload.get("description"),
        "stars": payload.get("stargazers_count", 0),
        "forks": payload.get("forks_count", 0),
        "url": payload.get("html_url", f"https://github.com/{owner}/{repo}"),
    }
