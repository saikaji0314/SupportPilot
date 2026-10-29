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

    def test_saved_evaluation_json_report_download_and_failures(self):
        session=self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{session}/messages',json={'text':'合成 JSON 报告测试'})
        body={'session_id':session,'turns':[1],'mode':'inspect','notes':'人工备注：中文保留'}
        with patch('supportpilot.providers.bailian.bailian',side_effect=AssertionError('不能调用模型')), \
             patch('supportpilot.evaluation.ragas_adapter.run_ragas',side_effect=AssertionError('不能调用 Ragas')):
            response=self.client.post('/admin/api/evaluations',json=body)
        self.assertEqual(response.status_code,202,response.text)
        identifier=response.json()['id']
        folder=self.workspace.folder('jobs',identifier)
        saved=(folder/'result.json').read_bytes()
        markdown=(folder/'report.md').read_bytes()
        files_before={p.name for p in folder.iterdir()}
        jobs_before={p.name:p.stat().st_mtime_ns for p in (self.workspace.directory/'jobs').iterdir()}
        sessions_before=self.client.get('/admin/api/sessions').json()
        url=f'/admin/api/evaluations/{identifier}/report.json'
        with patch('supportpilot.providers.bailian.bailian',side_effect=AssertionError('不能调用模型')), \
             patch('supportpilot.evaluation.ragas_adapter.run_ragas',side_effect=AssertionError('不能调用 Ragas')):
            result=self.client.get(url)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.content,saved)
        self.assertEqual(result.headers['content-type'],'application/json')
        self.assertIn('attachment',result.headers['content-disposition'])
        self.assertIn(f'filename="evaluation-{identifier}.json"',result.headers['content-disposition'])
        self.assertIn('no-store',result.headers['cache-control'])
        self.assertIn('人工备注：中文保留'.encode(),result.content)
        self.assertNotIn(b'\\u4eba',result.content)
        payload=json.loads(result.content.decode('utf-8'))
        self.assertEqual(payload['notes'],body['notes'])
        self.assertEqual(payload['results'][0]['evaluation']['judge_status'],'not_run')
        snapshot=self.client.get('/admin/api/evaluations/'+identifier)
        self.assertEqual(snapshot.status_code,200)
        self.assertEqual(snapshot.json()['report'],json.loads(saved.decode('utf-8')))
        legacy=self.client.get(f'/admin/api/evaluations/{identifier}/report')
        self.assertEqual(legacy.status_code,200)
        self.assertEqual(legacy.content,markdown)
        self.assertEqual({p.name for p in folder.iterdir()},files_before)
        self.assertEqual((folder/'result.json').read_bytes(),saved)
        self.assertEqual((folder/'report.md').read_bytes(),markdown)
        self.assertEqual(self.client.get('/admin/api/sessions').json(),sessions_before)
        self.assertEqual({p.name:p.stat().st_mtime_ns for p in (self.workspace.directory/'jobs').iterdir()},jobs_before)

        self.assertEqual(TestClient(self.app).get(url).status_code,401)
        other=TestClient(self.app); other.get('/auth/me')
        self.app.state.store.authenticate('other','Synthetic-only-456',register=True)
        self.assertEqual(other.post('/auth/login',json={'username':'other','password':'Synthetic-only-456'}).status_code,200)
        self.assertEqual(other.get(url).status_code,403)

        for bad in ('not-an-id','../etc/passwd','A'*32,'g'*32,'a'*31):
            self.assertEqual(self.client.get(f'/admin/api/evaluations/{bad}/report.json').status_code,404,bad)
        self.assertEqual(self.client.get('/admin/api/evaluations/'+'b'*32+'/report.json').status_code,404)

        publish=self.workspace.start_job('publish')
        self.workspace.run_job(publish['id'],lambda: {})
        self.assertEqual(self.client.get(f"/admin/api/evaluations/{publish['id']}/report.json").status_code,409)
        pending=self.workspace.start_job('evaluation')
        self.assertEqual(self.client.get(f"/admin/api/evaluations/{pending['id']}/report.json").status_code,409)
        self.workspace.run_job(pending['id'],lambda: (_ for _ in ()).throw(OSError('合成失败')))
        self.assertEqual(self.client.get(f"/admin/api/evaluations/{pending['id']}/report.json").status_code,409)

        (folder/'result.json').unlink()
        missing=self.client.get(url)
        self.assertEqual(missing.status_code,404)
        self.assertNotIn(str(self.root),missing.text)
        outside=self.root/'outside.json'; outside.write_text('{"secret":"不应返回"}',encoding='utf-8')
        (folder/'result.json').symlink_to(outside)
        escaped=self.client.get(url)
        self.assertEqual(escaped.status_code,404)
        self.assertNotIn('不应返回',escaped.text)
        (folder/'result.json').unlink()
        (folder/'result.json').write_bytes(saved)
        with patch('pathlib.Path.read_bytes',side_effect=OSError('/private/local/path')):
            broken=self.client.get(url)
        self.assertEqual(broken.status_code,503)
        self.assertNotIn('/private/local/path',broken.text)
        self.assertNotIn('private/local',broken.text)

    def test_ragas_uses_saved_snapshot_requires_consent_and_keeps_report(self):
        session=self.client.post('/sessions').json()['session_id']
        self.client.post(f'/sessions/{session}/messages',json={'text':'合成 Ragas 测试'})
        body={'session_id':session,'turns':[1],'mode':'ragas','notes':'人工备注不进入评分输入'}
        with patch('supportpilot.evaluation.ragas_adapter.run_ragas') as scorer:
            self.assertEqual(self.client.post('/admin/api/evaluations',json=body).status_code,422)
            scorer.assert_not_called()
            scorer.return_value={'status':'completed','metrics':[{'name':'faithfulness','status':'completed','value':.5}]}
            response=self.client.post('/admin/api/evaluations',json={**body,'confirm_external':True})
            self.assertEqual(response.status_code,202,response.text)
            self.assertNotIn(body['notes'],json.dumps(scorer.call_args.args[0]))
        identifier=response.json()['id']
        report=self.client.get('/admin/api/evaluations/'+identifier).json()['report']
        self.assertEqual(report['ragas_status_counts'],{'completed':1})
        self.assertEqual(report['results'][0]['evaluation']['ragas']['metrics'][0]['value'],.5)
        self.assertEqual(report['judge_status_counts'],{'not_run':1})
        self.assertEqual(self.client.get(f'/admin/api/evaluations/{identifier}/report').status_code,200)

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
