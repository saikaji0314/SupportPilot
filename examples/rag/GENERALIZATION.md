# 多产品语料与检索隔离

`corpus.json` 列举资料来源配置，Archer AX55 US V1 与 RE315 US V1 共用切块、产品过滤、上下文补块和图执行逻辑。产品差异来自资料与元数据。

## 准备与运行

获取 [AX55 手册](https://www.tp-link.com/us/document/79681/) 和 [RE315 手册](https://www.tp-link.com/us/document/76068/)，将两个来源 JSON 的 `source_path` 指向本地文件。AX55 默认指向提取 TXT，首次复现需改为下载的 PDF；RE315 默认路径为 `.local/research/RE315-US-V1-user-guide.pdf`。

RE315 资料由 [美国站 V1 支持入口](https://www.tp-link.com/us/support/download/re315/v1/?app=t) 提供。手册共用 RE315/RE215，示例只登记 RE315 US V1，不扩大到其他型号或固件。

```powershell
python -m supportpilot.cli.corpus_demo --prepare
python -m supportpilot.cli.corpus_demo --index
python -m supportpilot.cli.corpus_demo --check
python -m supportpilot.cli.corpus_demo --answer --case re315-check
```

prepare 生成 `.local/corpus/chunks.json`，不调用外部服务。index/check 请求嵌入；answer 还调用聊天模型。检查与回答记录位于 `.local/generalization/<id>/result.json`。

`generalization-cases.json` 覆盖跨产品的相同登录问题、信号灯说明、排障与未知产品。产品过滤与前文补块均保持归属。隔离检查核对返回片段的产品信息，正文相关性与操作依据需要另外评估。

CLI 构建基线混合语料；首次启动且没有管理端发布版本时，网页读取该基线。管理端发布后，网页使用版本指针，重新运行此 CLI 不覆盖已发布版本。语料或嵌入配置变化会换集合，可能重新嵌入完整语料。
