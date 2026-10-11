"""默认只读旧记录并出本地报告；--judge 才调用评审模型，不重跑客服。"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.evaluation import RUBRIC, evaluate_response, validate_review, review_consistency_errors
from supportpilot.trajectory import load_trace, render_trace

ROOT = Path(__file__).resolve().parents[1]


def inspect_rules(trace: dict) -> dict:
    if not trace["reviewable"]:
        return {"status": "not_run", "errors": None}
    from supportpilot.chat_support import response_errors
    from supportpilot.grounded import GroundedResponse
    try:
        reply = GroundedResponse.model_validate(trace["response"])
        errors = response_errors(reply, trace["payload"]["state"], trace["payload"]["passages"])
        return {"status": "completed", "errors": errors}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "errors": None}


def run_review(trace: dict, *, model=None, evaluator=evaluate_response) -> dict:
    result = {"rules": inspect_rules(trace), "judge_status": "not_run", "review": None,
              "review_errors": None}
    if model is None:
        return result
    if not trace["reviewable"]:
        result["judge_status"] = "skipped_incomplete"
        return result
    try:
        review = validate_review(evaluator(model, payload=trace["payload"],
                                          response=trace["response"], rubric=RUBRIC), RUBRIC)
        errors = review_consistency_errors(review)
        result.update(judge_status="invalid_review" if errors else "completed",
                      review=review.model_dump(), review_errors=errors)
        # 保留裁判原结论；矛盾输出不参与通过/失败统计，也不改写成 fail。
        if not errors:
            result["verdict_counts"] = dict(Counter(i.verdict for i in review.items))
    except Exception as exc:
        result.update(judge_status="error", error_type=type(exc).__name__)
    return result


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
              "evaluator_code_sha256": sha256((ROOT / "supportpilot/evaluation.py").read_bytes()).hexdigest(),
              "evaluation": {"judge_status": "running" if args.judge else "not_run"}}

    def save():
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "report.md").write_text(render_trace(trace, result["evaluation"]), encoding="utf-8")

    save()
    model = None
    if args.judge and trace["reviewable"]:
        try:
            from supportpilot.bailian import bailian
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
