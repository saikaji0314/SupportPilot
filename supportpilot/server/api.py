"""本地网页入口：临时 Cookie 身份、SQLite 会话和运行日志。"""
from supportpilot.paths import ROOT
from copy import deepcopy
import json
import re
import shutil
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from supportpilot.agent.chat_graph import run_turn_graph
from supportpilot.agent.chat_support import make_retriever
from supportpilot.storage.session_store import SessionStore, SessionConflict

WEB = Path(__file__).parent / "static"


class MessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class SessionInput(BaseModel):
    product_id: str | None = None


class Credentials(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,32}$")
    password: str = Field(min_length=8, max_length=72)
    migrate_guest: bool = True

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码 UTF-8 编码长度不能超过 72 字节")
        return value


class Runtime:
    """首次发送消息才加载模型/索引；浏览页面不请求外部服务。"""
    def __init__(self, chunks_path=None):
        self.lock = Lock()
        self.resources = None
        self.chunks_path = chunks_path or ROOT / ".local/corpus/chunks.json"

    def publish_corpus(self, path, retrieve, commit):
        with self.lock:
            commit()
            self.chunks_path = path
            if self.resources is not None:
                self.resources = (self.resources[0], retrieve)

    def __call__(self, **kwargs):
        with self.lock:
            if self.resources is None:
                from supportpilot.providers.bailian import bailian
                self.resources = (bailian(), make_retriever(self.chunks_path))
            model, retrieve = self.resources
        return run_turn_graph(model, retrieve=retrieve, **kwargs)


def create_app(turn_runner=None, log_dir=None, db_path=None, admin_usernames=None,
               admin_workspace=None, corpus_indexer=None, judge_factory=None):
    app = FastAPI(title="SupportPilot", docs_url="/docs")

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Pydantic 默认错误包含原始 input；认证表单不能回显密码。
        if request.url.path.startswith('/admin/'):
            return JSONResponse(status_code=422, content={'detail':'管理输入格式不正确：ID 使用小写字母、数字和连字符，检查资料链接、切块参数或轮次选择。'})
        return JSONResponse(status_code=422, content={"detail": "输入格式不正确：用户名为 3–32 位字母、数字或下划线；密码为 8–72 位且不超过 72 字节。" if request.url.path.startswith('/auth/') else "请输入有效文字或已接入的产品。"})
    config = json.loads((ROOT / "examples/rag/source.json").read_text(encoding="utf-8"))
    from supportpilot.server.admin_support import AdminWorkspace
    workspace = admin_workspace or AdminWorkspace(ROOT)
    app.state.admin_workspace = workspace

    def products():
        return workspace.active()['products']
    locks = {}
    sessions_lock = Lock()
    runner = turn_runner or Runtime(workspace.active()['chunks_path'])
    logs = Path(log_dir) if log_dir else ROOT / ".local/web"
    store_path = Path(db_path) if db_path else ROOT / ".local/web/sessions.sqlite"
    app.state.store = None
    app.state.session_locks = locks
    auth_attempts = {}

    def set_identity_cookie(request, response, token):
        response.set_cookie("supportpilot_guest", token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=30 * 86400)

    def get_store():
        with sessions_lock:
            if app.state.store is None:
                app.state.store = SessionStore(store_path)
        return app.state.store

    def identity(request: Request, response: Response):
        origin = request.headers.get("origin")
        if request.method != "GET" and origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "请从本页面发起请求。")
        credential = request.cookies.get("supportpilot_guest")
        owner = get_store().resolve_account(credential)
        if owner:
            response.headers["Cache-Control"] = "no-store"
            return owner
        owner, token = get_store().resolve_guest(credential)
        if token:
            set_identity_cookie(request, response, token)
        response.headers["Cache-Control"] = "no-store"
        return owner

    def load_session(owner, identifier):
        try:
            return get_store().load(owner, identifier)
        except KeyError:
            raise HTTPException(404, "会话不存在或不属于当前浏览器。") from None

    def session_lock(identifier):
        with sessions_lock:
            return locks.setdefault(identifier, Lock())

    def public_reply(record):
        reply = record["response"]
        state = record["after"]
        closed = reply["kind"] in ("resolved", "handoff")
        cited = set(reply["evidence_ids"])
        product = next(p for p in products() if p['product_id'] == state['product_id'])
        sources = [{"id": p["id"], "title": product["name"] + " 用户手册",
                    "page": p.get("page"), "url": p["source_url"], "text": p["text"]}
                   for p in record["passages"] if p["id"] in cited]
        summary = None
        if closed:
            summary = {"facts": [f["text"] for f in state["facts"]],
                       "checks": [{"text": c["text"], "result": c["result"]} for c in state["checks"]]}
        return {"response": reply, "sources": sources, "closed": closed,
                "status": state["status"], "summary": summary}
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True, "product": "Archer AX55", "variant": "US · V1",
                "product_id": config["product_id"], "source_url": config["source_url"]}

    @app.get("/auth/me")
    def current_identity(owner: str = Depends(identity)):
        account = get_store().account_for_owner(owner)
        return {"authenticated": bool(account), "username": account["username"] if account else None}

    def sign_in(body, request, response, owner, register):
        if register and body.username.lower() in app.state.reserved_admin_names:
            raise HTTPException(409, "该用户名已由管理配置保留。管理员请先注册账号，再配置管理名单并重启服务。")
        address = request.client.host if request.client else "local"
        with sessions_lock:
            attempts = [t for t in auth_attempts.get(address, []) if t > time.monotonic() - 60]
            if len(attempts) >= 10:
                raise HTTPException(429, "尝试次数较多，请稍后再试。")
            auth_attempts[address] = attempts + [time.monotonic()]
        try:
            token = get_store().authenticate(body.username, body.password, register=register,
                                            guest_owner=owner if body.migrate_guest else None)
        except PermissionError:
            raise HTTPException(401, "用户名或密码错误。") from None
        except ValueError:
            raise HTTPException(409, "用户名已被使用。") from None
        get_store().revoke_account_token(request.cookies.get("supportpilot_guest"))
        set_identity_cookie(request, response, token)
        return {"authenticated": True, "username": body.username.lower()}

    @app.post("/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response, owner: str = Depends(identity)):
        return sign_in(body, request, response, owner, True)

    @app.post("/auth/login")
    def login(body: Credentials, request: Request, response: Response, owner: str = Depends(identity)):
        return sign_in(body, request, response, owner, False)

    @app.post("/auth/logout")
    def logout(request: Request, response: Response, owner: str = Depends(identity)):
        get_store().revoke_account_token(request.cookies.get("supportpilot_guest"))
        _, token = get_store().resolve_guest()
        set_identity_cookie(request, response, token)
        return {"authenticated": False, "username": None}

    @app.post("/sessions", status_code=201)
    def create_session(body: SessionInput | None = None, owner: str = Depends(identity)):
        product_id = body.product_id if body and body.product_id is not None else config["product_id"]
        if product_id not in {p['product_id'] for p in products()}:
            raise HTTPException(422, "请选择已接入的产品。")
        if len(get_store().list_sessions(owner)) >= 200:
            raise HTTPException(503, "当前浏览器已达到演示会话上限。")
        identifier = get_store().create(owner, product_id)
        return {"session_id": identifier, "product_id": product_id}

    @app.get("/sessions")
    def list_sessions(owner: str = Depends(identity)):
        return get_store().list_sessions(owner)

    @app.get("/sessions/{session_id}")
    def restore_session(session_id: str, owner: str = Depends(identity)):
        load_session(owner, session_id)
        lock = session_lock(session_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "上一条消息仍在处理，请稍候。")
        try:
            saved = load_session(owner, session_id)
            turns = get_store().load_turns(owner, session_id)
            return {"session_id": session_id, "product_id": saved["state"]["product_id"],
                    "closed": saved["closed"], "status": saved["state"]["status"],
                    "turns": [{"user_text": r["user_text"], **public_reply(r)} for r in turns]}
        finally:
            lock.release()

    @app.get("/products")
    def list_products():
        return products()

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str, owner: str = Depends(identity)):
        load_session(owner, session_id)
        lock = session_lock(session_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "会话仍在处理，请稍候再删除。")
        try:
            get_store().delete_session(owner, session_id)
            # 仅清理由系统生成的会话目录，不允许任意路径或链接越界。
            root = logs.resolve()
            folder = logs / session_id
            cleanup = True
            if re.fullmatch(r"[0-9a-f]{32}", session_id) and folder.exists():
                if folder.is_symlink() or not folder.resolve().is_relative_to(root):
                    cleanup = False
                else:
                    try:
                        shutil.rmtree(folder)
                    except OSError:
                        cleanup = False
            return {"deleted": True, "logs_removed": cleanup}
        except KeyError:
            raise HTTPException(404, "会话不存在或不属于当前身份。") from None
        except Exception:
            raise HTTPException(503, "会话未能删除，请稍后重试。") from None
        finally:
            lock.release()

    @app.post("/sessions/{session_id}/messages")
    def send_message(session_id: str, body: MessageInput, owner: str = Depends(identity)):
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "请输入有效文字。")
        load_session(owner, session_id)
        lock = session_lock(session_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "上一条消息仍在处理，请稍候。")
        try:
            session = load_session(owner, session_id)
            state = session["state"]
            if session["closed"]:
                raise HTTPException(409, "本次会话已结束，请新建会话。")
            if len(state["messages"]) >= 24:
                raise HTTPException(409, "本次会话已达到演示轮数上限，请新建会话。")
            folder = logs / session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"attempt-{uuid4().hex}.json"
            partial = {"user_text": text, "before": deepcopy(state),
                       "status": "running", "stage": "initializing"}

            def save(record):
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

            def progress(stage, data):
                partial.update(data)
                partial["stage"] = stage
                save(partial)

            save(partial)
            try:
                record = runner(user_text=text, state=deepcopy(state), on_progress=progress)
            except Exception as exc:
                partial.update(status="error", error_type=type(exc).__name__)
                save(partial)
                if "timeout" in type(exc).__name__.lower():
                    raise HTTPException(504, "本轮请求超时，已保留之前的对话。请稍后重试。") from None
                raise HTTPException(502, "本轮未能完成，已保留之前的对话。请稍后重试或查看本地日志。") from None
            save(record)
            if not record["accepted"]:
                raise HTTPException(502, "本轮回复未通过校验，未作为建议展示。请重试或重新描述问题。")
            presentation = public_reply(record)
            try:
                get_store().commit_turn(owner, session_id, session["revision"], record)
            except SessionConflict:
                save({**record, "commit_status": "conflict"})
                raise HTTPException(409, "会话已更新，请重新打开历史会话。") from None
            except Exception as exc:
                save({**record, "commit_status": "error", "error_type": type(exc).__name__})
                raise HTTPException(503, "本轮未能保存，请稍后重试。") from None
            return presentation
        finally:
            lock.release()

    from supportpilot.server.admin import install_admin
    install_admin(app, get_store=get_store, root=ROOT, web=WEB, admin_usernames=admin_usernames,
                  workspace=workspace, runner=runner, indexer=corpus_indexer, judge_factory=judge_factory)
    return app


app = create_app()
