"""Supervisor pattern: Worker produces JSON reports; Supervisor reviews quality.

Flow:
- Worker Agent: analyze a task and return a structured JSON report.
- Supervisor Agent: score accuracy, depth, and format (1-10 each), then decide pass/fail.
- Retry loop: pass when overall score >= 7; otherwise rework with feedback (up to ``max_retries``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from workflows.model_client import chat, chat_json

LOGGER = logging.getLogger(__name__)

PASS_SCORE_THRESHOLD = 7

WORKER_SYSTEM = (
    "你是 Worker Agent。根据用户任务输出**仅包含一个 JSON 对象**的分析报告，不要输出 Markdown 代码块。\n"
    "JSON 字段建议：\n"
    '- "title": 简短标题\n'
    '- "summary": 100 字以内摘要\n'
    '- "analysis": 详细分析（字符串或字符串数组）\n'
    '- "conclusions": 结论列表\n'
    '- "risks_or_gaps": 风险或不足（可选）\n'
    "内容应基于任务本身，结构清晰、可审计。"
)

SUPERVISOR_SYSTEM = (
    "你是 Supervisor Agent，负责审核 Worker 的 JSON 分析报告。\n"
    "从以下三个维度打分（每项 1-10 整数）：\n"
    "- accuracy: 准确性\n"
    "- depth: 深度\n"
    "- format: JSON 结构与字段完整度\n\n"
    "综合 score 为三项的整数平均分（四舍五入）。\n"
    "passed 为 true 当且仅当 score >= 7。\n"
    "若未通过，feedback 必须具体说明如何改进（中文）。\n\n"
    '只输出 JSON：{"passed": bool, "score": int, "feedback": str, '
    '"accuracy": int, "depth": int, "format": int}'
)


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Run Worker/Supervisor loop until pass or retries exhausted.

    Args:
        task: User task description for the Worker to analyze.
        max_retries: Maximum number of Worker attempts (default 3).

    Returns:
        Dict with keys:
        - output: final Worker JSON report (dict)
        - attempts: number of attempts used
        - final_score: Supervisor's last overall score (1-10)
        - warning: present when max retries exceeded without pass
    """

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    feedback: Optional[str] = None
    last_output: dict[str, Any] = {}
    final_score = 0

    for attempt in range(1, max_retries + 1):
        LOGGER.info("Supervisor loop attempt %s/%s", attempt, max_retries)
        last_output = _worker_run(task, feedback=feedback)
        review = _supervisor_review(task, last_output)
        final_score = _coerce_score(review.get("score"))
        passed = final_score >= PASS_SCORE_THRESHOLD
        if passed:
            return {
                "output": last_output,
                "attempts": attempt,
                "final_score": final_score,
            }

        feedback = str(review.get("feedback") or "请提高准确性、深度并完善 JSON 结构。").strip()
        LOGGER.info(
            "Attempt %s rejected (score=%s): %s",
            attempt,
            final_score,
            feedback[:200],
        )

    return {
        "output": last_output,
        "attempts": max_retries,
        "final_score": final_score,
        "warning": (
            f"Supervisor 在 {max_retries} 轮内未通过审核（末轮 score={final_score}），"
            "已强制返回最后一版 Worker 输出。"
        ),
    }


def _worker_run(task: str, feedback: Optional[str] = None) -> dict[str, Any]:
    """Invoke Worker Agent and parse JSON report."""

    user_parts = [f"任务：{task.strip()}"]
    if feedback:
        user_parts.append(f"Supervisor 反馈（请据此修订）：{feedback}")
    user_content = "\n\n".join(user_parts)

    messages = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    try:
        data, _usage = chat_json(messages, temperature=0.3)
        if isinstance(data, dict):
            return data
    except Exception:
        LOGGER.exception("Worker chat_json failed, falling back to chat")
        text, _usage = chat(messages, temperature=0.3)
        return _parse_json_object(text)
    return {}


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text (forgiving)."""

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return {"value": data}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
            return {"value": data}
        except json.JSONDecodeError:
            pass
    return {"text": text}


def _supervisor_review(task: str, worker_output: dict[str, Any]) -> dict[str, Any]:
    """Invoke Supervisor Agent and parse review JSON."""

    worker_blob = json.dumps(worker_output, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SUPERVISOR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"原始任务：{task.strip()}\n\n"
                f"Worker 输出 JSON：\n{worker_blob}\n\n"
                "请审核并输出规定的 JSON。"
            ),
        },
    ]
    try:
        data, _usage = chat_json(messages, temperature=0.0)
        if isinstance(data, dict):
            return _normalize_review(data)
    except Exception:
        LOGGER.exception("Supervisor chat_json failed")

    return {
        "passed": False,
        "score": 0,
        "feedback": "Supervisor 审核调用失败，请重试 Worker 输出。",
        "accuracy": 0,
        "depth": 0,
        "format": 0,
    }


def _normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure review has score, passed, and dimension fields."""

    accuracy = _coerce_score(data.get("accuracy"))
    depth = _coerce_score(data.get("depth"))
    fmt = _coerce_score(data.get("format"))
    explicit_score = data.get("score")
    if explicit_score is not None:
        score = _coerce_score(explicit_score)
    else:
        score = round((accuracy + depth + fmt) / 3) if (accuracy + depth + fmt) else 0

    passed = score >= PASS_SCORE_THRESHOLD
    feedback = str(data.get("feedback") or "").strip()
    if not passed and not feedback:
        feedback = "综合得分不足 7，请补充分析深度并完善 JSON 字段。"

    return {
        "passed": passed,
        "score": score,
        "feedback": feedback,
        "accuracy": accuracy,
        "depth": depth,
        "format": fmt,
    }


def _coerce_score(value: Any) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(1, min(10, score)) if score else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_task = os.getenv(
        "SUPERVISOR_TEST_TASK",
        "分析 AI 知识库项目中 Router 与 Supervisor 两种 Agent 模式的适用场景。",
    )
    result = supervisor(sample_task, max_retries=int(os.getenv("SUPERVISOR_MAX_RETRIES", "3")))
    print(json.dumps(result, ensure_ascii=False, indent=2))