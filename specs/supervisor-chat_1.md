请帮我编写 patterns/supervisor.py，实现 Supervisor 监督模式：

需求：

1. Worker Agent：接收任务，输出 JSON 格式的分析报告
2. Supervisor Agent：对 Worker 的输出进行质量审核
   - 评分维度：准确性(1-10)、深度(1-10)、格式(1-10)
   - 输出 JSON: {"passed": bool, "score": int, "feedback": str}
3. 审核循环：
   - 通过（score >= 7）→ 返回结果
   - 不通过 → 带反馈重做（最多 3 轮）
   - 超过 3 轮 → 强制返回 + 警告
4. 函数签名：supervisor(task: str, max_retries: int = 3) -> dict
5. 返回值包含：output, attempts, final_score, warning(可选)
6. 包含 if **name** == "**main**" 的测试入口

依赖：使用 workflows/model_client.py 的 chat() 函数
chat() 返回 (text, usage) 元组
