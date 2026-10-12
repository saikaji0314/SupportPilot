# 本地网页演示

网页复用资料驱动的多轮核心，展示 Archer AX55 US V1 和 RE315 US V1 的问答、排障、资料引用与会话摘要。

在项目根目录、已能运行 chat_demo 的 Python 环境中启动。沿用现有模型配置与 Chroma 索引，另需安装 fastapi 和 uvicorn。

```powershell
python -m uvicorn supportpilot.server.api:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。发送消息时才调用模型与检索服务。选择示例问题后需点击发送；引用可展开查看正文、PDF 页序与官方链接。

- 入口：supportpilot/server/api.py；页面：supportpilot/server/static/。
- 会话保存在 .local/web/sessions.sqlite。浏览器临时 Cookie 验证归属；刷新恢复上次会话，服务重启后可从历史列表继续。当前按单进程演示运行，不要启用多个 workers。
- 失败会提示重试，服务端保留之前已接受的状态；同一会话不同时处理多个输入。
- 每个会话最多 12 个成功轮次；每个临时身份最多创建 200 个会话。
- 结束后展示已有事实和检查摘要；建议人工协助不代表已创建工单。
- 诊断日志在 .local/web/<session_id>/attempt-<随机ID>.json 下，重启不会覆盖旧尝试记录，已被 Git 忽略。

这是本地演示入口，已实现临时身份与会话归属校验；已支持用户名/密码注册、登录与退出；公网部署尚未实现。回复的引用归属校验不能保证语义正确，仍需审阅操作前提与正文依据。

接口测试：python -m unittest discover -s tests -p test_api.py 。这些测试使用模拟核心，不调用外部模型。

网页消息经 api.Runtime → run_turn_graph → LangGraph 主链路及最多一次候选修正处理，复用既有业务函数。会话仍由 API 管理，图未启用 checkpoint。更新服务端代码后需要重启 Uvicorn；浏览器刷新不会重载 Python 进程。

网页支持在 Archer AX55 US V1 和 RE315 US V1 之间选择。切换产品会新建会话，历史不迁移。启动前按 examples/rag/GENERALIZATION.md 准备并入库混合语料，Runtime 读取 .local/corpus/chunks.json；缺少完整索引时发送消息会失败。GET /products 返回产品清单，POST /sessions 接收可选 product_id，省略时默认 AX55。产品由服务端绑定到会话，来源标题随所选产品显示。

GET /sessions 列出当前临时身份的会话，GET /sessions/{id} 恢复已接受消息、引用和结束摘要。浏览器只保存随机 HttpOnly Cookie 与上次会话 ID；上次会话 ID 不构成访问权限。Cookie 使用 SameSite=Strict，本地 HTTP 下不设置 Secure，HTTPS 下自动设置。首次生成的 Cookie 有效期为 30 天；清除 Cookie、换浏览器或到期后不保证找回临时会话。请保持使用同一地址（例如始终用 127.0.0.1）。

保存只发生在整轮图结束且 accepted=true 后。消息、引用记录与 State 在同一事务提交，数据库保存失败时不返回成功。失败候选和超时只记录到诊断日志。旧内存会话不会自动迁移成可恢复历史。


账号认证额外依赖 bcrypt，安装命令：`python -m pip install -r requirements-web-auth.txt`。密码通过 [bcrypt 官方库](https://github.com/pyca/bcrypt) 散列保存，不记录明文。用户名为 3–32 位字母、数字或下划线，大小写不区分；密码至少 8 位，UTF-8 编码最长 72 字节。

右上角可注册、登录和退出。勾选“将本浏览器的临时会话保存到账号”会迁移当前访客会话并使旧访客凭据失效；不会迁移其他账号的会话。登录后可在其他浏览器登录同一账号读取历史。退出会使本次登录凭据在服务端失效，并创建新的访客身份，账号会话继续保存。当前登录凭据有效期 30 天；账号没有邮件验证、密码找回或修改密码界面。

历史会话旁有删除按钮，确认后删除该会话的数据库消息、State、引用记录和对应诊断日志；其他会话及知识库不受影响。正在处理的会话不能删除。数据库删除成功但日志清理失败时会返回提示；清理不构成对 SQLite 空闲页、系统备份或另行导出副本的安全擦除承诺。

认证接口：GET /auth/me、POST /auth/register、POST /auth/login、POST /auth/logout。登录/注册接收 username、password 和可选 migrate_guest；凭据仅放在 HttpOnly Cookie 中，不在 localStorage 存密码或凭据。单进程认证接口按客户端地址每分钟限制 10 次尝试，反向代理、公网防护与部署另行配置。DELETE /sessions/{id} 只允许删除当前身份所属会话。

回归命令：`python -m unittest tests.test_auth tests.test_api tests.test_session_store`。测试仅使用合成密码、临时数据库与模拟模型。

## 用户界面与管理工作台

历史会话以首条已保存的用户消息生成标题，保留产品和结束状态。登录弹窗、历史卡片及滚动条使用统一页面样式。

已提供管理工作台：管理员名单、PDF 上传与切块预览、入库发布、资料概览、会话分页与逐轮轨迹、评测轮次选择和报告。启用方法、外部调用确认与范围见 [ADMIN.md](ADMIN.md)。
