---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending Skill

## 使用场景

当需要从 GitHub 热门开源项目中采集与 AI / LLM / Agent 相关的技术动态，并输出结构化的原始数据时，使用此技能。

## 执行步骤

1. 使用 GitHub API 搜索热门仓库，优先关注 trending 相关数据源。
2. 提取每个仓库的基础信息，包括名称、链接、星标数、语言和 topics。
3. 过滤结果，仅纳入 AI / LLM / Agent 相关项目，排除明显的 Awesome 列表和非项目型仓库。
4. 对候选项目进行去重，避免同一仓库重复出现。
5. 撰写中文摘要，摘要公式为：项目名 + 做什么 + 为什么值得关注。
6. 按热度、相关性和质量排序，取 Top 15。
7. 将结果输出为 JSON，并保存到 `knowledge/raw/github-trending-YYYY-MM-DD.json`。

## 注意事项

- 只采集公开可访问的信息，不编造项目数据。
- 摘要必须使用中文，且尽量简洁、准确。
- 排除纯列表、聚合页、教程索引页等非项目仓库。
- 不得输出未经验证的星标数、语言或 topics。
- 如遇到 API 限流，应降低请求频率并避免重复抓取。

## 输出格式

输出必须为 JSON，结构如下：

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "2026-06-01T00:00:00Z",
  "items": [
    {
      "name": "example-repo",
      "url": "https://github.com/example/example-repo",
      "summary": "项目名 + 做什么 + 为什么值得关注",
      "stars": 12345,
      "language": "Python",
      "topics": ["ai", "llm", "agent"]
    }
  ]
}
```
