"""连续 RAG 对话的两个核心接口；由已有反馈、检索和回复函数组成。"""

from copy import deepcopy

from supportpilot.conversation import extract_feedback, merge_feedback
from supportpilot.grounded import propose_response
from supportpilot.chat_support import finish_turn, next_turn_ids


def build_retrieval_query(*, user_text: str, state: dict) -> str:
    """本轮话 + 当前事实 + 检查/追问上下文 → 非空检索文本。

    第一版用普通字符串拼接，不调用模型，不选片段或排障操作。
    使用合并后的事实；不要把第一轮旧事实无条件复制回来。
    见 .local/下一阶段-连续对话.md 的输入输出示例。
    """
    parts = [
        f"当前问题：{user_text}",
        f"已知事实：{"\n".join([fact["text"] for fact in state["facts"]])}",
    ]

    recent_check = None
    if state["pending"]:
        for check in state["checks"]:
            if check["id"] == state["pending"]:
                recent_check = check
                break
    else:
        if state["checks"]:
            recent_check = state["checks"][-1]
    if recent_check:
        parts.append(
            f"最近检查：{recent_check['text']}；"
            f"结果：{recent_check['result']}；"
            f"反馈：{recent_check['feedback']}"
        )

    last_assistant = next(
        (
            message
            for message in reversed(state["messages"])
            if message["role"] == "assistant"
        ),
        None,
    )
    if last_assistant and last_assistant["kind"] == "ask_user":
        parts.append(f"上一轮追问：{last_assistant['text']}")

    return "\n".join(parts)


def run_turn(model, *, user_text: str, state: dict, retrieve, on_progress=None) -> dict:
    """完成一轮，返回 finish_turn 生成的记录，不修改旧 State。

    retrieve(query, product_id) -> list[dict] 由外围提供。
    顺序：复制旧状态 → 编号 → 提取反馈 → 合并 → 构建查询 → 检索
          → propose_response → finish_turn。
    不在此读取密钥、终端输入、写日志，也不按产品条件选择动作。
    """
    before = deepcopy(state)
    user_id, _, _ = next_turn_ids(before)

    def progress(stage, **data):
        if on_progress is not None:
            on_progress(stage, data)

    progress("extract_feedback", before=before, user_text=user_text)
    feedback = extract_feedback(model, user_text=user_text, state=before)
    progress("merge_feedback", feedback=feedback.model_dump())
    updated = merge_feedback(before, feedback, message_id=user_id, user_text=user_text)
    progress("build_query", updated=updated)
    query = build_retrieval_query(user_text=user_text, state=updated)
    progress("retrieve", query=query)
    passages = retrieve(query, product_id=updated["product_id"])
    progress("propose_response", passages=passages)
    reply = propose_response(model, user_text=user_text, state=updated, passages=passages)
    progress("finish_turn", response=reply.model_dump())

    return finish_turn(before=before, updated=updated, user_text=user_text,
                       feedback=feedback, query=query, passages=passages, reply=reply)
