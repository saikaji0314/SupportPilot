"""离线评审服务；CLI 与管理端共用。"""
from collections import Counter
from supportpilot.evaluation.reviewer import RUBRIC, evaluate_response, validate_review, review_consistency_errors


def inspect_rules(trace: dict) -> dict:
    if not trace["reviewable"]:
        return {"status": "not_run", "errors": None}
    from supportpilot.agent.chat_support import response_errors
    from supportpilot.agent.grounded import GroundedResponse
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


