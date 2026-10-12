from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from supportpilot.api import create_app
from tests.test_api import fake_turn

PASSWORD = 'Synthetic-only-123'


class AuthTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / 'sessions.sqlite'
        self.logs = self.root / 'logs'
        self.app = create_app(turn_runner=fake_turn, db_path=self.database, log_dir=self.logs)
        self.client = TestClient(self.app)

    def register(self, client, username):
        response = client.post('/auth/register', json={'username': username, 'password': PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)

    def test_registration_migrates_guest_and_new_browser_login_restores(self):
        identifier = self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{identifier}/messages', json={'text': '合成对话'})
        old_guest = self.client.cookies.get('supportpilot_guest')
        self.register(self.client, 'Example_User')
        self.assertEqual(self.client.get('/auth/me').json(), {'authenticated': True, 'username': 'example_user'})
        self.assertEqual(len(self.client.get(f'/sessions/{identifier}').json()['turns']), 1)
        with closing(self.app.state.store.connect()) as db:
            saved = db.execute('SELECT password_hash FROM accounts').fetchone()[0]
        self.assertNotIn(PASSWORD, saved)
        self.assertTrue(saved.startswith('$2b$'))
        stolen = TestClient(self.app)
        stolen.cookies.set('supportpilot_guest', old_guest, domain='testserver.local', path='/')
        self.assertEqual(stolen.get(f'/sessions/{identifier}').status_code, 404)
        restarted = create_app(turn_runner=fake_turn, db_path=self.database, log_dir=self.logs)
        other = TestClient(restarted)
        self.assertEqual(other.post('/auth/login', json={'username': 'EXAMPLE_USER', 'password': PASSWORD}).status_code, 200)
        self.assertEqual(other.get('/sessions').json()[0]['id'], identifier)

    def test_wrong_password_logout_and_account_isolation(self):
        self.register(self.client, 'account_a')
        identifier = self.client.post('/sessions').json()['session_id']
        cookie = self.client.cookies.get('supportpilot_guest')
        other = TestClient(self.app)
        self.register(other, 'account_b')
        self.assertEqual(other.get(f'/sessions/{identifier}').status_code, 404)
        self.assertEqual(other.delete(f'/sessions/{identifier}').status_code, 404)
        self.assertEqual(other.post('/auth/login', json={'username': 'account_a', 'password': 'Wrong-password'}).status_code, 401)
        self.assertEqual(self.client.post('/auth/logout', json={}).status_code, 200)
        self.assertEqual(self.client.get('/sessions').json(), [])
        old = TestClient(self.app)
        old.cookies.set('supportpilot_guest', cookie, domain='testserver.local', path='/')
        self.assertEqual(old.get(f'/sessions/{identifier}').status_code, 404)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'account_a', 'password': PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get(f'/sessions/{identifier}').status_code, 200)

    def test_do_not_migrate_guest_when_unchecked_or_from_another_account(self):
        guest = self.client.post('/sessions').json()['session_id']
        response = self.client.post('/auth/register', json={'username': 'account_a', 'password': PASSWORD, 'migrate_guest': False})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get(f'/sessions/{guest}').status_code, 404)
        own = self.client.post('/sessions').json()['session_id']
        self.register(self.client, 'account_b')
        self.assertEqual(self.client.get(f'/sessions/{own}').status_code, 404)
        self.client.post('/auth/login', json={'username': 'account_a', 'password': PASSWORD})
        self.assertEqual(self.client.get(f'/sessions/{own}').status_code, 200)

    def test_duplicates_and_invalid_password_never_echo_password(self):
        self.register(self.client, 'account_a')
        self.assertEqual(self.client.post('/auth/register', json={'username': 'ACCOUNT_A', 'password': PASSWORD}).status_code, 409)
        for password in ['short', '密' * 30]:
            response = self.client.post('/auth/register', json={'username': 'account_b', 'password': password})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(password, response.text)

    def test_expired_cookie_and_login_rate_limit(self):
        self.register(self.client, 'account_a')
        with closing(self.app.state.store.connect()) as db, db:
            db.execute('UPDATE account_tokens SET expires_at=0')
        self.assertFalse(self.client.get('/auth/me').json()['authenticated'])
        with patch.object(self.app.state.store, 'authenticate', side_effect=PermissionError):
            responses = [self.client.post('/auth/login', json={'username': 'account_a', 'password': PASSWORD}) for _ in range(12)]
        self.assertEqual(responses[-1].status_code, 429)

    def test_delete_removes_turns_and_logs_and_busy_is_rejected(self):
        identifier = self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{identifier}/messages', json={'text': '合成待删除对话'})
        folder = self.logs / identifier
        self.assertTrue(folder.exists())
        lock = self.app.state.session_locks[identifier]
        lock.acquire()
        try:
            self.assertEqual(self.client.delete(f'/sessions/{identifier}').status_code, 409)
        finally:
            lock.release()
        self.assertEqual(self.client.delete(f'/sessions/{identifier}').json(), {'deleted': True, 'logs_removed': True})
        self.assertFalse(folder.exists())
        self.assertEqual(self.client.get('/sessions').json(), [])
        self.assertEqual(self.client.get(f'/sessions/{identifier}').status_code, 404)
        with closing(self.app.state.store.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0], 0)

    def test_cross_origin_auth_and_delete_rejected(self):
        identifier = self.client.post('/sessions').json()['session_id']
        headers = {'origin': 'https://other.test'}
        self.assertEqual(self.client.post('/auth/register', headers=headers, json={'username': 'account_a', 'password': PASSWORD}).status_code, 403)
        self.assertEqual(self.client.delete(f'/sessions/{identifier}', headers=headers).status_code, 403)
        self.assertEqual(self.client.get(f'/sessions/{identifier}').status_code, 200)

    def test_partial_log_cleanup_is_reported_and_db_failure_retains_session(self):
        identifier = self.client.post('/sessions').json()['session_id']
        with patch.object(self.app.state.store, 'delete_session', side_effect=OSError):
            self.assertEqual(self.client.delete(f'/sessions/{identifier}').status_code, 503)
        self.assertEqual(self.client.get(f'/sessions/{identifier}').status_code, 200)
        self.client.post(f'/sessions/{identifier}/messages', json={'text': '合成记录'})
        with patch('supportpilot.api.shutil.rmtree', side_effect=OSError):
            result = self.client.delete(f'/sessions/{identifier}').json()
        self.assertTrue(result['deleted'])
        self.assertFalse(result['logs_removed'])
