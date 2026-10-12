# 真实文档 RAG 实验入口

本实验使用 [AX55 型号手册](https://www.tp-link.com/us/document/79681/) 的完整提取文本，经过自动切块、嵌入和 Chroma 检索，交给已有模型回复接口。不读取 grounded 的手写 passages 作为知识库。

资料原文位于被忽略的 .local/research，公开仓库只保存来源配置和合成查询。使用者自行取得官方 PDF，可以将 source.json 的 source_path 改为本地 PDF 路径；PDF 文本提取需要 pypdf。当前已有按页提取的 TXT，可直接使用。

核心 chunk_pages 和 retrieve_passages 已实现。真实手册已完成入库，并验证一个中文登录问题能够召回英文正文并生成有引用回答。另已运行端口用途与无法上网查询：排障案例召回相关正文，端口用途案例仍未正确回答，需检查召回与资料利用，当前不是多轮排障验收。

```powershell
python -m supportpilot.cli.rag_demo --inspect
python -m supportpilot.cli.rag_demo --prepare
python -m supportpilot.cli.rag_demo --index
python -m supportpilot.cli.rag_demo --query "如何打开路由器管理页面？"
```

inspect 不调用模型；prepare 不调用模型；index、query 需要配置嵌入服务并可能发起请求。重复 index 会跳过已入库片段。当前新增 --answer-rag，会检索并调用聊天模型回答 queries.json 中的三条示例；answer_with_rag 也可由调用方传入已配置模型。

切块原文、索引、召回正文与模型结果均保存在 Git 忽略路径。产品归属来自 source.json，增加产品资料使用同类配置与函数。
