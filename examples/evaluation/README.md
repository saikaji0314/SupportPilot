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

## Ragas 指标

安装可选依赖后，使用 `--ragas` 对保存的回复评分。`--judge` 与 `--ragas` 分别运行，分数不混合。

```powershell
python -m pip install -r requirements-ragas.txt
python -m supportpilot.cli.eval_demo --record examples/evaluation/synthetic-replay.json --ragas
```

`--ragas` 会把该轮问题、状态/历史、候选回复和检索正文发送给已配置的聊天服务，产生多次模型调用费用。复用 `config.py` 中的聊天模型、地址和密钥；不需要嵌入服务。默认不运行 Ragas，浏览或下载报告不触发模型。Ragas 的匿名使用遥测在初始化前关闭。

| 指标 | 本项目的评测口径 |
| --- | --- |
| Faithfulness | 回答中的陈述是否受到本轮生成上下文支持 |
| Context Utilization | 最终上下文各片段相对于候选回答的有用性，按保存的上下文顺序计算 |

当前没有人工参考答案，使用不需要 reference 的指标。Context Utilization 使用生成模型实际收到的完整 `passages`，包含可能补入的前文；它不是原始向量召回排名的 Context Precision，也不衡量全部相关资料是否被召回。指标定义见 [Ragas Faithfulness](https://docs.ragas.io/en/v0.4.3/concepts/metrics/available_metrics/faithfulness/) 与 [Context Utilization](https://docs.ragas.io/en/v0.4.3/concepts/metrics/available_metrics/context_precision/)。

多轮短答结合保存的事实、检查和历史构造 `user_input`，输入版本为 `conversation-context-v1`；这些历史数据不加入 `retrieved_contexts` 充当官方证据。样本、片段 ID/顺序、输入哈希、适配代码哈希、Ragas 版本及评测模型保存在 `evaluation.ragas` 中。分数用于比较同一口径下的回答，不能直接与独立 QA 基准混算。

仅 `answer` 和 `recommend_check` 进入当前指标；追问、恢复确认、转人工标记 `not_applicable`。缺正文标记 `missing_data`，中断记录标记 `skipped_incomplete`，依赖缺失标记 `unavailable`。无有限数值的指标保留 `undefined` 与 `null`；超时、结构化输出错误等保留 `error`，单项成功可保留为 `partial`。这些状态都不会变成 0 分或满分。

两项指标依次运行；每项总超时 120 秒，每个模型请求超时 60 秒，SDK 不自动重试，结构化输出只尝试一次。Faithfulness 通常需要两次模型调用，Context Utilization 每个片段需要一次；并非每个指标只请求一次。部分失败、全部失败或依赖不可用时 CLI 返回非零退出码，报告仍保留已有结果。

Ragas 分数独立于程序规则与业务裁判，不计算综合通过率。高分不能证明引用 ID 正确、用户满足操作前提、检查不重复，或设备问题已解决；仍需原来的业务评审与人工核查。
