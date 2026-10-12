"""连续对话外围：初始化、编号、有限校验、记录回复、连接已有索引。"""

from copy import deepcopy
import json

from supportpilot.grounded import GroundedResponse


def new_state(product_id: str) -> dict:
    return {"product_id": product_id, "facts": [], "checks": [], "pending": None,
            "status": "ongoing", "messages": []}


def next_turn_ids(state: dict) -> tuple[str, str, str]:
    number = 1 + sum(m["role"] == "user" for m in state["messages"])
    return f"u{number}", f"a{number}", f"c{number}"


def response_errors(reply, state: dict, passages: list[dict]) -> list[str]:
    """只查引用归属、明确产品归属、完全重复和恢复状态，不保证语义支持。"""
    by_id = {p["id"]: p for p in passages}
    errors = []
    if reply.kind in ("answer", "recommend_check") and not reply.evidence_ids:
        errors.append("产品问答或检查建议缺少引用")
    for evidence_id in reply.evidence_ids:
        if evidence_id not in by_id:
            errors.append(f"引用不属于本轮检索：{evidence_id}")
        elif state["product_id"] not in by_id[evidence_id].get("product_ids", []):
            errors.append(f"引用资料未声明当前产品：{evidence_id}")
    if reply.kind == "recommend_check":
        normalized = " ".join(reply.text.split())
        if any(" ".join(c["text"].split()) == normalized for c in state["checks"]):
            errors.append("检查文字与已有记录完全重复")
        if state["status"] == "resolved":
            errors.append("用户已报告恢复，不应继续要求检查")
    if reply.kind == "resolved" and state["status"] != "resolved":
        errors.append("本轮记录没有确认问题恢复")
    return errors


def finish_turn(*, before: dict, updated: dict, user_text: str, feedback,
                query: str, passages: list[dict], reply) -> dict:
    """校验候选回复；通过后记录消息与检查，失败保留原状态及诊断材料。"""
    reply = GroundedResponse.model_validate(reply)
    errors = response_errors(reply, updated, passages)
    after = deepcopy(before if errors else updated)
    user_id, assistant_id, check_id = next_turn_ids(before)
    if not errors:
        after["messages"].extend([
            {"id": user_id, "role": "user", "text": user_text},
            {"id": assistant_id, "role": "assistant", **reply.model_dump()},
        ])
        if reply.kind == "recommend_check":
            after["checks"].append({"id": check_id, "text": reply.text,
                                    "evidence_ids": list(reply.evidence_ids),
                                    "result": "unknown", "feedback": None,
                                    "source_message_id": None})
            # 旧的未确认检查保留 unknown；不能因提出新检查而改成失败。
            after["pending"] = check_id
        elif reply.kind in ("resolved", "handoff"):
            after["pending"] = None
    return {"accepted": not errors, "user_text": user_text,
            "before": deepcopy(before), "feedback": feedback.model_dump(),
            "updated": deepcopy(updated), "query": query, "passages": deepcopy(passages),
            "response": reply.model_dump(), "errors": errors, "after": after}


def make_retriever(chunks_path=None):
    """显式开始聊天时创建一次客户端，复用已有索引；不入库。"""
    from supportpilot.rag_support import OUTPUT_DIR, make_embedder, open_collection
    from supportpilot.retrieval import retrieve_passages

    from pathlib import Path
    chunks = json.loads((Path(chunks_path) if chunks_path else OUTPUT_DIR / "chunks.json").read_text(encoding="utf-8"))
    embedder = make_embedder()
    collection = open_collection(chunks, embedder)
    if not collection.count():
        raise ValueError("当前集合为空，请先使用 rag_demo --index 入库")
    if chunks_path is not None and collection.count() != len(chunks):
        raise ValueError("多文档集合尚未完整入库，请重新运行 corpus_demo --index")

    return retriever_for_collection(collection, embedder, chunks)


def retriever_for_collection(collection, embedder, chunks):
    from supportpilot.retrieval import retrieve_passages

    def retrieve(query: str, product_id: str):
        passages = retrieve_passages(collection, embedder, query, product_id)
        return with_preceding_context(passages, chunks, product_id)

    return retrieve


def with_preceding_context(passages: list[dict], chunks: list[dict], product_id: str) -> list[dict]:
    """每个命中补同文档的前一块，保留原 ID，减少前提被截断的情况。"""
    groups = {}
    for chunk in chunks:
        meta = chunk["metadata"]
        if meta["product_id"] == product_id:
            groups.setdefault(meta["document_id"], []).append(chunk)
    previous = {}
    for group in groups.values():
        group.sort(key=lambda c: (c["metadata"]["page"], c["metadata"]["section"]))
        for index in range(1, len(group)):
            previous[group[index]["id"]] = group[index - 1]
    hits = {p["id"]: p for p in passages}
    result, seen = [], set()
    for passage in passages:
        context = previous.get(passage["id"])
        candidates = []
        if context:
            meta = context["metadata"]
            candidates.append(hits.get(context["id"], {
                "id": context["id"], "text": context["text"],
                "document_id": meta["document_id"], "product_ids": [meta["product_id"]],
                "source_url": meta["source_url"], "page": meta["page"], "section": meta["section"],
                "distance": None, "retrieval_role": "preceding_context",
            }))
        candidates.append(passage)
        for candidate in candidates:
            if candidate["id"] not in seen:
                result.append(deepcopy(candidate))
                seen.add(candidate["id"])
    return result
