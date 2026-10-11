# LangGraph 单轮入口

supportpilot/chat_graph.py 用六个节点复用既有提取、合并、查询、检索、回复和校验函数，提供兼容 run_turn 的 run_turn_graph。当前是独立入口，网页/API 尚未切换。

需要已可运行原聊天功能的 Python 环境及 langgraph；基础接线已在 LangGraph 1.2.12 验证。

```powershell
python -m supportpilot.graph_demo --record <完整的turn记录.json>
```

默认固定记录里的反馈、资料和候选回复，不调用模型；只检查本地数据传递与结果重现。matches_saved 不衡量回复质量。加 --run 才从原 before 和用户反馈调用真实模型与检索服务，可能产生费用。只支持完整 chat/web 轮记录。

结果存于 Git 忽略的 .local/graph/。没有 checkpoint，每次显式传入会话状态；END 表示本轮结束。尚未引入自动修正或在线模型裁判。

```powershell
python -m unittest discover -s tests -p test_chat_graph.py
```
