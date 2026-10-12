# 轨迹评测与报告

固定保存的用户输入、合并后 State、检索正文与候选回复，分别执行程序检查和可选语义评审，便于定位建议缺乏依据、前提未确认或历史处理错误。

```powershell
python -m supportpilot.cli.eval_demo --record examples/evaluation/synthetic-replay.json
python -m supportpilot.cli.eval_demo --record <轮记录.json> --judge
```

默认只执行规则检查，生成 `.local/evaluation/<id>/result.json` 与 `report.md`。judge 使用配置的聊天模型评审原候选，不重新检索或生成客服回复。公开 JSON 是合成数据夹具；真实会话和报告不随仓库分发。

## 评审标准

| 标准 | 关注点 |
| --- | --- |
| grounding | 产品事实与操作是否被引用正文支持 |
| preconditions | 必要条件是否由用户当前事实确认 |
| history | 是否尊重纠正、检查结果与每轮一项检查 |

每项保留 verdict、reason 与 support_refs，verdict 为 pass/fail/unclear/not_applicable。前提项的 audit 保存必要条件、已确认事实、缺项和候选行为。缺审计或显式矛盾输出标记为 `invalid_review`，保留原结果且不计入 verdict_counts；CLI 返回非零退出码。

规则结果、裁判错误与语义结论分别记录。审计校验只识别输出中的明确缺项或矛盾，模型语义判断仍需人工审阅。固定回复评审不衡量整段会话或实际设备解决率。

管理端可选择同一会话的多个轮次，保存人工备注并调用同一 `evaluation/service.py`，见 [管理端指南](../web/ADMIN.md)。
