"""本地网页入口：内存会话、同步核心调用、服务端日志。"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from supportpilot.chat_graph import run_turn_graph
from supportpilot.chat_support import make_retriever, new_state

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).parent / "web"


class MessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SessionInput(BaseModel):
    product_id: str | None = None


@dataclass
class Session:
    state: dict
    lock: Lock = field(default_factory=Lock)
    closed: bool = False
    attempts: int = 0


class Runtime:
    """首次发送消息才加载模型/索引；浏览页面不请求外部服务。"""
    def __init__(self):
        self.lock = Lock()
        self.resources = None

    def __call__(self, **kwargs):
        with self.lock:
            if self.resources is None:
                from supportpilot.bailian import bailian
                self.resources = (bailian(), make_retriever(ROOT / ".local/corpus/chunks.json"))
        model, retrieve = self.resources
        return run_turn_graph(model, retrieve=retrieve, **kwargs)


def create_app(turn_runner=None, log_dir=None):
    app = FastAPI(title="SupportPilot", docs_url="/docs")
    config = json.loads((ROOT / "examples/rag/source.json").read_text(encoding="utf-8"))
    products = json.loads((ROOT / "examples/rag/products.json").read_text(encoding="utf-8"))
    by_product = {p["product_id"]: p for p in products}
    sessions = {}
    sessions_lock = Lock()
    runner = turn_runner or Runtime()
    logs = Path(log_dir) if log_dir else ROOT / ".local/web"
    app.state.sessions = sessions
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True, "product": "Archer AX55", "variant": "US · V1",
                "product_id": config["product_id"], "source_url": config["source_url"]}

    @app.post("/sessions", status_code=201)
    def create_session(body: SessionInput | None = None):
        product_id = body.product_id if body and body.product_id is not None else config["product_id"]
        if product_id not in by_product:
            raise HTTPException(422, "请选择已接入的产品。")
        with sessions_lock:
            if len(sessions) >= 200:
                raise HTTPException(503, "本地演示会话已满，请重启服务。")
            identifier = uuid4().hex
            sessions[identifier] = Session(new_state(product_id))
        return {"session_id": identifier, "product_id": product_id}

    @app.get("/products")
    def list_products():
        return products

    @app.post("/sessions/{session_id}/messages")
    def send_message(session_id: str, body: MessageInput):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "请输入有效文字。")
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "会话已失效，请新建会话。")
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "上一条消息仍在处理，请稍候。")
        try:
            if session.closed:
                raise HTTPException(409, "本次会话已结束，请新建会话。")
            if len(session.state["messages"]) >= 24:
                raise HTTPException(409, "本次会话已达到演示轮数上限，请新建会话。")
            session.attempts += 1
            folder = logs / session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"turn-{session.attempts:02d}.json"
            partial = {"user_text": text, "before": deepcopy(session.state),
                       "status": "running", "stage": "initializing"}

            def save(record):
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            def progress(stage, data):
                partial.update(data)
                partial["stage"] = stage
                save(partial)

            save(partial)
            try:
                record = runner(user_text=text, state=deepcopy(session.state), on_progress=progress)
            except Exception as exc:
                partial.update(status="error", error_type=type(exc).__name__)
                save(partial)
                if "timeout" in type(exc).__name__.lower():
                    raise HTTPException(504, "本轮请求超时，已保留之前的对话。请稍后重试。") from None
                raise HTTPException(502, "本轮未能完成，已保留之前的对话。请稍后重试或查看本地日志。") from None
            save(record)
            if not record["accepted"]:
                raise HTTPException(502, "本轮回复未通过校验，未作为建议展示。请重试或重新描述问题。")
            session.state = deepcopy(record["after"])
            reply = record["response"]
            session.closed = reply["kind"] in ("resolved", "handoff")
            cited = set(reply["evidence_ids"])
            product = by_product[session.state["product_id"]]
            sources = [{"id": p["id"], "title": product["name"] + " 用户手册",
                        "page": p.get("page"), "url": p["source_url"], "text": p["text"]}
                       for p in record["passages"] if p["id"] in cited]
            summary = None
            if session.closed:
                summary = {"facts": [f["text"] for f in session.state["facts"]],
                           "checks": [{"text": c["text"], "result": c["result"]}
                                      for c in session.state["checks"]]}
            return {"response": reply, "sources": sources, "closed": session.closed,
                    "status": session.state["status"], "summary": summary}
        finally:
            session.lock.release()

    return app


app = create_app()
