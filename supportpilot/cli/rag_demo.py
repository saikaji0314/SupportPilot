"""RAG 分步实验：读取资料、切块、入库、检索；命令行不调用聊天模型。"""

import argparse
import json

from supportpilot.knowledge.rag_support import (
    load_source, save_local, make_embedder, open_collection, index_chunks, OUTPUT_DIR, SAMPLE_QUERY,
)
from supportpilot.knowledge.retrieval import chunk_pages, retrieve_passages
from supportpilot.providers.bailian import bailian


def prepare_chunks() -> list[dict]:
    pages, metadata, config = load_source()
    chunks = chunk_pages(pages, metadata, chunk_size=config["chunk_size"], overlap=config["overlap"])
    if not chunks:
        raise ValueError("没有生成片段，请先检查切块函数。")
    if len({item["id"] for item in chunks}) != len(chunks):
        raise ValueError("片段 ID 有重复。")
    for item in chunks:
        if not item["text"].strip():
            raise ValueError("片段正文为空。")
        for key in ("document_id", "product_id", "source_url", "source_revision", "page", "section"):
            if key not in item["metadata"]:
                raise ValueError(f"片段缺少元数据：{key}")
    save_local("chunks.json", chunks)
    return chunks


def query_index(query: str, product_id: str | None = None) -> list[dict]:
    # 用已保存的片段决定集合名称；仅查已有索引，不在查询时偷偷入库。
    chunks = json.loads((OUTPUT_DIR / "chunks.json").read_text(encoding="utf-8"))
    _, metadata, _ = load_source()
    embedder = make_embedder()
    collection = open_collection(chunks, embedder)
    if collection.count() == 0:
        raise ValueError("集合为空，请先执行 --index；更换嵌入模型也需要重新入库。")
    passages = retrieve_passages(collection, embedder, query, product_id or metadata["product_id"])
    save_local("retrieved.json", {"query": query, "passages": passages})
    return passages


def answer_with_rag(model, user_text: str, state: dict):
    # 只在用户显式调用时才调用聊天模型。
    from supportpilot.agent.grounded import propose_response

    passages = query_index(user_text, state["product_id"])
    reply = propose_response(model, user_text=user_text, state=state, passages=passages)
    available = {item["id"] for item in passages}
    errors = []
    if reply.kind in ("answer", "recommend_check") and not reply.evidence_ids:
        errors.append("回复缺少引用。")
    if set(reply.evidence_ids) - available:
        errors.append("回复包含本轮检索资料之外的引用。")
    save_local("reply.json", {"response": reply.model_dump(), "errors": errors})
    if errors:
        raise ValueError("；".join(errors))
    return reply


def main() -> None:
    parser = argparse.ArgumentParser(description="分步 RAG 实验，默认只检查来源")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--index", action="store_true")
    group.add_argument("--query")
    parser.add_argument("--product-id")
    parser.add_argument("--answer-rag", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        chunks = prepare_chunks()
        print(f"生成 {len(chunks)} 个片段，正文保存在 .local/rag/chunks.json。")
    elif args.index:
        chunks = json.loads((OUTPUT_DIR / "chunks.json").read_text(encoding="utf-8"))
        embedder = make_embedder()
        collection = open_collection(chunks, embedder)
        index_chunks(collection, embedder, chunks)
        print(f"入库完成，集合记录数：{collection.count()}。", flush=True)
    elif args.query is not None:
        print(json.dumps(query_index(args.query, args.product_id), ensure_ascii=False, indent=2))
    elif args.answer_rag:
        for query in json.loads(SAMPLE_QUERY.read_text(encoding="utf-8")):
            reply = answer_with_rag(
                bailian(),
                query["text"],
                {"product_id": "tp-link-archer-ax55-us-v1", "facts": [], "checks": [], "pending": None},
            )
            print(f"查询：{query['id']} {query['text']}\n回复：{reply.model_dump_json()}")
    else:
        pages, metadata, _ = load_source()
        print(json.dumps({"source": metadata, "pages": len(pages),
                          "characters": sum(len(item["text"]) for item in pages),
                          "empty_pages": [item["page"] for item in pages if not item["text"].strip()]},
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
