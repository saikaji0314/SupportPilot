# 会话持久化与提交语义

SQLite 保存业务会话，LangGraph 负责本轮执行。`SessionStore` 按服务端解析的身份读取数据，不能用浏览器自报 owner_id 代替认证。

| 表 | 内容 |
| --- | --- |
| sessions | 会话归属、产品、当前 State、版本与结束状态 |
| turns | 已接受轮次、消息与引用正文 |
| guests | 访客随机凭据哈希与身份映射 |
| accounts | 用户名与 bcrypt 密码散列 |
| account_tokens | 随机登录凭据哈希、有效期及归属 |

消息、State 与引用在同一事务提交。提交前检查会话版本、结束状态、原状态一致性及产品归属。被拒候选、过期输入或数据库写入失败不会推进已保存状态。

```powershell
python -m supportpilot.cli.persistence_demo
python -m unittest tests.test_session_store
```

合成数据运行不调用模型，结果位于 `.local/persistence/`。网页使用相同存储接口，支持跨服务重启恢复。注册/登录可迁移访客会话；退出撤销本次账号凭据。

删除会话先按归属删除数据库记录，再清理对应尝试日志；日志清理失败单独提示。独立评测快照、导出副本和备份不随会话删除。
