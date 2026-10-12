# 运行与复现入口

这些入口用于单独观察检索、反馈处理、图执行和评测行为。案例与参考片段是公开可复现的数据夹具；原始文档、真实会话和生成报告保存在运行环境中。

| 入口 | 输入 | 外部调用 |
| --- | --- | --- |
| [grounded](grounded/README.md) | 固定正文与合成问题 | 聊天模型 |
| [rag](rag/README.md) | 官方文档与产品元数据 | inspect/prepare 无；index/query 使用嵌入 |
| [多产品语料](rag/GENERALIZATION.md) | 产品来源清单 | check 使用嵌入；answer 还使用聊天模型 |
| [conversation](conversation/README.md) | 用户反馈与 State | 预览/merge-only 无；run 使用聊天模型 |
| [graph](graph/README.md) | 保存的完整轮记录 | 默认无；run 使用聊天与嵌入 |
| [evaluation](evaluation/README.md) | 保存的候选与输入快照 | 默认无；judge 使用评审模型 |
| [web](web/README.md) | 产品资料与用户对话 | 发送消息使用聊天与嵌入 |

安装和配置见 [仓库首页](../README.md)。模型调用与离线数据回放的结果分别解释，不将合成夹具视为设备排障成绩。
