# LangGraph 单轮入口

supportpilot/chat_graph.py 用主链路节点和一个修正节点复用既有提取、合并、查询、检索、回复和校验函数，提供兼容 run_turn 的 run_turn_graph。网页/API 已通过 Runtime 调用 run_turn_graph；graph_demo 仍可独立运行。

需要已可运行原聊天功能的 Python 环境及 langgraph；基础接线已在 LangGraph 1.2.12 验证。

```powershell
python -m supportpilot.graph_demo --record <完整的turn记录.json>
```

默认固定记录里的反馈、资料和候选回复，不调用模型；只检查本地数据传递与结果重现。matches_saved 不衡量回复质量。加 --run 才从原 before 和用户反馈调用真实模型与检索服务，可能产生费用。只支持完整 chat/web 轮记录。

结果存于 Git 忽略的 .local/graph/。没有 checkpoint，每次显式传入会话状态；END 表示本轮结束。网页和 --run 已启用最多一次候选修正：finish_turn 拒绝后进入 repair_response，再回到 finish_turn；再次拒绝则结束且不提交状态。超时、反馈合并异常和结构解析异常直接返回失败，不触发此分支。不接在线模型裁判。

修正时记录 repair_attempts（原候选与错误）；最终 response/errors/after 对应再次校验结果。默认离线回放关闭修正，只重现记录里的最终候选，不重演内部修正轨迹。

```powershell
python -m unittest discover -s tests -p test_chat_graph.py
```
