"""会话持久化基础；owner_id 由服务端身份层提供，不是浏览器自报身份。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import hashlib
import secrets
import time
from uuid import uuid4

from supportpilot.chat_support import new_state


class SessionConflict(ValueError):
    """会话已更新或结束，不能提交旧输入生成的结果。"""


class SessionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    owner_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_tokens (
                    token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES accounts(owner_id),
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guests (
                    token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    product_id TEXT NOT NULL, state_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    closed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner_id);
                CREATE TABLE IF NOT EXISTS turns (
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    revision INTEGER NOT NULL, record_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, revision)
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def create(self, owner_id, product_id):
        if not owner_id or not product_id:
            raise ValueError("身份和产品不能为空")
        identifier = uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO sessions(id, owner_id, product_id, state_json) VALUES (?, ?, ?, ?)",
                       (identifier, owner_id, product_id, json.dumps(new_state(product_id), ensure_ascii=False)))
        return identifier

    def resolve_guest(self, token=None):
        """验证随机 Cookie 凭据；无效时创建新身份，数据库只保存凭据哈希。"""
        with closing(self.connect()) as db, db:
            if token and len(token) <= 128:
                digest = hashlib.sha256(token.encode()).hexdigest()
                row = db.execute("SELECT owner_id FROM guests WHERE token_hash=?", (digest,)).fetchone()
                if row:
                    return row[0], None
            token = secrets.token_urlsafe(32)
            owner = uuid4().hex
            db.execute("INSERT INTO guests VALUES (?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), owner))
        return owner, token

    def load(self, owner_id, session_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND owner_id=?",
                             (session_id, owner_id)).fetchone()
        if row is None:
            raise KeyError("会话不存在或不属于当前身份")
        return {"id": row["id"], "state": json.loads(row["state_json"]),
                "revision": row["revision"], "closed": bool(row["closed"])}

    def account_for_owner(self, owner):
        with closing(self.connect()) as db:
            row = db.execute("SELECT username FROM accounts WHERE owner_id=?", (owner,)).fetchone()
        return {"username": row[0]} if row else None

    def resolve_account(self, token):
        if not token or len(token) > 128:
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT owner_id FROM account_tokens WHERE token_hash=? AND expires_at>?",
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row[0] if row else None

    def authenticate(self, username, password, *, register=False, guest_owner=None):
        from supportpilot.passwords import hash_password, verify_password
        username = username.lower()
        with closing(self.connect()) as db:
            account = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        if register:
            if account:
                raise ValueError("用户名已被使用")
            owner, password_hash = uuid4().hex, hash_password(password)
        else:
            if not verify_password(password, account["password_hash"] if account else None):
                raise PermissionError("用户名或密码错误")
            owner, password_hash = account["owner_id"], None
        token = secrets.token_urlsafe(32)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if register:
                try:
                    db.execute("INSERT INTO accounts VALUES (?, ?, ?)", (owner, username, password_hash))
                except sqlite3.IntegrityError:
                    raise ValueError("用户名已被使用") from None
            if guest_owner and not db.execute("SELECT 1 FROM accounts WHERE owner_id=?", (guest_owner,)).fetchone():
                db.execute("UPDATE sessions SET owner_id=? WHERE owner_id=?", (owner, guest_owner))
                db.execute("DELETE FROM guests WHERE owner_id=?", (guest_owner,))
            db.execute("INSERT INTO account_tokens VALUES (?, ?, ?)",
                       (hashlib.sha256(token.encode()).hexdigest(), owner, time.time() + 30 * 86400))
        return token

    def revoke_account_token(self, token):
        if token:
            with closing(self.connect()) as db, db:
                db.execute("DELETE FROM account_tokens WHERE token_hash=?",
                           (hashlib.sha256(token.encode()).hexdigest(),))

    def delete_session(self, owner, identifier):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM sessions WHERE id=? AND owner_id=?", (identifier, owner)).fetchone():
                raise KeyError("会话不存在或不属于当前身份")
            db.execute("DELETE FROM turns WHERE session_id=?", (identifier,))
            db.execute("DELETE FROM sessions WHERE id=? AND owner_id=?", (identifier, owner))

    def list_sessions(self, owner_id):
        with closing(self.connect()) as db:
            rows = db.execute("""SELECT id, product_id, revision, closed,
                (SELECT record_json FROM turns WHERE session_id=sessions.id ORDER BY revision LIMIT 1) AS first_turn
                FROM sessions WHERE owner_id=? ORDER BY rowid DESC""",
                              (owner_id,)).fetchall()
        return [self.session_summary(row) for row in rows]

    @staticmethod
    def session_summary(row):
        item = dict(row)
        first = json.loads(item.pop("first_turn") or "{}")
        text = " ".join(first.get("user_text", "").split())
        item["title"] = text[:28] + ("…" if len(text) > 28 else "") if text else "新会话"
        return item

    def admin_sessions(self, limit=50, offset=0):
        """调用方必须已鉴权；只返回概览，不含凭据和内部身份 ID。"""
        with closing(self.connect()) as db:
            total = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            rows = db.execute("""SELECT s.id, s.product_id, s.revision, s.closed,
                COALESCE(a.username, '临时访客') AS username,
                (SELECT record_json FROM turns WHERE session_id=s.id ORDER BY revision LIMIT 1) AS first_turn
                FROM sessions s LEFT JOIN accounts a ON s.owner_id=a.owner_id
                ORDER BY s.rowid DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        return {"total": total, "items": [self.session_summary(row) for row in rows]}

    def admin_session(self, identifier):
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT product_id, state_json FROM sessions WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            turns = db.execute("SELECT record_json FROM turns WHERE session_id=? ORDER BY revision", (identifier,)).fetchall()
        return {"id": identifier, "product_id": row["product_id"], "state": json.loads(row["state_json"]),
                "turns": [json.loads(turn[0]) for turn in turns]}

    def load_turns(self, owner_id, session_id):
        self.load(owner_id, session_id)
        with closing(self.connect()) as db:
            rows = db.execute("SELECT record_json FROM turns WHERE session_id=? ORDER BY revision",
                              (session_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def commit_turn(self, owner_id, session_id, expected_revision, record):
        """只保存通过校验的一轮；状态和引用正文在同一事务中提交。"""
        if record.get("accepted") is not True or record.get("errors"):
            raise ValueError("不保存被拒绝的候选")
        payload = json.dumps(record, ensure_ascii=False)
        after = record["after"]
        closed = record["response"]["kind"] in ("resolved", "handoff")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sessions WHERE id=? AND owner_id=?",
                             (session_id, owner_id)).fetchone()
            if row is None:
                raise KeyError("会话不存在或不属于当前身份")
            if row["closed"] or row["revision"] != expected_revision:
                raise SessionConflict("会话已更新或结束")
            if json.loads(row["state_json"]) != record["before"]:
                raise SessionConflict("候选使用的状态已过期")
            if after["product_id"] != row["product_id"]:
                raise ValueError("同一会话不能更换产品")
            revision = expected_revision + 1
            db.execute("UPDATE sessions SET state_json=?, revision=?, closed=? WHERE id=? AND owner_id=?",
                       (json.dumps(after, ensure_ascii=False), revision, int(closed), session_id, owner_id))
            db.execute("INSERT INTO turns(session_id, revision, record_json) VALUES (?, ?, ?)",
                       (session_id, revision, payload))
        return revision
