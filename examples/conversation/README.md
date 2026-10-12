# 多轮反馈实验

验证用户反馈如何改变事实、检查记录和问题状态。案例均为合成数据，不含真实会话或产品排障知识库。

`conversation.py` 定义反馈结构与已实现的提取、合并函数；`conversation_demo.py` 提供预览、给定反馈的合并、模型反馈提取三个入口。反馈样例已验证；连续 RAG 对话入口与待实现接口见 [CHAT.md](CHAT.md)。

```powershell
python -m supportpilot.cli.conversation_demo
python -m supportpilot.cli.conversation_demo --merge-only
python -m supportpilot.cli.conversation_demo --run
```

默认只预览。`--run` 会调用聊天服务。案例中的 `example_feedback` 和 `review` 仅供人工对照，执行模型时只传用户文本和 State。输出存入被忽略的 `.local/conversation/`。
