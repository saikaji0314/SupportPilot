"""会话持久化基础；owner_id 由服务端身份层提供，不是浏览器自报身份。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
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

    def load(self, owner_id, session_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND owner_id=?",
                             (session_id, owner_id)).fetchone()
        if row is None:
            raise KeyError("会话不存在或不属于当前身份")
        return {"id": row["id"], "state": json.loads(row["state_json"]),
                "revision": row["revision"], "closed": bool(row["closed"])}

    def list_sessions(self, owner_id):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT id, product_id, revision, closed FROM sessions WHERE owner_id=? ORDER BY rowid DESC",
                              (owner_id,)).fetchall()
        return [dict(row) for row in rows]

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
