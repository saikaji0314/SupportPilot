# 反馈提取与状态合并

使用合成反馈观察事实纠正、检查结果与问题状态如何进入会话记忆。`cases.json` 中的人工反馈示例用于对照，不作为产品知识库。

```powershell
python -m supportpilot.cli.conversation_demo
python -m supportpilot.cli.conversation_demo --merge-only
python -m supportpilot.cli.conversation_demo --run
```

默认预览输入；merge-only 使用给定反馈执行纯 Python 合并；run 调用模型提取反馈，再执行合并。模型只接收用户文本与 State，`example_feedback` 和 `review` 不作为答案传入。

输出保存在 `.local/conversation/`。核心接口位于 `agent/conversation.py`：`extract_feedback` 解析本轮反馈，`merge_feedback` 合并事实、纠正与检查结果。

完整终端对话和回复回放见 [CHAT.md](CHAT.md)。
