# Web 产品支持界面

用户端提供产品选择、售后问答、多轮排障、来源展开和结束摘要，并支持临时身份、账号登录与历史会话恢复。

```powershell
python -m uvicorn supportpilot.server.api:app --host 127.0.0.1 --port 8000
```

安装与配置见 [仓库首页](../../README.md)，访问 http://127.0.0.1:8000 。发送消息前通过 [管理端](ADMIN.md) 发布产品资料，或使用 [混合语料 CLI](../rag/GENERALIZATION.md) 准备基线。网页浏览不调用模型；消息处理调用聊天和嵌入服务。

## 会话体验

产品绑定到会话，切换产品创建新会话。历史标题来自首条已保存消息，点击可恢复消息、引用和摘要。访客凭据由本浏览器的 HttpOnly Cookie 保存；注册或登录时可将访客会话归入账号，登录同一账号可跨浏览器读取历史。

用户名为 3–32 位字母、数字或下划线，大小写不区分；密码至少 8 位且 UTF-8 最长 72 字节，使用 bcrypt 散列。退出撤销本次登录凭据。删除仅作用于当前身份的会话，已独立选入评测的快照继续保留。

每个会话最多 12 个成功轮次，每个身份最多 200 个会话。失败候选不提交；页面保留重试入口。handoff 展示沟通摘要，真实工单提交未接入。

## 接口

| 接口 | 用途 |
| --- | --- |
| GET /products | 产品目录 |
| POST /sessions | 创建指定产品会话 |
| GET /sessions、GET /sessions/{id} | 历史列表与恢复 |
| POST /sessions/{id}/messages | 执行一轮图处理 |
| DELETE /sessions/{id} | 删除所属会话 |
| GET /auth/me、POST /auth/register、login、logout | 账号认证 |

服务使用单进程。业务数据位于 `.local/web/sessions.sqlite`，尝试日志位于 `.local/web/<session_id>/`。Cookie 是访问凭据，客户端保存的会话 ID 不构成权限。详细事务语义见 [PERSISTENCE.md](PERSISTENCE.md)。
