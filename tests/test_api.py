"""HTTP 接线检查：使用模拟核心，不读取密钥或调用外部服务。"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from supportpilot.api import create_app


def fake_turn(*, user_text, state, on_progress):
    on_progress("propose_response", {"query": user_text})
    after = deepcopy(state)
    after["messages"].append({"role": "user", "text": user_text})
    return {"accepted": True, "response": {"kind": "answer", "text": "合成回复",
                                          "evidence_ids": ["p1"]}, "after": after,
            "passages": [{"id": "p1", "page": 2, "text": "合成正文", "source_url": "https://example.test/manual"}]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.mkdir = patch.object(Path, "mkdir").start()
        self.write = patch.object(Path, "write_text").start()
        self.addCleanup(patch.stopall)
        self.app = create_app(turn_runner=fake_turn)
        self.client = TestClient(self.app)

    def session(self):
        return self.client.post("/sessions").json()["session_id"]

    def test_sessions_are_isolated_and_response_excludes_internal_state(self):
        a,b = self.session(),self.session()
        reply = self.client.post(f"/sessions/{a}/messages",json={"text":"问题"})
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()["sources"][0]["text"],"合成正文")
        self.assertNotIn("after",reply.json())
        self.assertEqual(len(self.app.state.sessions[b].state["messages"]),0)
        self.assertEqual(len(self.app.state.sessions[a].state["messages"]),1)

    def test_timeout_retains_state_and_does_not_leak_exception(self):
        def fail(**kwargs):
            kwargs["state"]["facts"].append({"text":"不能提交"})
            raise TimeoutError("private provider details")
        app = create_app(turn_runner=fail)
        client = TestClient(app)
        identifier = client.post("/sessions").json()["session_id"]
        reply = client.post(f"/sessions/{identifier}/messages",json={"text":"问题"})
        self.assertEqual(reply.status_code,504)
        self.assertNotIn("private provider",reply.text)
        self.assertEqual(app.state.sessions[identifier].state["facts"],[])
        self.assertFalse(app.state.sessions[identifier].lock.locked())

    def test_busy_blank_unknown_and_closed_sessions(self):
        identifier = self.session()
        path = f"/sessions/{identifier}/messages"
        self.assertEqual(self.client.post(path,json={"text":"  "}).status_code,422)
        self.assertEqual(self.client.post('/sessions/missing/messages',json={"text":"x"}).status_code,404)
        session=self.app.state.sessions[identifier]
        session.lock.acquire()
        try:self.assertEqual(self.client.post(path,json={"text":"x"}).status_code,409)
        finally:session.lock.release()
        session.closed=True
        self.assertEqual(self.client.post(path,json={"text":"x"}).status_code,409)

    def test_rejected_output_is_not_committed(self):
        def reject(**kwargs):
            record=fake_turn(**kwargs);record["accepted"]=False
            return record
        app=create_app(turn_runner=reject);client=TestClient(app)
        identifier=client.post('/sessions').json()['session_id']
        self.assertEqual(client.post(f'/sessions/{identifier}/messages',json={'text':'问题'}).status_code,502)
        self.assertEqual(app.state.sessions[identifier].state['messages'],[])

    def test_handoff_closes_without_marking_resolved(self):
        def handoff(**kwargs):
            record=fake_turn(**kwargs);record['response']['kind']='handoff'
            return record
        client=TestClient(create_app(turn_runner=handoff))
        identifier=client.post('/sessions').json()['session_id']
        reply=client.post(f'/sessions/{identifier}/messages',json={'text':'问题'}).json()
        self.assertTrue(reply['closed']);self.assertEqual(reply['status'],'ongoing')
        self.assertIsNotNone(reply['summary'])

    def test_static_page_opens_without_initializing_model(self):
        client=TestClient(create_app())
        self.assertEqual(client.get('/').status_code,200)
        self.assertEqual(client.get('/static/app.js').status_code,200)
        self.assertTrue(client.get('/health').json()['ok'])


if __name__ == '__main__':
    unittest.main()
