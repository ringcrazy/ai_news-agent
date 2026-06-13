from __future__ import annotations

import json
from pathlib import Path

import pytest

import patterns.router as router


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")


@pytest.fixture()
def stub_router_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(messages, model=None, temperature=0.7, max_tokens=None):
        return ("general chat answer", router.Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    def fake_chat_json(messages, model=None, temperature=0.0, max_tokens=None):
        return ({"intent": router.INTENT_GENERAL_CHAT, "reason": "fallback"}, router.Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    monkeypatch.setattr(router, "chat", fake_chat)
    monkeypatch.setattr(router, "chat_json", fake_chat_json)


def test_route_github_search(monkeypatch: pytest.MonkeyPatch, stub_router_dependencies: None) -> None:
    payload = {
        "items": [
            {
                "full_name": "example/demo-repo",
                "html_url": "https://github.com/example/demo-repo",
                "description": "A demo repository for testing",
                "stargazers_count": 123,
            }
        ]
    }
    monkeypatch.setattr(router.urllib.request, "urlopen", lambda req, timeout=20: _FakeResponse(payload))

    result = router.route("github 搜索 demo repo")

    assert "GitHub 搜索摘要" in result
    assert "example/demo-repo" in result
    assert "命中原因" in result


def test_route_knowledge_query(stub_router_dependencies: None) -> None:
    result = router.route("帮我查一下知识库里关于学术研究工作流的文章")

    assert "知识库摘要" in result
    assert "命中列表" in result
    assert "文件路径/ID" in result
    assert "命中原因" in result


def test_route_general_chat(monkeypatch: pytest.MonkeyPatch, stub_router_dependencies: None) -> None:
    monkeypatch.setattr(router, "_keyword_route", lambda query: None)
    monkeypatch.setattr(router, "_classify_intent", lambda query: router.INTENT_GENERAL_CHAT)

    result = router.route("解释一下 Router 路由模式")

    assert result == "general chat answer"
