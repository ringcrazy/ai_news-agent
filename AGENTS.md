# AGENTS.md

## 项目概述

个人 AI 知识库助手系统。自动从技术信息源（GitHub Trending、Hacker News）采集 AI/LLM/Agent 领域内容，经过 AI 分析后结构化存储，并支持多渠道分发，帮助持续沉淀可检索、可复用的技术知识。

## 技术栈

- 语言: Python 3.11
- AI 编排: OpenCode + 国产大模型（DeepSeek/Qwen/GLM/Kimi）
- 工作流: LangGraph（第 3 周引入）
- 部署: OpenClaw（第 4 周引入）
- 依赖管理: pip + requirements.txt
- 版本控制: Git

## 编码规范

- 遵循 PEP 8 规范
- Python 版本统一使用 Python 3.11
- 使用 `black` 进行代码格式化，格式化结果为唯一标准
- 使用 `ruff` 进行静态检查与基础代码质量约束
- 变量名、函数名、模块名统一使用 `snake_case`
- 类名统一使用 `PascalCase`
- 常量统一使用 `UPPER_SNAKE_CASE`
- 所有公开函数、公开类和公开模块都必须提供 docstring
- docstring 统一使用 Google 风格
- docstring 必须说明用途、参数、返回值；如有异常抛出，也必须说明
- 禁止裸 `print()`，统一使用标准日志库 `logging`
- 日志内容不得包含 API Key、Token、Cookie、密码、隐私数据等敏感信息
- 禁止 `import *`
- 文件编码统一 UTF-8
- 禁止提交包含临时调试输出、未说明用途的 TODO、FIXME 或占位实现
- 业务配置、环境变量、敏感参数不得写死在代码中
- 单个函数应尽量保持职责单一，避免过长、过深嵌套和过度分支

## 项目结构

- `AGENTS.md`：项目规范
- `opencode.json`：OpenCode 配置
- `.opencode/agents/`：Agent 角色定义文件
  - `collector.md`
  - `analyzer.md`
  - `organizer.md`
- `.opencode/skills/`：可复用技能包
  - `github-trending/SKILL.md`
  - `tech-summary/SKILL.md`
- `knowledge/raw/`：原始采集数据（JSON）
- `knowledge/articles/`：结构化知识条目（JSON）
- `pipeline/`：自动化流水线（Week 2）
- `workflows/`：LangGraph 工作流（Week 3）
- `openclaw/`：OpenClaw 部署配置（Week 4）

## 内容规范

- 摘要语言: 中文
- 摘要长度: 不超过 100 字
- 技术术语保留英文原文（如 LangGraph、Agent、Token）
- 评分标准: 1-10 分，9-10 改变格局，7-8 直接有帮助，5-6 值得了解

## 知识条目格式

每条知识以 JSON 文件存储在 `knowledge/articles/` 目录下：

```json
{
  "id": "2026-03-01-github-openclaw",
  "title": "OpenClaw: 开源 AI Agent 运行时",
  "source": "github-trending",
  "source_url": "https://github.com/example/project",
  "collected_at": "2026-03-01T10:00:00Z",
  "summary": "一句话中文摘要（不超过 100 字）",
  "analysis": {
    "tech_highlights": ["多 Agent 路由", "50+ 平台支持"],
    "relevance_score": 9
  },
  "tags": ["agent", "runtime", "open-source"],
  "status": "draft"
}
```

**必填字段**: `id`, `title`, `source_url`, `summary`, `tags`, `status`

**status 可选值**: `draft` / `reviewed` / `published`

## Agent 角色概览

| 角色 | 文件 | 职责 |
| --- | --- | --- |
| 采集 Agent | `.opencode/agents/collector.md` | 从外部源采集技术动态 |
| 分析 Agent | `.opencode/agents/analyzer.md` | 深度分析和价值评估 |
| 整理 Agent | `.opencode/agents/organizer.md` | 去重、格式化、归档 |

## 红线（绝对禁止）

- 不编造不存在的项目或数据
- 不在日志中输出 API Key 或敏感信息
- 不执行 `rm -rf` 等危险命令
- 不修改 `AGENTS.md` 本身（除非明确要求）
- 禁止绕过测试、静态检查或审查流程直接合并到主分支
- 禁止未经验证就将错误数据写入知识库或分发渠道
- 禁止随意删除知识数据、测试数据或审计痕迹
