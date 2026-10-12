"""外围接线：读取真实文档、嵌入客户端和入库；不选择排障动作。"""

from supportpilot.paths import ROOT
import hashlib
import json
from pathlib import Path
import re


SOURCE_CONFIG = ROOT / "examples/rag/source.json"
SAMPLE_QUERY = ROOT / "examples/rag/queries.json"
OUTPUT_DIR = ROOT / ".local/rag"
INDEX_DIR = ROOT / "data/indexes/grounded"


def load_source(config_path: Path = SOURCE_CONFIG) -> tuple[list[dict], dict, dict]:
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    path = ROOT / config["source_path"]
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        pages = [{"page": i, "text": page.extract_text() or ""}
                 for i, page in enumerate(PdfReader(path).pages, start=1)]
    else:
        text = path.read_text(encoding="utf-8-sig")
        marked = list(re.finditer(r"^\[PDF page (\d+)\]\s*\n", text, re.MULTILINE))
        if marked:
            pages = [{"page": int(m.group(1)),
                      "text": text[m.end():marked[i + 1].start() if i + 1 < len(marked) else len(text)]}
                     for i, m in enumerate(marked)]
        else:
            pages = [{"page": 1, "text": text}]
    if not any(page["text"].strip() for page in pages):
        raise ValueError("资料未提取到文字；扫描件或提取异常请先处理，不建立空索引。")
    metadata = {key: config[key] for key in ("document_id", "product_id", "source_url", "scope_note")}
    metadata["source_revision"] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return pages, metadata, config


def save_local(name: str, payload) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class TextEmbedder:
    """OpenAI 兼容嵌入接口；批量最多 10 条，不使用聊天模型做向量。"""

    def __init__(self, client, model: str, dimensions: int = 1024):
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), 10):
            batch = texts[start:start + 10]
            result = self.client.embeddings.create(
                model=self.model, input=batch, dimensions=self.dimensions,
            )
            data = sorted(result.data, key=lambda item: item.index)
            if len(data) != len(batch):
                raise ValueError("嵌入返回条数不匹配，停止入库。")
            part = [item.embedding for item in data]
            if any(len(vector) != self.dimensions for vector in part):
                raise ValueError("嵌入维度与配置不匹配，停止入库。")
            vectors.extend(part)
        return vectors


def make_embedder() -> TextEmbedder:
    # 仅显式入库/查询时加载配置；inspect 和 prepare 不触发。
    import os
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    key = os.getenv("SUPPORTPILOT_EMBEDDING_API_KEY") or os.getenv("API_KEY")
    base_url = os.getenv("SUPPORTPILOT_EMBEDDING_BASE_URL")
    if not key or not base_url:
        raise ValueError("请在本地配置嵌入服务密钥与 SUPPORTPILOT_EMBEDDING_BASE_URL；使用与账号地域匹配的地址。")
    model = os.getenv("SUPPORTPILOT_EMBEDDING_MODEL", "text-embedding-v4")
    return TextEmbedder(OpenAI(api_key=key, base_url=base_url, timeout=60, max_retries=1), model)


def collection_name(chunks: list[dict], embedder: TextEmbedder) -> str:
    # 语料、切块或嵌入配置变化时换集合，不混用旧向量，不删除旧索引。
    payload = json.dumps({"chunks": chunks, "model": embedder.model,
                          "dimensions": embedder.dimensions}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"supportpilot_{digest}"


def open_collection(chunks: list[dict], embedder: TextEmbedder):
    import chromadb

    client = chromadb.PersistentClient(path=str(INDEX_DIR))
    return client.get_or_create_collection(
        name=collection_name(chunks, embedder), embedding_function=None,
    )


def index_chunks(collection, embedder, chunks: list[dict]) -> None:
    # 集合名称包含语料和模型配置的哈希，相同集合中的已有 ID 可以直接复用。
    pending = []
    for start in range(0, len(chunks), 100):
        batch = chunks[start:start + 100]
        existing = set(collection.get(ids=[item["id"] for item in batch], include=[])["ids"])
        pending.extend(item for item in batch if item["id"] not in existing)
    print(f"共 {len(chunks)} 条，已入库 {len(chunks) - len(pending)} 条，待入库 {len(pending)} 条。", flush=True)
    total_batches = (len(pending) + 9) // 10
    for start in range(0, len(pending), 10):
        batch = pending[start:start + 10]
        label = f"批次 {start // 10 + 1}/{total_batches}（{len(batch)} 条）"
        stage = "请求嵌入"
        try:
            vectors = embedder([item["text"] for item in batch])
            stage = "写入 Chroma"
            collection.upsert(
                ids=[item["id"] for item in batch],
                documents=[item["text"] for item in batch],
                metadatas=[item["metadata"] for item in batch],
                embeddings=vectors,
            )
        except Exception as exc:
            # 不输出服务返回正文、密钥或文档正文。
            status = getattr(exc, "status_code", None)
            detail = f"{type(exc).__name__}" + (f"，HTTP {status}" if status is not None else "")
            raise RuntimeError(f"{label}：{stage}失败（{detail}）。重跑 --index 会跳过已入库片段。") from None
        print(f"{label}：写入完成，本次已写入 {start + len(batch)}/{len(pending)} 条。", flush=True)
