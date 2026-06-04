"""Four-step knowledge base automation pipeline.

This module implements a small end-to-end pipeline for collecting AI-related
items from GitHub Search API and RSS feeds, analyzing them with an LLM,
normalizing/deduplicating the results, and persisting each article as an
independent JSON file under ``knowledge/articles/``.

Pipeline steps:
1. Collect
2. Analyze
3. Organize
4. Save
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
import yaml

try:
    from cost_tracker import get_cost_tracker
    from model_client import chat_with_retry, create_provider
except ImportError:  # pragma: no cover - compatibility fallback
    from cost_tracker import get_cost_tracker
    from model_client import chat_with_retry, get_env_provider as create_provider

LOGGER = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "knowledge" / "raw"
ARTICLES_DIR = ROOT_DIR / "knowledge" / "articles"
DEFAULT_TIMEOUT_SECONDS = 30.0
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
RSS_CONFIG_PATH = Path(__file__).resolve().parent / "rss_sources.yaml"
RSS_ITEM_PATTERN = re.compile(
    r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?"
    r"(?:<description>(.*?)</description>)?.*?</item>",
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"[A-Za-z0-9\-_/]+")


@dataclasses.dataclass(frozen=True)
class RawItem:
    """Raw collected content item."""

    title: str
    url: str
    source: str
    summary: str = ""
    popularity: int = 0


@dataclasses.dataclass(frozen=True)
class ArticleRecord:
    """Final normalized article record."""

    id: str
    title: str
    source: str
    source_url: str
    collected_at: str
    summary: str
    analysis: dict[str, Any]
    tags: list[str]
    status: str = "draft"


@dataclasses.dataclass(frozen=True)
class RSSSource:
    """Single RSS source definition loaded from YAML.

    Attributes:
        name: Human-readable source name (e.g. ``arXiv cs.AI``).
        url: RSS feed URL.
        category: Coarse classification (e.g. ``AI 研究``).
        enabled: Whether this source is active for collection.
    """

    name: str
    url: str
    category: str
    enabled: bool


def load_rss_sources(config_path: Path | str | None = None) -> list[RSSSource]:
    """Load enabled RSS sources from a YAML config file.

    The YAML structure must be::

        sources:
          - name: <str>
            url: <str>
            category: <str>
            enabled: <bool>

    Entries with ``enabled: false`` (or missing) are skipped.

    Args:
        config_path: Optional override path. Defaults to
            ``pipeline/rss_sources.yaml`` next to this module.

    Returns:
        List of enabled ``RSSSource`` entries, preserving YAML order.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the YAML is malformed or violates the expected schema.
    """

    path = Path(config_path) if config_path else RSS_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"RSS config not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"RSS config must be a mapping with 'sources': {path}")
    if "sources" not in data:
        raise ValueError(f"RSS config must define a 'sources' key: {path}")
    sources_raw = data.get("sources") or []
    if not isinstance(sources_raw, list):
        raise ValueError(f"'sources' must be a list in {path}")
    sources: list[RSSSource] = []
    for index, entry in enumerate(sources_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"RSS source at index {index} must be a mapping: {path}")
        if not bool(entry.get("enabled", False)):
            continue
        url = str(entry.get("url") or "").strip()
        if not url:
            raise ValueError(f"RSS source at index {index} missing 'url': {path}")
        name = str(entry.get("name") or "").strip() or url
        category = str(entry.get("category") or "").strip()
        sources.append(RSSSource(name=name, url=url, category=category, enabled=True))
    return sources


def collect_github(limit: int) -> list[RawItem]:
    """Collect AI-related repositories from GitHub Search API."""

    query = quote_plus("ai OR llm OR agent OR mcp OR rag in:name,description")
    url = (
        f"{GITHUB_SEARCH_URL}?q={query}&sort=stars&order=desc"
        f"&per_page={min(limit, 100)}"
    )
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()

    items: list[RawItem] = []
    for repo in payload.get("items", [])[:limit]:
        title = str(repo.get("full_name") or repo.get("name") or "").strip()
        html_url = str(repo.get("html_url") or "").strip()
        description = str(repo.get("description") or "").strip()
        stars = int(repo.get("stargazers_count") or 0)
        if title and html_url:
            items.append(
                RawItem(
                    title=title,
                    url=html_url,
                    source="github_trending",
                    summary=description,
                    popularity=stars,
                )
            )
    return items


def collect_rss(limit: int, config_path: Path | str | None = None) -> list[RawItem]:
    """Collect items from RSS feeds defined in the YAML config.

    Args:
        limit: Maximum total number of items to return across all feeds.
        config_path: Optional override path to the YAML config.

    Returns:
        List of raw items. Each ``source`` field is prefixed with ``rss:``
        followed by the feed's ``name`` so downstream code can identify the
        originating feed.
    """

    sources = load_rss_sources(config_path)
    if not sources:
        LOGGER.info(
            "No enabled RSS sources in config %s", config_path or RSS_CONFIG_PATH
        )
        return []
    results: list[RawItem] = []
    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        for feed in sources:
            if len(results) >= limit:
                break
            LOGGER.info("Fetching RSS feed: %s (%s)", feed.name, feed.url)
            response = client.get(feed.url)
            response.raise_for_status()
            matches = RSS_ITEM_PATTERN.findall(response.text)
            for title, link, description in matches:
                if len(results) >= limit:
                    break
                clean_title = _strip_html(title)
                clean_link = _strip_html(link)
                clean_desc = _strip_html(description)
                if clean_title and clean_link:
                    results.append(
                        RawItem(
                            title=clean_title,
                            url=clean_link,
                            source=f"rss:{feed.name}",
                            summary=clean_desc,
                            popularity=0,
                        )
                    )
    return results[:limit]


def analyze_items(items: list[RawItem]) -> list[ArticleRecord]:
    """Analyze collected items with the configured LLM."""

    analyzed: list[ArticleRecord] = []
    create_provider()
    for item in items:
        prompt = _build_analysis_prompt(item)
        response = chat_with_retry([{"role": "user", "content": prompt}])
        analysis = _parse_analysis_response(response.content)
        analyzed.append(_item_to_article(item, analysis))
    return analyzed


def organize_items(items: list[ArticleRecord]) -> list[ArticleRecord]:
    """Deduplicate, normalize, and validate article records."""

    seen: set[str] = set()
    organized: list[ArticleRecord] = []
    for item in items:
        normalized = _normalize_article(item)
        dedupe_key = normalized.source_url.rstrip("/")
        if dedupe_key in seen:
            continue
        _validate_article(normalized)
        seen.add(dedupe_key)
        organized.append(normalized)
    return organized


def save_items(items: list[ArticleRecord], dry_run: bool = False) -> list[Path]:
    """Save each article to an independent JSON file."""

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    for item in items:
        path = ARTICLES_DIR / f"{_safe_filename(item.id)}.json"
        if dry_run:
            LOGGER.info("[dry-run] would save %s", path)
        else:
            path.write_text(
                json.dumps(dataclasses.asdict(item), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOGGER.info("Saved %s", path)
        saved_paths.append(path)
    return saved_paths


def run_pipeline(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
    rss_config: Path | str | None = None,
) -> list[Path]:
    """Run the full pipeline.

    Args:
        sources: Collection sources to enable (``github`` and/or ``rss``).
        limit: Maximum items per selected source.
        dry_run: If True, skip writing article JSON files.
        rss_config: Optional path to the RSS sources YAML config.

    Returns:
        Paths of saved (or would-be-saved) article files.
    """

    collected: list[RawItem] = []
    collected_at = datetime.now(timezone.utc).isoformat()

    if "github" in sources:
        LOGGER.info("Collecting GitHub items")
        collected.extend(collect_github(limit))
    if "rss" in sources:
        LOGGER.info("Collecting RSS items")
        collected.extend(collect_rss(limit, config_path=rss_config))

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"pipeline-raw-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    raw_payload = {
        "collected_at": collected_at,
        "sources": sources,
        "items": [dataclasses.asdict(item) for item in collected],
    }
    raw_path.write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Saved raw data to %s", raw_path)

    analyzed = analyze_items(collected)
    organized = organize_items(analyzed)
    return save_items(organized, dry_run=dry_run)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(description="AI knowledge base pipeline")
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="Comma-separated sources: github,rss",
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="Max items per selected source"
    )
    parser.add_argument(
        "--rss-config",
        type=Path,
        default=None,
        help=(f"Path to RSS sources YAML config. Default: {RSS_CONFIG_PATH}"),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write article files"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser


def main() -> int:
    """CLI entry point."""

    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    sources = [
        source.strip().lower() for source in args.sources.split(",") if source.strip()
    ]
    valid_sources = {"github", "rss"}
    invalid = [source for source in sources if source not in valid_sources]
    if invalid:
        LOGGER.error("Unsupported sources: %s", ", ".join(invalid))
        return 2

    try:
        saved_paths = run_pipeline(
            sources=sources,
            limit=args.limit,
            dry_run=args.dry_run,
            rss_config=args.rss_config,
        )
        LOGGER.info("Pipeline finished, %s article files ready", len(saved_paths))
        get_cost_tracker().report()
        return 0
    except Exception:
        LOGGER.exception("Pipeline failed")
        return 1


def _build_analysis_prompt(item: RawItem) -> str:
    """Build an analysis prompt for a raw item."""

    return (
        "请分析下面这条 AI 相关内容，并严格输出 JSON。\n"
        "字段要求：summary(<=100字中文), relevance_score(1-10整数), tags(英文或中文短标签数组), tech_highlights(3-5项数组)。\n"
        f"title: {item.title}\n"
        f"url: {item.url}\n"
        f"source: {item.source}\n"
        f"summary: {item.summary}\n"
        f"popularity: {item.popularity}\n"
    )


def _parse_analysis_response(text: str) -> dict[str, Any]:
    """Parse the LLM response into structured analysis."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {
            "summary": text.strip()[:100],
            "relevance_score": 6,
            "tags": _guess_tags(text),
            "tech_highlights": [text.strip()[:60]],
        }
    data.setdefault("summary", "")
    data.setdefault("relevance_score", 6)
    data.setdefault("tags", [])
    data.setdefault("tech_highlights", [])
    return data


def _item_to_article(item: RawItem, analysis: dict[str, Any]) -> ArticleRecord:
    """Convert a raw item into an article record."""

    article_id = _make_article_id(item.url)
    collected_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    summary = str(analysis.get("summary") or item.summary or "")[:100]
    tags = [str(tag).strip() for tag in analysis.get("tags", []) if str(tag).strip()]
    return ArticleRecord(
        id=article_id,
        title=item.title,
        source=item.source,
        source_url=item.url,
        collected_at=collected_at,
        summary=summary,
        analysis={
            "tech_highlights": analysis.get("tech_highlights", []),
            "relevance_score": int(analysis.get("relevance_score", 6)),
        },
        tags=tags,
        status="draft",
    )


def _normalize_article(item: ArticleRecord) -> ArticleRecord:
    """Normalize whitespace and structural fields."""

    return ArticleRecord(
        id=item.id.strip(),
        title=item.title.strip(),
        source=item.source.strip(),
        source_url=item.source_url.strip(),
        collected_at=item.collected_at.strip(),
        summary=item.summary.strip()[:100],
        analysis=item.analysis,
        tags=sorted({tag.strip() for tag in item.tags if tag.strip()}),
        status=item.status.strip() or "draft",
    )


def _validate_article(item: ArticleRecord) -> None:
    """Validate required fields for an article record."""

    required = [
        item.id,
        item.title,
        item.source_url,
        item.summary,
        item.tags,
        item.status,
    ]
    if any(not value for value in required):
        raise ValueError(f"Invalid article record: {item.id}")


def _make_article_id(url: str) -> str:
    """Create a stable article id from the source URL."""

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    return f"{date_prefix}-{digest}"


def _safe_filename(value: str) -> str:
    """Make a filesystem-safe filename."""

    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def _strip_html(value: str) -> str:
    """Strip simple HTML tags from text."""

    text = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", text).strip()


def _guess_tags(text: str) -> list[str]:
    """Guess tags from a free-form analysis response."""

    tokens = TAG_PATTERN.findall(text.lower())
    return list(dict.fromkeys(tokens[:5]))


if __name__ == "__main__":
    sys.exit(main())
