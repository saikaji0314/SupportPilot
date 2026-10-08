"""RAG 的两个核心接口：自动切块与按产品检索。"""


def chunk_pages(
    pages: list[dict],
    metadata: dict,
    *,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> list[dict]:
    """把全部页面自动切成 {id, text, metadata} 列表。

    pages 中每项为 {page: 1, text: ...}，page 是 PDF 阅读器的页序。
    metadata 提供 document_id、product_id、source_url、source_revision。
    片段 metadata 另补 page 和 section（例如 PDF page 1）。
    ID 包含文档、资料版本、页码与片段序号，同输入重复运行保持一致。
    不手工挑 FAQ，不根据症状选择只入库哪个章节。
    """
    if not chunk_size > 0:
        raise ValueError("chunk_size 必须大于 0")
    if not 0 <= overlap < chunk_size:
        raise ValueError(f"overlap 必须在 0 到 chunk_size 之间")
    
    chunks = []
    for page in pages:
        if not page["text"].strip():
            continue
        page_text = page["text"].strip()
        for section, start in enumerate(range(0, len(page_text), chunk_size - overlap)):
            end = min(start + chunk_size, len(page_text))
            text = page_text[start:end]
            if not text.strip():
                continue
            chunks.append({
                "id": f"{metadata['document_id']}-{metadata['source_revision']}-p{page['page']}-s{section}", 
                "text": text, 
                "metadata": {**metadata, "page": page["page"], "section": section}
            })
            if end == len(page_text):
                break
    return chunks


def retrieve_passages(
    collection,
    embedder,
    query: str,
    product_id: str,
    *,
    top_k: int = 3,
) -> list[dict]:
    """将 Chroma 查询结果转换为 propose_response 所需 passages。

    embedder([query]) 返回一组向量；用 query_embeddings 传给 collection.query。
    必须按 product_id 过滤；没有匹配产品返回 []，不能移除过滤重试。
    输出项至少包含 id、text、source_url、document_id、section、product_ids。
    另带 page 与 distance，方便检查召回。不要根据固定关键词直接指定片段。
    """
    if not query.strip():
        raise ValueError("query 不能为空")
    if not top_k > 0:
        raise ValueError("top_k 必须大于 0")
    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=embedder([query]),
        n_results=min(top_k, collection.count()),
        where={"product_id": product_id},
        include=["documents", "metadatas", "distances"],
    )

    return [{
        "id": results['ids'][0][i], 
        "text": results["documents"][0][i],
        "document_id": results["metadatas"][0][i]["document_id"],
        "product_ids": [results["metadatas"][0][i]["product_id"]],
        "source_url": results["metadatas"][0][i]["source_url"],
        "page": results["metadatas"][0][i]["page"],
        "section": results["metadatas"][0][i]["section"],
        "distance": results["distances"][0][i]
    } for i in range(len(results["ids"][0]))]
