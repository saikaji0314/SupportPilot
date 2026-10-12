from supportpilot.paths import ROOT
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from supportpilot.server.api import create_app, Runtime
from supportpilot.server.admin_support import AdminWorkspace, read_json, write_json, index_corpus
from tests.test_api import fake_turn


def text_pdf(text='Official synthetic manual. Connect device before logging in.'):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'),
                             NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 20 700 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    result = BytesIO(); writer.write(result)
    return result.getvalue()


META = {'document_id':'demo-manual','product_id':'demo-device','name':'Demo Device','variant':'US V1',
        'source_url':'https://example.test/manual','scope_note':'Synthetic PDF for tests'}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.workspace = AdminWorkspace(ROOT, self.root/'admin')
        self.index_calls = []
        def indexer(chunks, path):
            self.index_calls.append(chunks)
            return 'synthetic_collection', lambda *a,**k: []
        self.indexer = indexer
        self.app = create_app(turn_runner=fake_turn, db_path=self.root/'db.sqlite', log_dir=self.root/'logs',
                              admin_usernames=['reviewer'], admin_workspace=self.workspace, corpus_indexer=indexer)
        self.client = TestClient(self.app)
        self.client.get('/auth/me')
        self.app.state.store.authenticate('reviewer','Synthetic-only-123',register=True)
        self.client.post('/auth/login',json={'username':'reviewer','password':'Synthetic-only-123'})

    def draft(self, meta=None):
        result = self.client.post('/admin/api/documents/drafts',json=meta or META)
        self.assertEqual(result.status_code,201,result.text)
        return result.json()['id']

    def upload(self, identifier, pdf=None):
        return self.client.put(f'/admin/api/documents/drafts/{identifier}/pdf',content=pdf or text_pdf(),
                               headers={'Content-Type':'application/pdf'})

    def publish(self, identifier):
        result=self.client.post(f'/admin/api/documents/drafts/{identifier}/publish',json={'confirm_external':True})
        self.assertEqual(result.status_code,202,result.text)
        return self.client.get('/admin/api/jobs/'+result.json()['id']).json()

    def test_preview_then_publish_new_product_and_restart_restore(self):
        identifier=self.draft()
        result=self.upload(identifier)
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('Official synthetic',result.json()['chunks'][0]['text'])
        self.assertEqual(self.index_calls,[])
        self.assertFalse(self.workspace.pointer.exists())
        self.assertEqual(self.client.post(f'/admin/api/documents/drafts/{identifier}/publish',json={}).status_code,422)
        self.assertEqual(self.publish(identifier)['status'],'completed')
        self.assertEqual(len(self.index_calls),1)
        self.assertTrue(any(p['product_id']=='demo-device' for p in self.client.get('/products').json()))
        self.assertEqual(self.client.post('/sessions',json={'product_id':'demo-device'}).status_code,201)
        reopened=AdminWorkspace(self.workspace.root,self.workspace.directory)
        self.assertEqual(reopened.active()['id'],identifier)
        self.assertIn('已通过',reopened.inventory()['index_status'])

    def test_failure_keeps_old_version_and_stale_draft_cannot_overwrite(self):
        first=self.draft(); self.upload(first)
        stale=self.draft(); self.upload(stale)
        with patch.object(self.workspace,'publish',side_effect=TimeoutError('private vendor message')):
            failed=self.publish(first)
        self.assertEqual(failed['status'],'error')
        self.assertNotIn('private',json.dumps(failed))
        self.assertFalse(self.workspace.pointer.exists())
        self.assertEqual(self.publish(first)['status'],'completed')
        self.assertEqual(self.client.post(f'/admin/api/documents/drafts/{stale}/publish',json={'confirm_external':True}).status_code,409)
        self.assertEqual(self.workspace.active()['id'],first)

    def test_replacement_removes_old_document_chunks_and_rejects_rebinding(self):
        first=self.draft(); self.upload(first); self.publish(first)
        second=self.draft(); self.upload(second,text_pdf('Replacement version for synthetic manual.')); self.publish(second)
        chunks=read_json(self.workspace.active()['chunks_path'])
        matches=[c for c in chunks if c['metadata']['document_id']=='demo-manual']
        self.assertEqual(len(matches),1)
        self.assertIn('Replacement',matches[0]['text'])
        self.assertEqual(self.client.post('/admin/api/documents/drafts',json={**META,'product_id':'another-device'}).status_code,409)

    def test_auth_origin_paths_bad_pdf_and_blank_pdf(self):
        outsider=TestClient(self.app)
        self.assertEqual(outsider.post('/admin/api/documents/drafts',json=META).status_code,401)
        self.assertEqual(self.client.post('/admin/api/documents/drafts',json=META,headers={'Origin':'https://other.test'}).status_code,403)
        self.assertEqual(self.client.get('/admin/api/documents/drafts/not-an-id').status_code,404)
        identifier=self.draft()
        self.assertEqual(self.upload(identifier,b'not PDF').status_code,422)
        blank=BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=600,height=800); writer.write(blank)
        self.assertEqual(self.upload(identifier,blank.getvalue()).status_code,422)
        self.assertFalse(self.workspace.pointer.exists())
        self.assertEqual(self.index_calls,[])

    def test_evaluation_snapshot_reports_and_external_confirmation(self):
        session=self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{session}/messages',json={'text':'合成测试'})
        body={'session_id':session,'turns':[1],'mode':'inspect','notes':'人工预期'}
        with patch('supportpilot.providers.bailian.bailian',side_effect=AssertionError('不能调用模型')):
            response=self.client.post('/admin/api/evaluations',json=body)
        self.assertEqual(response.status_code,202,response.text)
        identifier=response.json()['id']
        report=self.client.get('/admin/api/evaluations/'+identifier).json()
        self.assertEqual(report['job']['status'],'completed')
        self.assertEqual(report['report']['results'][0]['evaluation']['judge_status'],'not_run')
        self.assertEqual(report['report']['notes'],'人工预期')
        self.assertEqual(self.client.get(f'/admin/api/evaluations/{identifier}/report').status_code,200)
        self.assertEqual(TestClient(self.app).get('/admin/api/evaluations/'+identifier).status_code,401)
        self.assertEqual(self.client.post('/admin/api/evaluations',json={**body,'mode':'judge'}).status_code,422)
        self.assertEqual(self.client.post('/admin/api/evaluations',json={**body,'turns':[2]}).status_code,422)
        self.client.delete('/sessions/'+session)
        self.assertEqual(self.client.get('/admin/api/evaluations/'+identifier).json()['report'],report['report'])

    def test_judge_init_failure_reported_and_restart_marks_interrupted(self):
        session=self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{session}/messages',json={'text':'合成测试'})
        with patch('supportpilot.providers.bailian.bailian',side_effect=TimeoutError('private')):
            result=self.client.post('/admin/api/evaluations',json={'session_id':session,'turns':[1],
                                   'mode':'judge','confirm_external':True}).json()
        report=self.client.get('/admin/api/evaluations/'+result['id']).json()['report']
        self.assertEqual(report['judge_status_counts'],{'error':1})
        self.assertNotIn('private',json.dumps(report))
        job=self.workspace.start_job('publish')
        restored=AdminWorkspace(self.workspace.root,self.workspace.directory)
        self.assertEqual(restored.job(job['id'])['status'],'interrupted')
        self.workspace.task_lock.release()

    def test_runtime_switch_preserves_inflight_snapshot_and_commit_failure(self):
        runtime=Runtime(); old=lambda *a,**k:['old']; new=lambda *a,**k:['new']
        runtime.resources=(object(),old)
        with self.assertRaises(OSError):
            runtime.publish_corpus(self.root/'chunks.json',new,lambda: (_ for _ in ()).throw(OSError()))
        self.assertIs(runtime.resources[1],old)
        runtime.publish_corpus(self.root/'chunks.json',new,lambda:None)
        self.assertIs(runtime.resources[1],new)
        self.assertEqual(old(),['old'])

    def test_index_publish_requires_exact_ids_not_only_count(self):
        from unittest.mock import Mock
        collection=Mock(); collection.count.return_value=1
        collection.get.return_value={'ids':[]}
        chunks=[{'id':'expected-id','text':'Synthetic','metadata':{}}]
        with patch('supportpilot.knowledge.rag_support.make_embedder',return_value=Mock()), \
             patch('supportpilot.knowledge.rag_support.open_collection',return_value=collection), \
             patch('supportpilot.knowledge.rag_support.index_chunks'):
            with self.assertRaises(ValueError):
                index_corpus(chunks,self.root/'chunks.json')


if __name__=='__main__': unittest.main()
