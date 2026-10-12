# 代码目录导航

```text
supportpilot/
├── agent/              # 资料驱动的对话与排障
├── knowledge/          # 文档读取、切块、嵌入和检索
├── evaluation/         # 轨迹、规则检查、语义评审和报告
├── storage/            # SQLite 会话与账号数据
├── auth/               # 密码哈希与校验
├── providers/          # 模型供应商客户端
├── server/             # FastAPI、管理端和前端静态文件
│   └── static/         # 用户端/管理端 HTML、CSS、JavaScript
├── cli/                # 命令行实验、回放与演示入口
├── legacy/             # 早期固定分支教学原型
├── paths.py            # 仓库根路径
├── utils.py            # 少量通用工具
└── api.py、*_demo.py等 # 旧命令兼容入口，实际实现位于上述目录
```

## 从哪里读

| 关注点 | 文件与关键函数 |
| --- | --- |
| 模型如何选回复 | `agent/grounded.py` → `propose_response` |
| 如何理解反馈并记住事实 | `agent/conversation.py` → `extract_feedback`、`merge_feedback` |
| 一轮对话怎样串起来 | `agent/chat_graph.py` → `build_turn_graph`、`run_turn_graph` |
| 哪些检查由程序执行 | `agent/chat_support.py` → `response_errors`、`finish_turn` |
| 回复被拒后怎样修正 | `agent/response_repair.py` → `repair_response` |
| 文档如何进入检索 | `knowledge/rag_support.py` → `load_source`、`index_chunks`；`knowledge/retrieval.py` → `chunk_pages`、`retrieve_passages` |
| 如何做离线评测 | `evaluation/service.py` → `run_review`；`evaluation/reviewer.py` → `evaluate_response`；`evaluation/trajectory.py` → `normalize_record`、`render_trace` |
| 会话如何保存 | `storage/session_store.py` → `SessionStore` |
| 网页与管理端 | `server/api.py` → `create_app`；`server/admin.py` → `install_admin`；`server/admin_support.py` → `AdminWorkspace` |
| 页面样式和交互 | `server/static/` |

客服主流程：用户输入 → 提取反馈 → 合并状态 → 检索 → 模型回复 → 程序校验/一次修正 → 保存并展示。`legacy/` 的固定分支原型不参与当前网页链路。

## 启动与导入

新文档采用分类后的入口：

```powershell
python -m uvicorn supportpilot.server.api:app --host 127.0.0.1 --port 8000
python -m supportpilot.cli.chat_demo --chat
python -m supportpilot.cli.corpus_demo --check
python -m supportpilot.cli.eval_demo --record examples/evaluation/synthetic-replay.json
```

旧的 `supportpilot.api:app` 和 `python -m supportpilot.<原命令模块>` 仍可使用。兼容文件只转发到新实现，不复制业务逻辑。业务代码和测试统一从新模块路径导入，例如：

```python
from supportpilot.agent.chat_graph import run_turn_graph
from supportpilot.evaluation.service import run_review
from supportpilot.storage.session_store import SessionStore
```

资源路径统一基于 `paths.ROOT`，不依赖启动目录。运行数据继续保存在被 Git 忽略的目录。
