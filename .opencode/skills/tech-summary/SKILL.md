---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# Tech Summary Skill

## 使用场景

当需要对 `knowledge/raw/` 中已经采集到的技术内容进行深度分析、总结、评分与标签建议时，使用此技能。

## 执行步骤

1. 读取 `knowledge/raw/` 中最新的采集文件，确认输入数据范围与来源。
2. 对每条内容进行逐条深度分析：摘要不超过 50 字、提炼 2-3 个技术亮点、给出 1-10 分评分并附理由、提出标签建议。
3. 进行趋势发现，归纳多个项目之间的共同主题、新概念或新方向。
4. 将分析结果输出为 JSON，供后续整理与分发使用。

## 评分标准

- `9-10`：改变格局，具有显著范式价值或行业影响力
- `7-8`：直接有帮助，能够明显提升效率或能力
- `5-6`：值得了解，适合持续关注或学习
- `1-4`：可略过，价值有限或噪声较高

## 约束

- 在 15 个项目中，`9-10` 分的项目不超过 2 个
- 评分必须克制，避免过度打高分
- 所有摘要必须为中文，且尽量精炼准确
- 技术亮点必须基于事实，不得编造或夸大
- 标签建议应服务于检索、分类和后续分发

## 注意事项

- 不直接修改 `knowledge/raw/` 的原始数据
- 不输出未经验证的结论
- 不为了凑趋势而虚构共同主题
- 不允许评分失真或标签过度泛化

## 输出格式

输出必须为 JSON，建议结构如下：

```json
{
  "source": "github-trending",
  "skill": "tech-summary",
  "collected_at": "2026-06-01T00:00:00Z",
  "items": [
    {
      "title": "Example Project",
      "url": "https://github.com/example/example-project",
      "summary": "50字以内中文摘要",
      "highlights": ["亮点1", "亮点2", "亮点3"],
      "score": 8,
      "score_reason": "直接解决了某类核心问题",
      "suggested_tags": ["ai", "agent", "llm"]
    }
  ],
  "trends": {
    "common_themes": ["多 Agent", "RAG"],
    "new_concepts": ["..." ]
  }
}
```
