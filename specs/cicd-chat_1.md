请帮我创建 .github/workflows/daily-collect.yml，一个 GitHub Actions 工作流：

需求：

1. 每天 UTC 08:00（北京时间 16:00）自动运行
2. 同时支持手动触发（workflow_dispatch）
3. 添加 permissions: contents: write
4. 使用 Python 3.11，启用 pip 缓存
5. 通过 pip install -r requirements.txt 安装依赖
6. 运行命令：python pipeline/pipeline.py --sources github,rss --limit 20 --verbose
7. 支持多个 LLM 密钥（LLM_PROVIDER、DEEPSEEK_API_KEY、QWEN_API_KEY、OPENAI_API_KEY）
8. 采集后运行 validate_json.py 和 check_quality.py 校验文章
9. 自动 git commit + push，commit 消息包含文章数量和日期
10. 如果没有新数据则不提交（避免空 commit）
