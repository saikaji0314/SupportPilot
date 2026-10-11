# 单条离线评审入口

默认读取已保存的 chat/web 轮记录或 response_replay 结果，不重新检索或生成客服回复。

```powershell
python -m supportpilot.eval_demo --record examples/evaluation/synthetic-replay.json
```

生成 .local/evaluation 下的 JSON 与 Markdown 报告。synthetic-replay.json 是合成接线样例，不是设备运行成绩。记录与报告默认不上传 Git。

supportpilot/evaluation.py 提供评审 schema 和标准；evaluate_response 已实现。可显式加 --judge 调用现有配置的模型评审候选回复，可能产生费用。默认不创建模型客户端。每项评审输出 pass/fail/unclear/not_applicable、理由及证据位置。

规则检查、语义评审、运行失败分别记录。固定正文的回复回放不等于端到端或多轮评测；本入口尚不含批量实验、Langfuse 或 Ragas 集成。

```powershell
python -m unittest discover -s tests -p test_evaluation.py
```

前提项附 audit，记录必要条件、用户确认事实、缺失条件和候选行为。缺 audit 或裁判同时报告“缺必要条件＋直接要求操作＋pass”时，judge_status 为 invalid_review；原评审保留，不输出 verdict_counts，命令返回非零退出码。它只检查显式矛盾，不能保证证据语义正确。其他项的 audit 为 null。新报告外层 schema_version 为 2，旧报告保持原样。
