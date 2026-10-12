# LangGraph 单轮编排与回放

图主链路组织反馈提取、状态合并、查询构建、检索、回复与校验。校验拒绝后进入一次修正节点，再次拒绝则结束且不提交状态。超时、合并与结构解析异常走错误处理。

```powershell
python -m supportpilot.cli.graph_demo --record <完整轮记录.json>
python -m supportpilot.cli.graph_demo --record <完整轮记录.json> --run
```

默认使用保存的反馈、资料与最终候选回放数据传递，不调用服务，也不重演记录中的内部修正。`matches_saved` 表示与保存结果的一致性。run 从原 before 与用户反馈重新执行，调用模型与检索，启用有界修正。

输入需要 before、user_text、feedback、passages 和 response。结果保存至 `.local/graph/`。修正候选与错误保存在 `repair_attempts`；最终 response/errors/after 对应最终校验结果。

图接口为 `build_turn_graph` / `run_turn_graph`，网页调用同一入口。State 显式传入；SQLite 提交业务状态，图没有启用 checkpoint。END 表示本轮执行结束，回复质量由独立评测检查。
