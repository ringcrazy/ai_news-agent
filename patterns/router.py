"""Two-layer intent router for query handling.

This module implements:
- Layer 1: zero-cost keyword routing
- Layer 2: LLM fallback classification for ambiguous queries

Supported intents:
- github_search
- knowledge_query
- general_chat

The router returns a human-readable string response.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from workflows.model_client import chat, chat_json
except ImportError:  # pragma: no cover - fallback for current repo layout
    from pipeline.model_client import chat, chat_json  # type: ignore

LOGGER = logging.getLogger(__name__)

INTENT_GITHUB_SEARCH = "github_search"
INTENT_KNOWLEDGE_QUERY = "knowledge_query"
INTENT_GENERAL_CHAT = "general_chat"

KEYWORD_RULES = {
    INTENT_GITHUB_SEARCH: [
        "github",
        "repo",
        "repository",
        "star",
        "fork",
        "commit",
        "pull request",
        "pr",
        "issue",
        "release",
        "代码仓库",
        "仓库",
    ],
    INTENT_KNOWLEDGE_QUERY: [
        "knowledge",
        "article",
        "articles",
        "index",
        "检索",
        "查找资料",
        "知识库",
        "文章",
        "文档",
        "资料",
    ],
}

GITHUB_API_URL = "https://api.github.com/search/repositories"
DEFAULT_GITHUB_TOP_K = 3
DEFAULT_KNOWLEDGE_TOP_K = 3
INDEX_PATH = (
    Path(__file__).resolve().parent.parent / "knowledge" / "articles" / "index.json"
)
ARTICLE_DIR = INDEX_PATH.parent


@dataclass(frozen=True)
class Usage:
    """Token usage information returned by the underlying LLM client."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class RoutedKnowledgeHit:
    path: str
    article_id: str
    title: str
    summary: str
    reason: str
    score: float


def route(query: str) -> str:
    """Route a user query to the best handler and return text output."""

    normalized_query = _normalize_text(query)
    intent = _classify_intent(normalized_query)

    if intent == INTENT_GITHUB_SEARCH:
        return github_search_handler(query)
    if intent == INTENT_KNOWLEDGE_QUERY:
        return knowledge_query_handler(query)
    return general_chat_handler(query)


def github_search_handler(query: str) -> str:
    """Search GitHub repositories using the public search API."""

    encoded_query = urllib.parse.quote(query, safe="")
    url = f"{GITHUB_API_URL}?q={encoded_query}&sort=stars&order=desc&per_page={DEFAULT_GITHUB_TOP_K}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "router-bot"},
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network failures are runtime only
        LOGGER.exception("GitHub search failed")
        return f"GitHub 搜索失败：{exc}"

    items = payload.get("items") or []
    if not items:
        return f"未找到与“{query}”相关的 GitHub 仓库。"

    lines = [
        f"GitHub 搜索摘要：共找到 {len(items)} 个结果，以下是最相关的 {min(len(items), DEFAULT_GITHUB_TOP_K)} 条："
    ]
    for item in items[:DEFAULT_GITHUB_TOP_K]:
        name = item.get("full_name") or item.get("name") or "unknown"
        html_url = item.get("html_url") or ""
        description = item.get("description") or "暂无描述"
        reason = _github_hit_reason(query, item)
        lines.append(
            f"- {name}\n  - 摘要：{description}\n  - 路径/ID：{html_url}\n  - 命中原因：{reason}"
        )
    return "\n".join(lines)


def knowledge_query_handler(query: str) -> str:
    """Search local knowledge articles with keyword relevance scoring."""

    articles = _load_articles()
    if not articles:
        return "本地知识库中没有可检索的文章。"

    scored = [_score_article(query, article) for article in articles]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return f"未在知识库中找到与“{query}”相关的内容。"

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_hits = scored[:DEFAULT_KNOWLEDGE_TOP_K]
    summary = _summarize_hits(query, top_hits)

    lines = [f"知识库摘要：{summary}", "命中列表："]
    for score, article, reason in top_hits:
        lines.append(
            f"- {article.get('title', article.get('id', 'unknown'))}\n"
            f"  - 摘要：{article.get('summary', '暂无摘要')}\n"
            f"  - 文件路径/ID：{_article_path(article)} / {article.get('id', 'unknown')}\n"
            f"  - 命中原因：{reason}"
        )
    return "\n".join(lines)


def general_chat_handler(query: str) -> str:
    """Answer directly via LLM."""

    text, _usage = chat([{"role": "user", "content": query}])
    return text


def _classify_intent(query: str) -> str:
    keyword_intent = _keyword_route(query)
    if keyword_intent:
        return keyword_intent

    prompt = (
        "你是一个路由分类器，只能输出 JSON。\n"
        "根据用户输入判断意图，只能从以下三种里选一个：\n"
        f"- {INTENT_GITHUB_SEARCH}\n"
        f"- {INTENT_KNOWLEDGE_QUERY}\n"
        f"- {INTENT_GENERAL_CHAT}\n\n"
        '输出格式：{"intent": "...", "reason": "..."}\n'
        f"用户输入：{query}"
    )
    try:
        data, _usage = chat_json([{"role": "user", "content": prompt}])
        intent = str(data.get("intent", "")).strip()
        if intent in {
            INTENT_GITHUB_SEARCH,
            INTENT_KNOWLEDGE_QUERY,
            INTENT_GENERAL_CHAT,
        }:
            return intent
    except Exception:
        LOGGER.exception("LLM intent classification failed")

    return INTENT_GENERAL_CHAT


def _keyword_route(query: str) -> Optional[str]:
    for intent, keywords in KEYWORD_RULES.items():
        if any(keyword in query for keyword in keywords):
            return intent

    if re.search(r"https?://github\.com|github\s+search|search\s+github", query, re.I):
        return INTENT_GITHUB_SEARCH
    if re.search(r"知识库|文章|资料|检索|查询.*(知识|文章|资料)", query):
        return INTENT_KNOWLEDGE_QUERY
    return None


def _load_articles() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return _load_articles_from_directory()

    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        LOGGER.exception("Failed to load index.json")
        return []

    raw_articles: list[dict[str, Any]] = []
    if isinstance(data, list):
        raw_articles = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        raw = data.get("articles")
        if isinstance(raw, list):
            raw_articles = [item for item in raw if isinstance(item, dict)]

    return [_enrich_article(article) for article in raw_articles]


def _enrich_article(article: dict[str, Any]) -> dict[str, Any]:
    """Backfill stale index entries with the canonical article file.

    The index.json is a metadata cache and may lag behind the source
    files. When a critical field such as ``summary`` is missing, load
    the actual article file (referenced by ``file_path``) and merge it
    so scoring has the real text to match against.
    """

    summary = article.get("summary")
    needs_enrichment = summary is None or (
        isinstance(summary, str) and not summary.strip()
    )
    if not needs_enrichment:
        return article

    file_path_str = article.get("file_path")
    if not file_path_str:
        return article

    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = INDEX_PATH.parent.parent.parent / file_path_str
    try:
        if not file_path.exists():
            return article
        full = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.exception("Failed to enrich article from %s", file_path)
        return article

    if not isinstance(full, dict):
        return article

    merged = {**article, **full}
    merged["_path"] = str(file_path)
    return merged


def _load_articles_from_directory() -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for path in sorted(ARTICLE_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            article = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(article, dict):
                article["_path"] = str(path)
                articles.append(article)
        except Exception:
            LOGGER.exception("Failed to load article: %s", path)
    return articles


def _score_article(
    query: str, article: dict[str, Any]
) -> tuple[float, dict[str, Any], str]:
    tokens = _tokenize(query)
    text = " ".join(
        str(article.get(field, ""))
        for field in ("title", "summary", "id", "source", "source_url")
    ).lower()
    tags = article.get("tags") or []
    if isinstance(tags, list):
        text += " " + " ".join(str(tag).lower() for tag in tags)

    score = 0.0
    reasons: list[str] = []

    title = str(article.get("title", "")).lower()
    summary = str(article.get("summary", "")).lower()
    for token in tokens:
        if not token:
            continue
        title_count = title.count(token)
        summary_count = summary.count(token)
        tag_count = sum(1 for tag in tags if token in str(tag).lower())
        if title_count:
            score += 5 * title_count
            reasons.append(f"标题命中“{token}”")
        if summary_count:
            score += 2 * summary_count
            reasons.append(f"摘要命中“{token}”")
        if tag_count:
            score += 3 * tag_count
            reasons.append(f"标签命中“{token}”")
        if token in text:
            score += 1

    if article.get("id"):
        article_id = str(article["id"]).lower()
        if any(token in article_id for token in tokens):
            score += 2
            reasons.append("ID 相关")

    reason = "；".join(dict.fromkeys(reasons)) or "关键词与标题/摘要存在相关性"
    return score, article, reason


def _summarize_hits(query: str, hits: list[tuple[float, dict[str, Any], str]]) -> str:
    keywords = ", ".join(_tokenize(query)[:5]) or query
    titles = ", ".join(
        str(article.get("title", article.get("id", "unknown")))
        for _score, article, _reason in hits
    )
    return f"围绕“{keywords}”共命中 {len(hits)} 条，主题最接近的内容包括：{titles}。"


def _article_path(article: dict[str, Any]) -> str:
    if article.get("_path"):
        return str(article["_path"])
    article_id = str(article.get("id", "unknown"))
    return str(ARTICLE_DIR / f"{article_id}.json")


def _github_hit_reason(query: str, item: dict[str, Any]) -> str:
    q = query.lower()
    pieces: list[str] = []
    full_name = str(item.get("full_name", "")).lower()
    description = str(item.get("description", "")).lower()
    if full_name and any(word in full_name for word in _tokenize(q)):
        pieces.append("仓库名相关")
    if description and any(word in description for word in _tokenize(q)):
        pieces.append("描述相关")
    if item.get("stargazers_count"):
        pieces.append("高 star 倾向")
    return "；".join(pieces) or "搜索词与仓库名称/描述相关"


def _tokenize(text: str) -> list[str]:
    """Split text into tokens for keyword/relevance matching.

    CJK characters are also added as individual tokens so Chinese queries
    can match against article titles and summaries that contain those
    characters as substrings.
    """

    normalized = _normalize_text(text)
    parts = re.split(r'\s+|[,，。！？；;:/\\|()（）\[\]{}<>"]+', normalized)
    parts = [p for p in parts if p]

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    if cjk_chars:
        parts = list(dict.fromkeys(parts + cjk_chars))

    if len(parts) == 1:
        return parts + [normalized]
    return parts


def _normalize_text(text: str) -> str:
    return str(text).strip().lower()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample = os.getenv("ROUTER_TEST_QUERY", "帮我找一下 n8n 的 GitHub 仓库")
    print(route(sample))
