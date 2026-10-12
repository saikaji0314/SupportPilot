# 会话存储基础

`supportpilot.storage.session_store.SessionStore` 提供会话创建、按所属身份读取/列出及已接受轮次提交。已接入网页/API，数据库是已接受会话状态的存储来源。

使用标准库 sqlite3，sessions 保存当前 State 和版本，turns 保存已接受记录与引用正文。两项写入处于同一事务；旧版本、已结束会话、产品变化和被拒绝的候选不能提交。owner_id 必须由可信服务端身份层提供，存储接口自身不构成浏览器认证。

```powershell
python -m supportpilot.cli.persistence_demo
python -m unittest tests.test_session_store
```

演示使用合成数据且不调用模型，数据库与结果保存在被 Git 忽略的 .local/persistence 下。网页使用服务端验证的临时 Cookie 身份，支持历史列表和跨服务重启恢复。数据库 guests 表仅保存 Cookie 的 SHA-256 哈希和 owner_id 映射，网页不能自报 owner_id 获取会话。已加入 accounts 与 account_tokens 表：bcrypt 密码散列、随机登录 Cookie 凭据哈希、有效期与服务端退出撤销。注册/登录可将访客会话归入账号。DELETE 接口校验归属后事务删除 sessions/turns，并清理对应日志。
