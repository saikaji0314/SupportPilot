"""已有完整轮/回复回放的本地只读适配；不请求任何模型。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def normalize_record(record: dict, *, record_id: str) -> dict:
    is_replay = isinstance(record.get("input"), dict)
    if is_replay:
        payload = deepcopy(record["input"])
        scope = "response_replay"
    elif "user_text" in record and ("before" in record or "updated" in record):
        payload = {"user_text": record["user_text"],
                   "state": deepcopy(record.get("updated")),
                   "passages": deepcopy(record.get("passages"))}
        scope = "turn"
    else:
        raise ValueError("仅支持 chat/web 完整或中断轮记录，以及 response_replay 结果")
    response = deepcopy(record.get("response"))  # 不能拿 original_response 充当本次输出
    missing = [k for k in ("user_text", "state", "passages") if payload.get(k) is None]
    if not isinstance(response, dict):
        missing.append("response")
    status = record.get("status", "completed" if "accepted" in record else "unknown")
    return {"schema_version": 1, "record_id": record_id, "scope": scope,
            "execution_status": status, "accepted": record.get("accepted"),
            "error_type": record.get("error_type"), "stage": record.get("stage"),
            "payload": payload, "response": response,
            "recorded_errors": deepcopy(record.get("errors")),
            "missing": missing, "reviewable": not missing and status == "completed",
            "snapshots": {k: deepcopy(record.get(k)) for k in
                          ("before", "feedback", "updated", "query", "after")},
            "provenance": {"generation_model": "unknown", "generation_version": "unknown",
                           "duration_ms": None, "token_usage": None}}


def load_trace(path: Path) -> dict:
    raw = path.read_bytes()
    trace = normalize_record(json.loads(raw.decode("utf-8-sig")), record_id=path.stem)
    trace["source_record"] = str(path.resolve())
    trace["source_sha256"] = sha256(raw).hexdigest()
    return trace


def render_trace(trace: dict, evaluation: dict) -> str:
    """输出固定围栏，避免原始文字里的反引号提前结束代码块。"""
    def block(value):
        content = json.dumps(value, ensure_ascii=False, indent=2)
        # 任意连续反引号都要覆盖，包括正文里的 Markdown。
        import re
        fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", content)), default=3))
        return f"{fence}json\n{content}\n{fence}\n"
    parts = ["# 单轮轨迹与评审\n", "仅展示记录与评审；程序检查通过不等于语义正确。\n"]
    for title, value in [("范围与运行状态", {k: trace[k] for k in
                         ("scope", "execution_status", "accepted", "missing", "provenance")}),
                         ("历史及过程快照", trace["snapshots"]),
                         ("评审输入（合并后 State 与正文）", trace["payload"]),
                         ("候选回复", trace["response"]), ("评审结果", evaluation)]:
        parts.extend([f"## {title}\n", block(value)])
    return "\n".join(parts)
