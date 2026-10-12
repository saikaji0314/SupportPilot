# 会话存储基础

`supportpilot.session_store.SessionStore` 提供会话创建、按所属身份读取/列出及已接受轮次提交。当前独立于网页，网页仍使用内存会话。

使用标准库 sqlite3，sessions 保存当前 State 和版本，turns 保存已接受记录与引用正文。两项写入处于同一事务；旧版本、已结束会话、产品变化和被拒绝的候选不能提交。owner_id 必须由可信服务端身份层提供，存储接口自身不构成浏览器认证。

```powershell
python -m supportpilot.persistence_demo
python -m unittest tests.test_session_store
```

演示使用合成数据且不调用模型，数据库与结果保存在被 Git 忽略的 .local/persistence 下。网页 Cookie 身份、历史列表和跨服务重启恢复尚待接入。
