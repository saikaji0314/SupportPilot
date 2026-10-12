from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from supportpilot.server.api import create_app
from supportpilot.server.admin import document_inventory
from tests.test_api import fake_turn


class AdminTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.app = create_app(turn_runner=fake_turn, db_path=root/'db.sqlite', log_dir=root/'logs',
                              admin_usernames=['reviewer'])
        self.client = TestClient(self.app)

    def register(self, client, name):
        if name == 'reviewer':
            # 模拟已注册账号随后由本机管理员配置授权；公网不能抢注保留名。
            client.get('/auth/me')
            self.app.state.store.authenticate(name, 'Synthetic-only-123', register=True)
            result = client.post('/auth/login', json={'username': name, 'password': 'Synthetic-only-123'})
            self.assertEqual(result.status_code, 200)
            return
        result = client.post('/auth/register', json={'username': name, 'password': 'Synthetic-only-123'})
        self.assertEqual(result.status_code, 201)

    def test_all_admin_data_routes_require_authorized_account(self):
        paths = ['/admin/api/me', '/admin/api/documents', '/admin/api/sessions', '/admin/api/sessions/missing']
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.register(self.client, 'ordinary')
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.get('/admin/api/sessions?username=reviewer').status_code, 403)

    def test_title_trace_and_delete_are_consistent(self):
        identifier = self.client.post('/sessions').json()['session_id']
        self.assertEqual(self.client.get('/sessions').json()[0]['title'], '新会话')
        question = '  已经连上路由器网络，\n但是始终无法打开网页。请帮我确认下一步如何检查。 '
        self.client.post(f'/sessions/{identifier}/messages', json={'text': question})
        title = ' '.join(question.split())[:28] + '…'
        self.assertEqual(self.client.get('/sessions').json()[0]['title'], title)
        self.client.post(f'/sessions/{identifier}/messages', json={'text':'第二个问题'})
        admin = TestClient(self.app)
        self.register(admin, 'reviewer')
        response = admin.get('/admin/api/sessions')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        item = response.json()['items'][0]
        self.assertEqual(item['title'], title)
        self.assertNotIn('owner_id', item)
        trace = admin.get(f'/admin/api/sessions/{identifier}').json()
        self.assertEqual(len(trace['turns']), 2)
        self.assertEqual(trace['turns'][0]['user_text'], question.strip())
        # 管理员的只读权限不会改变用户端会话归属。
        self.assertEqual(admin.delete(f'/sessions/{identifier}').status_code, 404)
        self.assertEqual(self.client.delete(f'/sessions/{identifier}').status_code, 200)
        self.assertEqual(admin.get(f'/admin/api/sessions/{identifier}').status_code, 404)

    def test_inventory_errors_pagination_and_revocation(self):
        self.register(self.client, 'reviewer')
        with patch.object(self.app.state.admin_workspace, 'inventory', return_value={'documents':[], 'index_status':'未检查'}):
            self.assertEqual(self.client.get('/admin/api/documents').status_code, 200)
        with patch.object(self.app.state.admin_workspace, 'inventory', side_effect=OSError('private path')):
            result = self.client.get('/admin/api/documents')
            self.assertEqual(result.status_code, 503)
            self.assertNotIn('private path', result.text)
        self.assertEqual(self.client.get('/admin/api/sessions?limit=101').status_code, 422)
        self.assertEqual(self.client.get('/admin/api/sessions?offset=-1').status_code, 422)
        self.client.post('/auth/logout')
        self.assertEqual(self.client.get('/admin/api/sessions').status_code, 401)

    def test_no_admin_enabled_by_default(self):
        self.register(self.client, 'reviewer')
        with patch.dict('os.environ', {'SUPPORTPILOT_ADMIN_USERS':''}):
            app = create_app(db_path=self.app.state.store.path)
        other = TestClient(app)
        other.cookies.update(self.client.cookies)
        self.assertEqual(other.get('/admin/api/me').status_code, 403)

    def test_configured_admin_name_cannot_be_claimed_by_registration(self):
        result = self.client.post('/auth/register', json={'username':'reviewer', 'password':'Synthetic-only-123'})
        self.assertEqual(result.status_code, 409)

    def test_inventory_counts_saved_versions_without_claiming_index_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'examples/rag').mkdir(parents=True)
            (root/'.local/corpus').mkdir(parents=True)
            (root/'examples/rag/corpus.json').write_text(json.dumps({'sources':['source.json']}))
            (root/'source.json').write_text(json.dumps({'document_id':'doc', 'product_id':'device',
                'source_url':'https://example.test/manual', 'scope_note':'Synthetic'}))
            chunks = [{'metadata':{'document_id':'doc','source_revision':revision}} for revision in ['v1','v1','v2']]
            (root/'.local/corpus/chunks.json').write_text(json.dumps(chunks))
            result = document_inventory(root)
            self.assertEqual(result['documents'][0]['chunk_count'], 3)
            self.assertEqual(len(result['documents'][0]['versions']), 2)
            self.assertIn('未检查', result['index_status'])


if __name__ == '__main__':
    unittest.main()
