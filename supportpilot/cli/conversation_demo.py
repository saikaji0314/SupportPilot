"""反馈实验：默认预览合成输入；--run 才调用模型；--merge-only 只验证合并。"""

from supportpilot.paths import ROOT
import argparse
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.agent.conversation import Feedback, extract_feedback, merge_feedback

CASES = ROOT / "examples" / "conversation" / "cases.json"


def load_cases():
    return json.loads(CASES.read_text(encoding="utf-8"))


def make_state():
    """仅实验夹具：此前助手已提出一项检查，用户现在反馈。"""
    return {
        "product_id": "tp-link-archer-ax55-us-v1",
        "facts": [{"id": "u1-f1", "text": "Internet IP 为 0.0.0.0", "source_message_id": "u1"}],
        "checks": [{"id": "c1", "text": "请检查路由器与调制解调器之间的物理连接，并反馈是否正常。",
                    "result": "unknown", "feedback": None, "source_message_id": None}],
        "pending": "c1",
        "status": "ongoing",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="调用聊天模型并合并；不调用嵌入")
    mode.add_argument("--merge-only", action="store_true", help="使用给定 Feedback，只运行合并")
    parser.add_argument("--case", help="只运行指定案例，例如 feedback-01")
    args = parser.parse_args()
    cases = [c for c in load_cases() if not args.case or c["id"] == args.case]
    if not cases:
        parser.error("未知案例 ID")
    model = None
    if args.run:
        from supportpilot.providers.bailian import bailian
        model = bailian()
    output_dir = ROOT / ".local" / "conversation" / uuid4().hex[:12]
    for case in cases:
        state = make_state()
        if case.get("without_pending"):
            state["checks"] = []
            state["pending"] = None
        if not args.run and not args.merge_only:
            print(json.dumps({**case, "state": state}, ensure_ascii=False, indent=2))
            continue
        original = deepcopy(state)
        record = {"case_id": case["id"], "user_text": case["user_text"], "before": original}
        try:
            feedback = (extract_feedback(model, user_text=case["user_text"], state=state)
                        if args.run else Feedback.model_validate(case["example_feedback"]))
            feedback = Feedback.model_validate(feedback)
            record["feedback"] = feedback.model_dump()
            after = merge_feedback(state, feedback, message_id="u2", user_text=case["user_text"])
            record["after"] = after
            if state != original:
                raise ValueError("函数修改了传入的旧 State，应返回副本")
        except NotImplementedError as exc:
            parser.exit(2, f"{exc}\n")
        except Exception as exc:
            # 不把供应商异常响应或凭据输出到日志。
            record["error_type"] = type(exc).__name__
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{case['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False, indent=2))
    if args.run or args.merge_only:
        print(f"结果目录：{output_dir}")


if __name__ == "__main__":
    main()
