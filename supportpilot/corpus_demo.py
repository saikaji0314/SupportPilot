"""多文档同库实验；复用切块、产品过滤和图，不修改网页当前索引。"""
import argparse
from collections import Counter
import json
from pathlib import Path
from uuid import uuid4

from supportpilot.rag_support import ROOT, load_source, make_embedder, open_collection, index_chunks
from supportpilot.retrieval import chunk_pages
from supportpilot.chat_support import make_retriever, new_state

MANIFEST = ROOT / "examples/rag/corpus.json"
CHUNKS = ROOT / ".local/corpus/chunks.json"
CASES = ROOT / "examples/rag/generalization-cases.json"


def prepare_corpus(manifest=MANIFEST):
    """读取清单，逐文档复用切块；同库内文档 ID 必须唯一。"""
    config = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))
    chunks, documents = [], set()
    if not config["sources"]:
        raise ValueError("资料清单为空")
    for source in config["sources"]:
        pages, metadata, settings = load_source(ROOT / source)
        if metadata["document_id"] in documents:
            raise ValueError("清单包含重复 document_id")
        documents.add(metadata["document_id"])
        part = chunk_pages(pages, metadata, chunk_size=settings["chunk_size"], overlap=settings["overlap"])
        if not part:
            raise ValueError("文档未生成片段")
        chunks.extend(part)
    if len({c["id"] for c in chunks}) != len(chunks):
        raise ValueError("片段 ID 冲突")
    return chunks


def check_isolation(passages, product_id, known_products):
    if any(p["product_ids"] != [product_id] for p in passages):
        raise ValueError("检索混入其他产品")
    if product_id not in known_products and passages:
        raise ValueError("未知产品应无结果")
    if product_id in known_products and not passages:
        raise ValueError("已入库产品未召回任何片段")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true", help="读本地原文切块，不调用模型")
    group.add_argument("--index", action="store_true", help="调用嵌入服务入库")
    group.add_argument("--check", action="store_true", help="运行同库产品隔离查询，调用嵌入服务")
    group.add_argument("--answer", action="store_true", help="单个案例运行既有图，调用聊天和嵌入服务")
    parser.add_argument("--case", help="--answer 必须指定的案例 ID")
    args = parser.parse_args()
    if args.answer and not args.case:
        parser.error("--answer 需要 --case")
    if args.prepare:
        chunks = prepare_corpus()
        CHUNKS.parent.mkdir(parents=True, exist_ok=True)
        CHUNKS.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(dict(Counter(c["metadata"]["product_id"] for c in chunks)), ensure_ascii=False))
        return
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    if args.index:
        embedder = make_embedder()
        collection = open_collection(chunks, embedder)
        index_chunks(collection, embedder, chunks)
        print(f"集合 {collection.name}，记录数 {collection.count()}")
        return
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.answer:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error("未知案例 ID")
    folder = ROOT / ".local/generalization" / uuid4().hex[:12]
    folder.mkdir(parents=True)
    result = {"mode": "answer" if args.answer else "retrieval", "status": "running", "cases": []}
    def save():
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"记录目录：{folder}", flush=True)
    save()
    try:
        retrieve = make_retriever(CHUNKS)
        products = {c["metadata"]["product_id"] for c in chunks}
        for case in cases:
            item = {"case": case, "status": "running"}
            result["cases"].append(item)
            save()
            if args.answer:
                from supportpilot.bailian import bailian
                from supportpilot.chat_graph import run_turn_graph
                def progress(stage, data):
                    item.update(stage=stage, partial={**item.get("partial", {}), **data})
                    save()
                record = run_turn_graph(bailian(), user_text=case["text"],
                    state=new_state(case["product_id"]), retrieve=retrieve, on_progress=progress)
                item["record"] = record
                passages = record["passages"]
            else:
                passages = retrieve(case["text"], product_id=case["product_id"])
                item["passages"] = passages
            check_isolation(passages, case["product_id"], products)
            item.update(status="completed", isolation_passed=True)
            save()
        result["status"] = "completed"
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__)
    save()
    print(json.dumps({"status": result["status"], "error_type": result.get("error_type"),
        "cases": [{"id": x["case"]["id"], "status": x["status"],
                   "isolation_passed": x.get("isolation_passed"),
                   "accepted": x.get("record", {}).get("accepted")}
                  for x in result["cases"]]}, ensure_ascii=False, indent=2))
    print("隔离通过只证明产品归属；召回相关性、正文支持和操作前提仍需人工查看。")
    if result["status"] == "error":
        parser.exit(1)


if __name__ == "__main__":
    main()
