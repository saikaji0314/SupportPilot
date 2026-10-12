# 给定资料的结构化回复

固定输入中的资料片段与会话状态，观察模型如何选择回答、追问、检查或交接。这个入口隔离检索的影响，适合对比回复提示词。

- `passages.json`：根据 [TP-Link FAQ 1556](https://www.tp-link.com/us/support/faq/1556/) 整理的中文短摘要，保留来源与章节。
- `cases.json`：合成用户问题、State 和片段选择；人工预期不传给模型。

```powershell
python -m supportpilot.cli.grounded_demo
```

命令调用聊天模型运行四个案例，输出保存到 `examples/grounded/eval/`（Git 忽略）。单个案例可通过 `run_case(model, "case-01")` 调用。

输出包含 `kind`、`text` 与 `evidence_ids`。资料 ID 引用输入片段，检查记录 ID 标识会话中实际提出的建议；资料无需预设操作编号。FAQ 为通用资料，示例的产品归属不意味着其内容适用于所有硬件或固件。
