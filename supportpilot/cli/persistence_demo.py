"""使用合成数据验证 SQLite 保存与恢复，不调用模型。"""
from supportpilot.paths import ROOT
from pathlib import Path
from uuid import uuid4
import json

from supportpilot.agent.chat_support import finish_turn, next_turn_ids
from supportpilot.agent.conversation import Feedback, merge_feedback
from supportpilot.agent.grounded import GroundedResponse
from supportpilot.storage.session_store import SessionStore, SessionConflict


def main():
    folder = ROOT / ".local/persistence" / uuid4().hex[:12]
    store = SessionStore(folder / "sessions.sqlite")
    owner = "synthetic-owner"
    identifier = store.create(owner, "synthetic-product")
    before = store.load(owner, identifier)["state"]
    record = finish_turn(before=before, updated=before, user_text="合成设备无法连接",
        feedback=Feedback(), query="合成问题", passages=[{
            "id": "p1", "product_ids": ["synthetic-product"], "text": "合成资料：检查指示灯。",
            "source_url": "https://example.test/manual", "page": 1}],
        reply=GroundedResponse(kind="recommend_check", text="检查指示灯并反馈", evidence_ids=["p1"]))
    store.commit_turn(owner, identifier, 0, record)
    # 新对象每次重新打开磁盘数据库；没有复用内存中的会话。
    reopened = SessionStore(folder / "sessions.sqlite")
    saved = reopened.load(owner, identifier)
    checks = {"state_restored": saved["state"] == record["after"],
              "sources_restored": reopened.load_turns(owner, identifier)[0]["passages"] == record["passages"]}
    try:
        reopened.load("different-owner", identifier)
        checks["other_owner_denied"] = False
    except KeyError:
        checks["other_owner_denied"] = True
    try:
        reopened.commit_turn(owner, identifier, 0, record)
        checks["duplicate_denied"] = False
    except SessionConflict:
        checks["duplicate_denied"] = True
    feedback = Feedback(check_result="passed", issue_status="resolved")
    before = saved["state"]
    updated = merge_feedback(before, feedback, message_id=next_turn_ids(before)[0], user_text="已恢复")
    final = finish_turn(before=before, updated=updated, user_text="已恢复", feedback=feedback,
        query="合成恢复反馈", passages=[], reply=GroundedResponse(kind="resolved", text="问题已恢复"))
    reopened.commit_turn(owner, identifier, saved["revision"], final)
    saved = reopened.load(owner, identifier)
    checks["continued_and_closed"] = saved["closed"] and len(saved["state"]["messages"]) == 4
    result = {"mode": "synthetic_no_model", "checks": checks, "passed": all(checks.values())}
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"记录目录：{folder}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
