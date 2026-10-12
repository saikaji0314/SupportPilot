"""默认只读旧记录并出本地报告；--judge 才调用评审模型，不重跑客服。"""
from supportpilot.paths import ROOT
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.evaluation.reviewer import RUBRIC, evaluate_response, validate_review, review_consistency_errors
from supportpilot.evaluation.trajectory import load_trace, render_trace



from supportpilot.evaluation.service import inspect_rules, run_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--judge", action="store_true", help="调用现有配置的模型评审一次；可能产生费用")
    args = parser.parse_args()
    try:
        trace = load_trace(args.record)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"无法加载记录：{type(exc).__name__}\n")
    folder = ROOT / ".local/evaluation" / uuid4().hex[:12]
    folder.mkdir(parents=True)
    result = {"schema_version": 2, "trace": trace, "rubric": RUBRIC,
              "mode": "judge" if args.judge else "inspect",
              "evaluator_code_sha256": sha256((ROOT / "supportpilot/evaluation/reviewer.py").read_bytes()).hexdigest(),
              "evaluation": {"judge_status": "running" if args.judge else "not_run"}}

    def save():
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "report.md").write_text(render_trace(trace, result["evaluation"]), encoding="utf-8")

    save()
    model = None
    if args.judge and trace["reviewable"]:
        try:
            from supportpilot.providers.bailian import bailian
            model = bailian()
        except Exception as exc:
            result["evaluation"] = {"judge_status": "error", "error_type": type(exc).__name__}
            save()
            parser.exit(1, f"评审初始化失败；记录：{folder}\n")
    result["evaluation"] = run_review(trace, model=model)
    if args.judge and not trace["reviewable"]:
        result["evaluation"]["judge_status"] = "skipped_incomplete"
    save()
    print(f"报告：{folder / 'report.md'}")
    print(json.dumps(result["evaluation"], ensure_ascii=False, indent=2))
    if result["evaluation"]["judge_status"] == "error":
        parser.exit(1, "评审未完成；若为 NotImplementedError，请先实现 evaluate_response。\n")
    if result["evaluation"]["judge_status"] == "invalid_review":
        parser.exit(1, "评审缺少证据审计或自相矛盾；原输出已保留，不参与成绩统计。\n")


if __name__ == "__main__":
    main()
