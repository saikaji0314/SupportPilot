from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from contextlib import closing
import sqlite3

from supportpilot.chat_support import finish_turn
from supportpilot.conversation import Feedback
from supportpilot.grounded import GroundedResponse
from supportpilot.session_store import SessionStore, SessionConflict


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "sessions.sqlite"
        self.store = SessionStore(self.path)
        self.id = self.store.create("owner", "product")
        state = self.store.load("owner", self.id)["state"]
        self.record = finish_turn(before=state, updated=state, user_text="问题",
            feedback=Feedback(), query="问题", passages=[],
            reply=GroundedResponse(kind="ask_user", text="请描述指示灯"))

    def test_restore_ownership_and_stale_commit(self):
        self.store.commit_turn("owner", self.id, 0, self.record)
        reopened = SessionStore(self.path)
        self.assertEqual(reopened.load("owner", self.id)["state"], self.record["after"])
        self.assertEqual(reopened.load_turns("owner", self.id), [self.record])
        self.assertEqual(reopened.list_sessions("other"), [])
        for action in [lambda: reopened.load("other", self.id),
                       lambda: reopened.load_turns("other", self.id),
                       lambda: reopened.commit_turn("other", self.id, 1, self.record)]:
            with self.assertRaises(KeyError): action()
        with self.assertRaises(SessionConflict):
            reopened.commit_turn("owner", self.id, 0, self.record)
        self.assertEqual(len(reopened.load_turns("owner", self.id)), 1)

    def test_rejection_and_product_change_do_not_write(self):
        for change in [{"accepted": False}, {"after": {**self.record["after"], "product_id": "other"}}]:
            record = {**deepcopy(self.record), **change}
            with self.assertRaises(ValueError):
                self.store.commit_turn("owner", self.id, 0, record)
        self.assertEqual(self.store.load("owner", self.id)["revision"], 0)

    def test_state_update_rolls_back_if_turn_insert_fails(self):
        with closing(self.store.connect()) as db, db:
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON turns BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.commit_turn("owner", self.id, 0, self.record)
        self.assertEqual(self.store.load("owner", self.id)["state"], self.record["before"])
        self.assertEqual(self.store.load_turns("owner", self.id), [])
