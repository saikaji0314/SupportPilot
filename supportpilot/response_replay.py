"""回放已保存的一轮回复：默认预览，--run 只调用回复模型一次。"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.chat_support import response_errors
from supportpilot.grounded import GroundedResponse, propose_response

ROOT = Path(__file__).resolve().parents[1]


def load_payload(path: Path) -> tuple[dict, dict]:
    """重用原轮的已合并状态与检索正文，不混入后续消息或预期答案。"""
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    payload = {"user_text": record["user_text"], "state": record["updated"],
               "passages": record["passages"]}
    return payload, record.get("response", {})


def replay(model, payload: dict) -> dict:
    """保留候选输出和校验结果；人工另查资料是否支持及前提是否满足。"""
    reply = GroundedResponse.model_validate(propose_response(model, **payload))
    return {"response": reply.model_dump(),
            "errors": response_errors(reply, payload["state"], payload["passages"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path, help="此前保存的 turn-XX.json")
    parser.add_argument("--run", action="store_true", help="调用聊天模型一次；不检索、不请求嵌入")
    args = parser.parse_args()
    payload, original = load_payload(args.record)
    if not args.run:
        print(json.dumps({"user_text": payload["user_text"], "facts": payload["state"]["facts"],
                          "passage_ids": [p["id"] for p in payload["passages"]],
                          "original_response": original}, ensure_ascii=False, indent=2))
        print("仅预览。加 --run 才调用模型；原记录不会被覆盖。")
        return
    from supportpilot.bailian import bailian

    folder = ROOT / ".local/response-replay" / uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "result.json"
    result = {"source_record": str(args.record.resolve()), "input": payload,
              "original_response": original, "status": "running"}

    def save():
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    print(f"回放记录：{path}\n正在生成回复……", flush=True)
    try:
        result.update(replay(bailian(), payload), status="completed")
    except KeyboardInterrupt:
        result["status"] = "interrupted"
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__)
    save()
    print(json.dumps({k: result[k] for k in ("status", "response", "errors", "error_type") if k in result},
                     ensure_ascii=False, indent=2))
    print("errors 仅表示程序校验结果；仍需人工确认步骤前提和正文支持。")


if __name__ == "__main__":
    main()
