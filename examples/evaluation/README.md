# 单条离线评审入口

默认读取已保存的 chat/web 轮记录或 response_replay 结果，不重新检索或生成客服回复。

```powershell
python -m supportpilot.eval_demo --record examples/evaluation/synthetic-replay.json
```

生成 .local/evaluation 下的 JSON 与 Markdown 报告。synthetic-replay.json 是合成接线样例，不是设备运行成绩。记录与报告默认不上传 Git。

supportpilot/evaluation.py 提供评审 schema 和标准；evaluate_response 尚待实现。实现后可显式加 --judge 调用现有配置的模型评审候选回复，可能产生费用。默认不创建模型客户端。每项评审输出 pass/fail/unclear/not_applicable、理由及证据位置。

规则检查、语义评审、运行失败分别记录。固定正文的回复回放不等于端到端或多轮评测；本入口尚不含批量实验、Langfuse 或 Ragas 集成。

```powershell
python -m unittest discover -s tests -p test_evaluation.py
```
