请帮我创建 pipeline/rss_sources.yaml，配置知识库的 RSS 数据源：

需求：

1. YAML 格式，每个源包含 name、url、category、enabled 字段
2. 包含以下分类的数据源：
   - 综合技术：Hacker News Best (AI 相关)、Lobsters AI/ML
   - AI 研究：arXiv cs.AI
   - 公司博客：OpenAI Blog、Anthropic Research、Hugging Face Blog
   - 中文社区：机器之心、量子位（默认 disabled，需确认 RSS 可用性）
3. 每个源的 enabled 字段控制是否采集
4. 量太大的源默认设为 enabled: false
