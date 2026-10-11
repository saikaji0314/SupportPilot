# 多产品同库验证

通过 corpus.json 列举来源配置，共用 chunk_pages、retrieve_passages、with_preceding_context 和 run_turn_graph。来源配置只包含文档、产品归属、来源和切块参数，无产品专属排障分支。

当前样本为 Archer AX55 US V1 与 RE315 US V1。第二份资料来自 [RE315 US V1 官方支持页](https://www.tp-link.com/us/support/download/re315/v1/?app=t) 的[用户手册](https://www.tp-link.com/us/document/76068/)。手册共用 RE315/RE215，但这里只登记已选择的 RE315 US V1；不自动扩大型号或固件适用范围。

下载完整 PDF 保存为 `.local/research/RE315-US-V1-user-guide.pdf`；AX55 原文路径见 source.json。原文与生成物不入 Git。

```powershell
python -m supportpilot.corpus_demo --prepare
python -m supportpilot.corpus_demo --index
python -m supportpilot.corpus_demo --check
python -m supportpilot.corpus_demo --answer --case re315-check
```

prepare 仅处理本地文字；index/check 调用嵌入服务，answer 还调用聊天模型。结果保存在 `.local/generalization/<id>/result.json`。本入口不覆盖 `.local/rag/chunks.json` 或切换网页产品。新集合包含两份完整资料，集合名称变化，因此首次入库会重新嵌入两份资料；失败重跑可跳过已写片段。

五项检索样例覆盖两个产品的相同登录提问、扩展器指示灯解释、扩展器排障与未知产品。过滤和前文补块均保持 product_id。使用合成向量的真实 Chroma 隔离测试已通过；真实嵌入召回与回答质量需另验，不能将隔离通过等同于语义正确。

产品由命令行案例显式指定。本增量不验证自然语言型号识别、同一对话切换产品、多个地区/版本并存。网页已增加产品选择并使用该混合语料；切换创建新会话。`--answer` 复用图运行独立的一轮，不是新的多轮验收。
