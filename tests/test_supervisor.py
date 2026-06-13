from __future__ import annotations

import pytest

import patterns.supervisor as supervisor_mod


@pytest.fixture()
def stub_supervisor_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic Worker/Supervisor responses without network."""

    call_state = {"worker": 0}

    def fake_chat_json(messages, model=None, temperature=0.0, max_tokens=None):
        content = messages[-1]["content"]
        if "Supervisor 反馈" in content or "请据此修订" in content:
            call_state["worker"] += 1
        system = messages[0]["content"] if messages else ""
        if "Supervisor Agent" in system:
            # First review fails, second passes
            if call_state["worker"] < 1:
                return (
                    {
                        "passed": False,
                        "score": 5,
                        "feedback": "分析过浅，请补充结论。",
                        "accuracy": 6,
                        "depth": 4,
                        "format": 7,
                    },
                    None,
                )
            return (
                {
                    "passed": True,
                    "score": 8,
                    "feedback": "通过",
                    "accuracy": 8,
                    "depth": 8,
                    "format": 8,
                },
                None,
            )
        return (
            {
                "title": "报告",
                "summary": "摘要",
                "analysis": "分析内容",
                "conclusions": ["结论1"],
            },
            None,
        )

    monkeypatch.setattr(supervisor_mod, "chat_json", fake_chat_json)


def test_supervisor_passes_on_second_attempt(stub_supervisor_llm: None) -> None:
    result = supervisor_mod.supervisor("测试任务", max_retries=3)

    assert result["attempts"] == 2
    assert result["final_score"] == 8
    assert "warning" not in result
    assert result["output"]["title"] == "报告"


def test_supervisor_forces_return_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_fail_review(messages, model=None, temperature=0.0, max_tokens=None):
        system = messages[0]["content"] if messages else ""
        if "Supervisor Agent" in system:
            return (
                {
                    "passed": False,
                    "score": 4,
                    "feedback": "仍不合格",
                    "accuracy": 4,
                    "depth": 4,
                    "format": 4,
                },
                None,
            )
        return ({"title": "末版", "summary": "s", "analysis": "a", "conclusions": []}, None)

    monkeypatch.setattr(supervisor_mod, "chat_json", always_fail_review)

    result = supervisor_mod.supervisor("任务", max_retries=3)

    assert result["attempts"] == 3
    assert result["final_score"] == 4
    assert "warning" in result
    assert result["output"]["title"] == "末版"


def test_supervisor_passes_first_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    def pass_first(messages, model=None, temperature=0.0, max_tokens=None):
        system = messages[0]["content"] if messages else ""
        if "Supervisor Agent" in system:
            return (
                {"passed": True, "score": 9, "feedback": "ok", "accuracy": 9, "depth": 9, "format": 9},
                None,
            )
        return ({"title": "一次过", "summary": "s", "analysis": "a", "conclusions": []}, None)

    monkeypatch.setattr(supervisor_mod, "chat_json", pass_first)

    result = supervisor_mod.supervisor("任务", max_retries=3)

    assert result["attempts"] == 1
    assert result["final_score"] == 9
    assert "warning" not in result