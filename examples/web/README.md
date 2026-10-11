# 本地网页演示

网页复用资料驱动的多轮核心，展示 Archer AX55 US V1 的问答、排障、资料引用与会话摘要。

在项目根目录、已能运行 chat_demo 的 Python 环境中启动。沿用现有模型配置与 Chroma 索引，另需安装 fastapi 和 uvicorn。

```powershell
python -m uvicorn supportpilot.api:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。发送消息时才调用模型与检索服务。选择示例问题后需点击发送；引用可展开查看正文、PDF 页序与官方链接。

- 入口：supportpilot/api.py；页面：supportpilot/web/。
- 会话保存在单进程内存中；刷新页面新建会话，重启服务不会恢复旧会话。不要启用多个 workers。
- 失败会提示重试，服务端保留之前已接受的状态；同一会话不同时处理多个输入。
- 每个会话最多 12 个成功轮次；本地内存最多容纳 200 个会话。
- 结束后展示已有事实和检查摘要；建议人工协助不代表已创建工单。
- 诊断日志在 .local/web/ 下，已被 Git 忽略。

这是本地演示入口，尚未配置公网服务所需的身份与会话保护。回复的引用归属校验不能保证语义正确，仍需审阅操作前提与正文依据。

接口测试：python -m unittest discover -s tests -p test_api.py 。这些测试使用模拟核心，不调用外部模型。

网页消息经 api.Runtime → run_turn_graph → LangGraph 主链路及最多一次候选修正处理，复用既有业务函数。会话仍由 API 管理，图未启用 checkpoint。更新服务端代码后需要重启 Uvicorn；浏览器刷新不会重载 Python 进程。

网页支持在 Archer AX55 US V1 和 RE315 US V1 之间选择。切换产品会新建会话，历史不迁移。启动前按 examples/rag/GENERALIZATION.md 准备并入库混合语料，Runtime 读取 .local/corpus/chunks.json；缺少完整索引时发送消息会失败。GET /products 返回产品清单，POST /sessions 接收可选 product_id，省略时默认 AX55。产品由服务端绑定到会话，来源标题随所选产品显示。
