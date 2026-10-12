# 终端对话与回复回放

终端入口复用反馈提取、状态合并、产品检索和资料驱动回复，适合观察一条会话中的事实变化。

```powershell
python -m supportpilot.cli.chat_demo
python -m supportpilot.cli.chat_demo --chat
```

默认仅展示结构；chat 使用单文档索引 `.local/rag/chunks.json`，需要先运行 [RAG 导入](../rag/README.md)。每轮调用聊天与嵌入服务。每次启动是新会话，输入 `/exit` 退出；恢复或交接后结束。网页的多产品、持久化及图修正入口见 [Web](../web/README.md)。

`facts` 记录用户事实，`checks` 保存检查及反馈，`pending` 保存待答项，`messages` 保留原话。轮记录存入 `.local/chat/`，包含 before、feedback、updated、query、passages、response、errors 与 after。被拒候选保留为诊断材料，不写入已接受会话。

## 固定输入的回复回放

```powershell
python -m supportpilot.cli.response_replay --record <轮记录.json>
python -m supportpilot.cli.response_replay --record <轮记录.json> --run
```

默认只预览；run 固定原状态与检索正文，重新调用回复模型，不重新检索或提取反馈。结果保存在 `.local/response-replay/`，原记录保持不变。
