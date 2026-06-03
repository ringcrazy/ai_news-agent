请帮我编写一个 Python 模块 pipeline/model_client.py，作为统一的 LLM 调用客户端：

需求：

1. 支持 DeepSeek、Qwen、OpenAI 三种模型提供商
2. 通过环境变量切换：LLM_PROVIDER（默认 deepseek）、对应的 API_KEY
3. 使用 httpx 直接调用 OpenAI 兼容 API（不依赖 openai SDK）
4. 用抽象基类 LLMProvider 定义接口，OpenAICompatibleProvider 实现
5. 统一返回 LLMResponse dataclass，包含 content 和 Usage 用量统计
6. 包含带重试的 chat_with_retry() 函数（3次，指数退避）和 60 秒超时
7. 包含 Token 消耗估算和成本计算函数（USD 计价）
8. 包含 quick_chat() 便捷函数，一句话调用 LLM
9. 最后有 if **name** == "**main**" 的测试代码

编码规范：遵循 PEP 8，Google 风格 docstring，使用 logging 不用 print
