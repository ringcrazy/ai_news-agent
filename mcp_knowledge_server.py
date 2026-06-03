"""MCP server for searching the local knowledge base.

This server exposes a small JSON-RPC 2.0 over stdio interface compatible with
MCP tool discovery and invocation.

Supported tools:
- search_articles(keyword, limit=5)
- get_article(article_id)
- knowledge_stats()

The server scans JSON files under ``knowledge/articles/`` and keeps everything
self-contained with only Python standard library dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
ARTICLES_DIR = ROOT_DIR / "knowledge" / "articles"
JSONRPC_VERSION = "2.0"

SEARCH_TOOL_NAME = "search_articles"
GET_TOOL_NAME = "get_article"
STATS_TOOL_NAME = "knowledge_stats"

TOOL_SCHEMAS = [
    {
        "name": SEARCH_TOOL_NAME,
        "description": "Search local articles by keyword in title and summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results.",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": GET_TOOL_NAME,
        "description": "Get the full JSON content of an article by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "Article id."},
            },
            "required": ["article_id"],
        },
    },
    {
        "name": STATS_TOOL_NAME,
        "description": "Return knowledge base statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


@dataclass(frozen=True)
class Article:
    """Normalized article record loaded from disk."""

    path: Path
    data: dict[str, Any]

    @property
    def article_id(self) -> str:
        return str(self.data.get("id", "")).strip()

    @property
    def title(self) -> str:
        return str(self.data.get("title", "")).strip()

    @property
    def source(self) -> str:
        return str(self.data.get("source", "")).strip()

    @property
    def summary(self) -> str:
        return str(self.data.get("summary", "")).strip()

    @property
    def tags(self) -> list[str]:
        tags = self.data.get("tags", [])
        if isinstance(tags, list):
            return [str(tag).strip() for tag in tags if str(tag).strip()]
        return []


class KnowledgeBase:
    """Load and query local knowledge articles."""

    def __init__(self, articles_dir: Path) -> None:
        self._articles_dir = articles_dir
        self._articles = self._load_articles()
        self._by_id = {article.article_id: article for article in self._articles if article.article_id}

    def _load_articles(self) -> list[Article]:
        articles: list[Article] = []
        if not self._articles_dir.exists():
            return articles

        for path in sorted(self._articles_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    articles.append(Article(path=path, data=data))
            except Exception as exc:  # pragma: no cover - defensive load guard
                LOGGER.warning("Skipping invalid article file %s: %s", path, exc)
        return articles

    def search_articles(self, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
        keyword_norm = keyword.strip().lower()
        if not keyword_norm:
            return []

        scored: list[tuple[int, Article]] = []
        for article in self._articles:
            text = f"{article.title}\n{article.summary}".lower()
            score = text.count(keyword_norm)
            if score > 0:
                scored.append((score, article))

        scored.sort(key=lambda item: (-item[0], item[1].title.lower()))
        results: list[dict[str, Any]] = []
        for score, article in scored[: max(1, min(limit, 50))]:
            results.append(
                {
                    "id": article.article_id,
                    "title": article.title,
                    "source": article.source,
                    "summary": article.summary,
                    "tags": article.tags,
                    "score": article.data.get("analysis", {}).get("relevance_score")
                    if isinstance(article.data.get("analysis"), dict)
                    else article.data.get("score"),
                    "match_score": score,
                    "path": str(article.path),
                }
            )
        return results

    def get_article(self, article_id: str) -> dict[str, Any] | None:
        article = self._by_id.get(article_id.strip())
        if article is None:
            return None
        return article.data

    def knowledge_stats(self) -> dict[str, Any]:
        sources = Counter()
        tags = Counter()
        for article in self._articles:
            sources[article.source or "unknown"] += 1
            tags.update(article.tags)

        return {
            "total_articles": len(self._articles),
            "source_distribution": dict(sorted(sources.items(), key=lambda item: (-item[1], item[0]))),
            "top_tags": [
                {"tag": tag, "count": count}
                for tag, count in tags.most_common(10)
            ],
        }


class McpKnowledgeServer:
    """Minimal MCP server over stdio."""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._kb = knowledge_base

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "mcp-knowledge-server",
                        "version": "1.0.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {"tools": TOOL_SCHEMAS},
            }

        if method == "tools/call":
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": self._handle_tool_call(params),
            }

        if method == "notifications/initialized":
            return None

        return self._error(request_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", "")).strip()
        arguments = params.get("arguments") or {}

        if name == SEARCH_TOOL_NAME:
            keyword = str(arguments.get("keyword", ""))
            limit = int(arguments.get("limit", 5) or 5)
            payload = self._kb.search_articles(keyword, limit=limit)
            return self._tool_result(payload)

        if name == GET_TOOL_NAME:
            article_id = str(arguments.get("article_id", ""))
            article = self._kb.get_article(article_id)
            if article is None:
                return self._tool_error(f"Article not found: {article_id}")
            return self._tool_result(article)

        if name == STATS_TOOL_NAME:
            return self._tool_result(self._kb.knowledge_stats())

        return self._tool_error(f"Unknown tool: {name}")

    @staticmethod
    def _tool_result(payload: Any) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ],
            "isError": False,
        }

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        return {
            "content": [
                {
                    "type": "text",
                    "text": message,
                }
            ],
            "isError": True,
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def _iter_jsonrpc_messages() -> Iterable[dict[str, Any]]:
    """Read JSON-RPC requests from stdin line by line."""

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("Skipping invalid JSON-RPC line")
            continue
        if isinstance(message, dict):
            yield message


def main() -> int:
    """Run the MCP knowledge server."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    kb = KnowledgeBase(ARTICLES_DIR)
    server = McpKnowledgeServer(kb)

    for request in _iter_jsonrpc_messages():
        response = server.handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
