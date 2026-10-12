# 单文档 RAG

从官方文档提取页面文字，经自动切块、嵌入与 Chroma 检索，为模型提供可引用正文。适合定位文本提取、召回和正文利用各环节的问题。

## 准备资料

从 [AX55 用户手册](https://www.tp-link.com/us/document/79681/) 获取 PDF，保存到运行环境，并将 `source.json` 的 `source_path` 指向它，例如 `.local/research/AX55-US-V1-user-guide.pdf`。默认配置指向提取后的 TXT，该文件不随仓库分发。路径相对于仓库根目录；元数据包含文档 ID、产品 ID、来源、范围与切块参数。

```powershell
python -m supportpilot.cli.rag_demo --inspect
python -m supportpilot.cli.rag_demo --prepare
python -m supportpilot.cli.rag_demo --index
python -m supportpilot.cli.rag_demo --query "如何打开路由器管理页面？"
python -m supportpilot.cli.rag_demo --answer-rag
```

| 参数 | 行为 |
| --- | --- |
| inspect | 本地提取与页面统计 |
| prepare | 自动切块，保存 `.local/rag/chunks.json` |
| index | 请求嵌入并写入集合；相同集合的已有 ID 跳过 |
| query | 嵌入查询、按产品过滤并返回片段 |
| answer-rag | 检索并调用模型回答 `queries.json` 中的问题 |

inspect/prepare 不调用外部服务；其余命令需配置嵌入，answer-rag 还需要聊天模型。原文与生成物均在 Git 忽略目录。网页使用多产品或已发布语料，单文档 CLI 不改变网页在线版本。

核心接口：`chunk_pages`、`retrieve_passages` 与 `index_chunks`。多产品接入见 [GENERALIZATION.md](GENERALIZATION.md)。
