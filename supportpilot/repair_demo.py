"""预览被拒绝的回复；--run 调用修正模型一次，不提交会话状态。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.chat_support import response_errors
from supportpilot.grounded import GroundedResponse
from supportpilot.response_repair import repair_response

ROOT = Path(__file__).resolve().parents[1]


def load_case(path):
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    candidate = GroundedResponse.model_validate(record["response"])
    errors = response_errors(candidate, record["updated"], record["passages"])
    return {"user_text": record["user_text"], "state": record["updated"],
            "passages": record["passages"], "rejected_response": candidate.model_dump(),
            "errors": errors}


def run_repair(model, payload, *, repair_fn=None):
    if not payload["errors"]:
        return {"status": "skipped", "reason": "原候选已通过程序校验，无需修正"}
    reply = GroundedResponse.model_validate((repair_fn or repair_response)(model, **deepcopy(payload)))
    errors = response_errors(reply, payload["state"], payload["passages"])
    return {"status": "completed", "response": reply.model_dump(),
            "errors": errors, "accepted": not errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--run", action="store_true", help="调用模型一次，不检索、不写入会话")
    args = parser.parse_args()
    payload = load_case(args.record)
    if not args.run or not payload["errors"]:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("仅预览；实现函数后加 --run。" if payload["errors"] else "校验通过，无需修正。")
        return
    folder = ROOT / ".local/repair" / uuid4().hex[:12]
    folder.mkdir(parents=True)
    result = {"source_record": str(args.record.resolve()), "input": payload, "status": "running"}
    def save():
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    print(f"记录目录：{folder}", flush=True)
    try:
        from supportpilot.bailian import bailian
        result.update(run_repair(bailian(), payload))
    except KeyboardInterrupt:
        result["status"] = "interrupted"
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__)
    save()
    print(json.dumps({k: v for k, v in result.items() if k not in ("input", "source_record")}, ensure_ascii=False, indent=2))
    print("accepted 仅代表程序校验；正文支持和步骤前提仍需人工确认。")
    if result["status"] in ("error", "interrupted"):
        parser.exit(1)


if __name__ == "__main__":
    main()
