"""Utilities for fetching GitHub repository metadata.

This module provides helper functions to query the GitHub REST API and
retrieve basic repository information such as star count, fork count, and
description.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
GITHUB_API_URL = "https://api.github.com"


def get_repository_basic_info(repo_full_name: str, token: str | None = None) -> dict[str, Any]:
    """Fetch basic information for a GitHub repository.

    Args:
        repo_full_name: Repository full name in the format ``owner/repo``.
        token: Optional GitHub personal access token for authenticated requests.

    Returns:
        A dictionary containing the repository's star count, fork count,
        description, and other basic metadata.

    Raises:
        ValueError: If ``repo_full_name`` is invalid.
        requests.RequestException: If the HTTP request fails.
    """
    if "/" not in repo_full_name:
        raise ValueError("repo_full_name must be in the format 'owner/repo'")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{GITHUB_API_URL}/repos/{repo_full_name}"
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()
    LOGGER.info("Fetched repository metadata for %s", repo_full_name)

    return {
        "full_name": data.get("full_name"),
        "html_url": data.get("html_url"),
        "description": data.get("description"),
        "stargazers_count": data.get("stargazers_count", 0),
        "forks_count": data.get("forks_count", 0),
    }
