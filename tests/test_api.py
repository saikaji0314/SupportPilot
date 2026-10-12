"""HTTP 接线检查：使用模拟核心，不读取密钥或调用外部服务。"""
from copy import deepcopy
from pathlib import Path
import tempfile
from contextlib import closing
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from supportpilot.server.api import Runtime, create_app
from supportpilot.agent.chat_graph import run_turn_graph
from supportpilot.agent.conversation import Feedback
from supportpilot.agent.grounded import GroundedResponse


def fake_turn(*, user_text, state, on_progress):
    on_progress("propose_response", {"query": user_text})
    after = deepcopy(state)
    after["messages"].append({"role": "user", "text": user_text})
    return {"before": deepcopy(state), "user_text": user_text, "errors": [], "accepted": True, "response": {"kind": "answer", "text": "合成回复",
                                          "evidence_ids": ["p1"]}, "after": after,
            "passages": [{"id": "p1", "page": 2, "text": "合成正文", "source_url": "https://example.test/manual"}]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.app_count = 0
        self.write = patch.object(Path, "write_text").start()
        self.addCleanup(patch.stopall)
        self.app = self.make_app(turn_runner=fake_turn)
        self.client = TestClient(self.app)

    def make_app(self, **kwargs):
        self.app_count += 1
        kwargs.setdefault('log_dir', self.folder / 'logs')
        return create_app(db_path=self.folder / f"test-{self.app_count}.sqlite", **kwargs)

    def saved(self, app, client, identifier):
        owner, _ = app.state.store.resolve_guest(client.cookies.get('supportpilot_guest'))
        return app.state.store.load(owner, identifier)

    def session(self):
        return self.client.post("/sessions").json()["session_id"]

    def test_sessions_are_isolated_and_response_excludes_internal_state(self):
        a,b = self.session(),self.session()
        reply = self.client.post(f"/sessions/{a}/messages",json={"text":"问题"})
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()["sources"][0]["text"],"合成正文")
        self.assertNotIn("after",reply.json())
        self.assertEqual(len(self.saved(self.app, self.client, b)['state']["messages"]),0)
        self.assertEqual(len(self.saved(self.app, self.client, a)['state']["messages"]),1)

    def test_timeout_retains_state_and_does_not_leak_exception(self):
        def fail(**kwargs):
            kwargs["state"]["facts"].append({"text":"不能提交"})
            raise TimeoutError("private provider details")
        app = self.make_app(turn_runner=fail)
        client = TestClient(app)
        identifier = client.post("/sessions").json()["session_id"]
        reply = client.post(f"/sessions/{identifier}/messages",json={"text":"问题"})
        self.assertEqual(reply.status_code,504)
        self.assertNotIn("private provider",reply.text)
        self.assertEqual(self.saved(app, client, identifier)['state']["facts"],[])
        self.assertFalse(app.state.session_locks[identifier].locked())

    def test_busy_blank_unknown_and_closed_sessions(self):
        identifier = self.session()
        path = f"/sessions/{identifier}/messages"
        self.assertEqual(self.client.post(path,json={"text":"  "}).status_code,422)
        self.assertEqual(self.client.post('/sessions/missing/messages',json={"text":"x"}).status_code,404)
        self.client.post(path,json={"text":"x"})
        lock=self.app.state.session_locks[identifier]
        lock.acquire()
        try:self.assertEqual(self.client.post(path,json={"text":"x"}).status_code,409)
        finally:lock.release()
        with closing(self.app.state.store.connect()) as db, db:
            db.execute("UPDATE sessions SET closed=1 WHERE id=?", (identifier,))
        self.assertEqual(self.client.post(path,json={"text":"x"}).status_code,409)

    def test_rejected_output_is_not_committed(self):
        def reject(**kwargs):
            record=fake_turn(**kwargs);record["accepted"]=False
            return record
        app=self.make_app(turn_runner=reject);client=TestClient(app)
        identifier=client.post('/sessions').json()['session_id']
        self.assertEqual(client.post(f'/sessions/{identifier}/messages',json={'text':'问题'}).status_code,502)
        self.assertEqual(self.saved(app, client, identifier)['state']['messages'],[])

    def test_handoff_closes_without_marking_resolved(self):
        def handoff(**kwargs):
            record=fake_turn(**kwargs);record['response']['kind']='handoff'
            return record
        client=TestClient(self.make_app(turn_runner=handoff))
        identifier=client.post('/sessions').json()['session_id']
        reply=client.post(f'/sessions/{identifier}/messages',json={'text':'问题'}).json()
        self.assertTrue(reply['closed']);self.assertEqual(reply['status'],'ongoing')
        self.assertIsNotNone(reply['summary'])

    def test_static_page_opens_without_initializing_model(self):
        client=TestClient(self.make_app())
        self.assertEqual(client.get('/').status_code,200)
        self.assertEqual(client.get('/static/app.js').status_code,200)
        self.assertTrue(client.get('/health').json()['ok'])

    def test_product_selection_binds_new_session_and_rejects_unknown(self):
        products = self.client.get('/products').json()
        self.assertEqual(len(products), 2)
        selected = products[1]['product_id']
        identifier = self.client.post('/sessions', json={'product_id': selected}).json()['session_id']
        self.assertEqual(self.saved(self.app, self.client, identifier)['state']['product_id'], selected)
        reply = self.client.post(f'/sessions/{identifier}/messages', json={'text': '问题'})
        self.assertEqual(reply.json()['sources'][0]['title'], 'RE315 用户手册')
        self.assertEqual(self.client.post('/sessions', json={'product_id': 'unknown'}).status_code, 422)
        default = self.session()
        self.assertNotEqual(self.saved(self.app, self.client, default)['state']['product_id'], selected)

    def test_runtime_loads_shared_corpus(self):
        runtime = Runtime()
        with patch('supportpilot.providers.bailian.bailian', return_value=object()), \
             patch('supportpilot.server.api.make_retriever', return_value=object()) as retrieve, \
             patch('supportpilot.server.api.run_turn_graph', return_value={}) as graph:
            runtime(user_text='问题', state={'product_id': 'tp-link-re315-us-v1'})
        self.assertEqual(retrieve.call_args.args[0].name, 'chunks.json')
        self.assertEqual(retrieve.call_args.args[0].parent.name, 'corpus')
        self.assertEqual(graph.call_args.kwargs['state']['product_id'], 'tp-link-re315-us-v1')

    def test_runtime_uses_real_graph_across_two_http_turns(self):
        runtime = Runtime()
        runtime.resources = (object(), lambda query, product_id: [{
            "id": "p1", "text": "合成检查", "product_ids": [product_id],
            "page": 2, "source_url": "https://example.test/manual"}])
        app = self.make_app(turn_runner=runtime)
        client = TestClient(app)
        identifier = client.post('/sessions').json()['session_id']
        path = f'/sessions/{identifier}/messages'
        with patch('supportpilot.server.api.run_turn_graph', wraps=run_turn_graph) as graph_call, \
             patch('supportpilot.agent.chat_graph.extract_feedback', side_effect=[Feedback(), Feedback(issue_status='resolved')]), \
             patch('supportpilot.agent.chat_graph.propose_response', side_effect=[
                 GroundedResponse(kind='recommend_check', text='合成检查', evidence_ids=['p1']),
                 GroundedResponse(kind='resolved', text='已恢复')]):
            first = client.post(path, json={'text': '无法上网'})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()['sources'][0]['id'], 'p1')
            second = client.post(path, json={'text': '已经恢复'})
            self.assertEqual(second.status_code, 200)
            self.assertTrue(second.json()['closed'])
            self.assertEqual(second.json()['status'], 'resolved')
            self.assertEqual(graph_call.call_count, 2)
        self.assertEqual(len(self.saved(app, client, identifier)['state']['messages']), 4)
        self.assertIsNone(self.saved(app, client, identifier)['state']['pending'])

    def test_graph_timeout_keeps_session_and_allows_retry(self):
        runtime = Runtime()
        runtime.resources = (object(), lambda query, product_id: [])
        app = self.make_app(turn_runner=runtime)
        client = TestClient(app)
        identifier = client.post('/sessions').json()['session_id']
        before = deepcopy(self.saved(app, client, identifier)['state'])
        path = f'/sessions/{identifier}/messages'
        with patch('supportpilot.agent.chat_graph.extract_feedback', return_value=Feedback(facts=[{'text': '未提交事实'}])), \
             patch('supportpilot.agent.chat_graph.propose_response', side_effect=TimeoutError('private provider')):
            failed = client.post(path, json={'text': '问题'})
        self.assertEqual(failed.status_code, 504)
        self.assertEqual(self.saved(app, client, identifier)['state'], before)
        self.assertNotIn('private provider', failed.text)
        with patch('supportpilot.agent.chat_graph.extract_feedback', return_value=Feedback()), \
             patch('supportpilot.agent.chat_graph.propose_response', return_value=GroundedResponse(kind='handoff', text='缺资料')):
            retried = client.post(path, json={'text': '问题'})
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(len(self.saved(app, client, identifier)['state']['messages']), 2)

    def test_graph_repair_commit_rejection_and_timeout(self):
        bad = GroundedResponse(kind='answer', text='无效引用', evidence_ids=['missing'])
        good = GroundedResponse(kind='recommend_check', text='合成检查', evidence_ids=['p1'])
        for outcome, expected in [(good, 200), (bad, 502), (TimeoutError('private'), 504)]:
            with self.subTest(status=expected):
                runtime = Runtime()
                runtime.resources = (object(), lambda query, product_id: [{
                    'id': 'p1', 'text': '合成检查', 'product_ids': [product_id],
                    'source_url': 'https://example.test/manual'}])
                app = self.make_app(turn_runner=runtime)
                client = TestClient(app)
                identifier = client.post('/sessions').json()['session_id']
                before = deepcopy(self.saved(app, client, identifier)['state'])
                kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with patch('supportpilot.agent.chat_graph.extract_feedback', return_value=Feedback()), \
                     patch('supportpilot.agent.chat_graph.propose_response', return_value=bad), \
                     patch('supportpilot.agent.chat_graph.repair_response', **kwargs) as repair:
                    response = client.post(f'/sessions/{identifier}/messages', json={'text': '问题'})
                self.assertEqual(response.status_code, expected)
                self.assertEqual(repair.call_count, 1)
                session = self.saved(app, client, identifier)
                self.assertFalse(app.state.session_locks[identifier].locked())
                if expected == 200:
                    self.assertEqual(len(session['state']['messages']), 2)
                    self.assertEqual(len(session['state']['checks']), 1)
                    self.assertEqual(response.json()['response'], good.model_dump())
                else:
                    self.assertEqual(session['state'], before)
                saved = __import__('json').loads(self.write.call_args.args[0])
                self.assertEqual(len(saved['repair_attempts']), 1)
                if expected == 504:
                    self.assertEqual(saved['stage'], 'repair_response')

    def test_restart_restores_product_sources_and_continues(self):
        identifier = self.client.post('/sessions', json={'product_id': 'tp-link-re315-us-v1'}).json()['session_id']
        self.client.post(f'/sessions/{identifier}/messages', json={'text': '第一轮'})
        database = self.app.state.store.path
        app = create_app(turn_runner=fake_turn, db_path=database, log_dir=self.folder)
        client = TestClient(app)
        client.cookies.update(self.client.cookies)
        detail = client.get(f'/sessions/{identifier}').json()
        self.assertEqual(detail['product_id'], 'tp-link-re315-us-v1')
        self.assertEqual(detail['turns'][0]['sources'][0]['text'], '合成正文')
        self.assertNotIn('state', detail)
        self.assertEqual(client.post(f'/sessions/{identifier}/messages', json={'text': '第二轮'}).status_code, 200)
        self.assertEqual(len(client.get(f'/sessions/{identifier}').json()['turns']), 2)
        self.assertEqual(client.get('/sessions').json()[0]['revision'], 2)

    def test_other_browser_and_forged_cookie_cannot_access_session(self):
        identifier = self.session()
        cookie = self.client.cookies.get('supportpilot_guest')
        other = TestClient(self.app)
        self.assertEqual(other.get('/sessions').json(), [])
        self.assertEqual(other.get(f'/sessions/{identifier}').status_code, 404)
        self.assertEqual(other.post(f'/sessions/{identifier}/messages', json={'text': 'x'}).status_code, 404)
        forged = TestClient(self.app)
        forged.cookies.set('supportpilot_guest', 'invented-credential', domain='testserver.local', path='/')
        self.assertEqual(forged.get('/sessions').json(), [])
        self.assertEqual(forged.get(f'/sessions/{identifier}').status_code, 404)
        self.assertNotEqual(forged.cookies.get('supportpilot_guest'), cookie)

    def test_cookie_flags_closed_history_and_cross_origin_write(self):
        reply = self.client.post('/sessions')
        header = reply.headers['set-cookie'].lower()
        self.assertIn('httponly', header)
        self.assertIn('samesite=strict', header)
        identifier = reply.json()['session_id']
        path = f'/sessions/{identifier}/messages'
        self.assertEqual(self.client.post(path, json={'text': 'x'}, headers={'origin': 'https://other.test'}).status_code, 403)
        self.assertEqual(self.saved(self.app, self.client, identifier)['revision'], 0)
        def handoff(**kwargs):
            record = fake_turn(**kwargs)
            record['response']['kind'] = 'handoff'
            return record
        app = create_app(turn_runner=handoff, db_path=self.app.state.store.path)
        client = TestClient(app)
        client.cookies.update(self.client.cookies)
        self.assertEqual(client.post(path, json={'text': 'x'}).status_code, 200)
        self.assertTrue(client.get(f'/sessions/{identifier}').json()['closed'])
        self.assertEqual(client.post(path, json={'text': 'x'}).status_code, 409)

    def test_database_failure_does_not_return_success(self):
        identifier = self.session()
        with patch.object(self.app.state.store, 'commit_turn', side_effect=OSError):
            result = self.client.post(f'/sessions/{identifier}/messages', json={'text': 'x'})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.saved(self.app, self.client, identifier)['revision'], 0)
        self.assertEqual(self.client.get(f'/sessions/{identifier}').json()['turns'], [])


if __name__ == '__main__':
    unittest.main()
