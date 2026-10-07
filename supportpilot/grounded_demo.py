"""给定资料的单案例评估辅助；直接运行将调用模型并保存结果。"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from supportpilot.grounded import GroundedResponse, propose_response
from supportpilot.bailian import bailian
from supportpilot.utils import write_json, run_id


EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "grounded"


class CitationValidationError(ValueError):
    """保留被校验拒绝的回复，便于区分生成问题和分类问题。"""

    def __init__(self, reply: GroundedResponse, errors: list[str]):
        super().__init__("；".join(errors))
        self.reply = reply
        self.errors = errors


def load_case(case_id: str) -> dict:
    cases = json.loads((EXAMPLE_DIR / "cases.json").read_text(encoding="utf-8-sig"))
    passages = json.loads((EXAMPLE_DIR / "passages.json").read_text(encoding="utf-8-sig"))
    case = next((case for case in cases if case["id"] == case_id), None)
    if case is None:
        raise ValueError(f"未知案例：{case_id}")
    by_id = {passage["id"]: passage for passage in passages}
    # 这里是实验给定的资料集合，还没有做 RAG。
    return {
        "user_text": case["user_text"],
        "state": deepcopy(case["state"]),
        "passages": [deepcopy(by_id[item]) for item in case["passage_ids"]],
    }


def citation_errors(reply: GroundedResponse, passages: list[dict]) -> list[str]:
    """只校验引用归属；不代表原文支持性、适用性或查重已通过。"""
    available = {item["id"] for item in passages}
    errors = []
    if reply.kind in ("answer", "recommend_check") and not reply.evidence_ids:
        errors.append("产品问答或检查建议需要资料引用。")
    if set(reply.evidence_ids) - available:
        errors.append("存在不属于本轮资料的引用。")
    return errors


def run_case(model, case_id: str = "case-01") -> GroundedResponse:
    """由用户传入已有模型客户端；只有显式调用此函数才运行核心。"""
    payload = load_case(case_id)
    reply = GroundedResponse.model_validate(propose_response(model, **payload))
    errors = citation_errors(reply, payload["passages"])
    if errors:
        raise CitationValidationError(reply, errors)
    print(reply.model_dump_json(indent=2))
    return reply


def main(case_id: str, run_id: str = run_id()) -> None:
    # parser = argparse.ArgumentParser(description="预览资料驱动实验输入；不会调用模型")
    # parser.add_argument("--case", default="case-01")
    # args = parser.parse_args()

    # print("以下为给定资料的实验输入；本次将调用模型，不是实际检索评测：")
    # print(json.dumps(load_case(case_id), ensure_ascii=False, indent=2))

    eval_path = EXAMPLE_DIR / "eval" / run_id
    eval_path.mkdir(parents=True, exist_ok=True)

    model = bailian()
    try:
        resp = run_case(model, case_id)
    except CitationValidationError as e:
        print(e)
        write_json(
            {"error": str(e), "errors": e.errors, "response": e.reply.model_dump()},
            (eval_path / f"{case_id}.json"),
        )
        return
    except ValueError as e:
        print(e)
        write_json({"error": str(e)}, (eval_path / f"{case_id}.json"))
        return

    write_json(resp.model_dump(), (eval_path / f"{case_id}.json"))


if __name__ == "__main__":
    for case_id in ["case-01", "case-02", "case-03", "case-04"]:
        main(case_id)
