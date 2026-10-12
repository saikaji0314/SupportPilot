"""默认固定历史输出验证图接线；--run 才调用真实模型与检索。"""
from supportpilot.paths import ROOT
import argparse
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.agent.chat_graph import build_turn_graph, run_turn_graph
from supportpilot.agent.conversation import Feedback
from supportpilot.agent.grounded import GroundedResponse



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path, help="完整 chat/web turn 记录")
    parser.add_argument("--run", action="store_true", help="从原 before 重跑一轮，调用模型及嵌入服务")
    args = parser.parse_args()
    source = json.loads(args.record.read_text(encoding="utf-8-sig"))
    for key in ("before", "user_text", "feedback", "passages", "response"):
        if key not in source:
            parser.error(f"记录缺少 {key}，请选择完整 turn 记录")
    folder = ROOT / ".local/graph" / uuid4().hex[:12]
    folder.mkdir(parents=True)
    result = {"mode": "live" if args.run else "recorded_outputs",
              "source_record": str(args.record.resolve()), "status": "running", "stages": []}
    def save():
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    def progress(stage, data):
        result["stages"].append(stage)
        result["partial"] = {**result.get("partial", {}), **deepcopy(data)}
        save()
    save()
    print(f"记录目录：{folder}", flush=True)
    try:
        if args.run:
            from supportpilot.providers.bailian import bailian
            from supportpilot.agent.chat_support import make_retriever
            record = run_turn_graph(bailian(), user_text=source["user_text"],
                state=source["before"], retrieve=make_retriever(), on_progress=progress)
        else:
            graph = build_turn_graph(None, on_progress=progress, enable_repair=False,
                retrieve=lambda query, product_id: deepcopy(source["passages"]),
                feedback_fn=lambda *a, **kw: Feedback.model_validate(source["feedback"]),
                response_fn=lambda *a, **kw: GroundedResponse.model_validate(source["response"]))
            record = graph.invoke({"user_text": source["user_text"], "before": deepcopy(source["before"])})["record"]
            keys = ("updated", "query", "after", "accepted", "errors")
            result["matches_saved"] = {k: record[k] == source[k] if k in source else None for k in keys}
        result.update(status="completed", record=record)
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__)
    save()
    print(json.dumps({k: result[k] for k in ("mode", "status", "stages", "matches_saved", "error_type") if k in result}, ensure_ascii=False, indent=2))
    if result["status"] == "error":
        parser.exit(1)


if __name__ == "__main__":
    main()
