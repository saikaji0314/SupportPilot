"""管理入口：复用账号凭据；资料发布、会话轨迹与离线评测。"""
from collections import Counter
import json
import os
from hashlib import sha256

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from supportpilot.server.admin_support import DocumentInput, ReviewInput, index_corpus, read_json, write_json, review_selection
from supportpilot.config import admin_usernames as configured_admin_usernames


def document_inventory(root):
    """仅读取固定清单；片段存在不等于向量索引已经完整可用。"""
    manifest = json.loads((root / 'examples/rag/corpus.json').read_text(encoding='utf-8'))
    chunks_path = root / '.local/corpus/chunks.json'
    chunks = json.loads(chunks_path.read_text(encoding='utf-8')) if chunks_path.exists() else []
    counts = Counter((c['metadata']['document_id'], c['metadata'].get('source_revision')) for c in chunks)
    documents = []
    for relative in manifest['sources']:
        config_path = (root / relative).resolve()
        if not config_path.is_relative_to(root.resolve()):
            raise ValueError('资料清单路径越界')
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
        versions = [{'revision': revision or '未知', 'chunks': count}
                    for (doc, revision), count in counts.items() if doc == config['document_id']]
        documents.append({key: config[key] for key in ('document_id', 'product_id', 'source_url', 'scope_note')} |
                         {'versions': versions, 'chunk_count': sum(v['chunks'] for v in versions)})
    return {'documents': documents, 'index_status': '未检查向量索引；此处仅展示本地切块文件。'}


def install_admin(app, *, get_store, root, web, admin_usernames=None,
                  workspace=None, runner=None, indexer=None, judge_factory=None):
    configured = configured_admin_usernames() if admin_usernames is None else admin_usernames
    allowed = frozenset(name.strip().lower() for name in configured if name.strip())
    app.state.reserved_admin_names = allowed

    def admin_identity(request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD') and origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '请从管理页面发起请求。')
        owner = get_store().resolve_account(request.cookies.get('supportpilot_guest'))
        account = get_store().account_for_owner(owner) if owner else None
        if not account:
            raise HTTPException(401, '请先在用户端登录管理员账号。')
        if account['username'] not in allowed:
            raise HTTPException(403, '当前账号没有管理权限。')
        return account

    @app.get('/admin')
    def page():
        # 页面是公开静态壳；每一个数据接口都单独校验管理员凭据。
        return FileResponse(web / 'admin.html', headers={'Cache-Control': 'no-store'})

    @app.get('/admin/api/me')
    def me(account=Depends(admin_identity)):
        return account

    @app.get('/admin/api/documents')
    def documents(account=Depends(admin_identity)):
        try:
            return workspace.inventory()
        except (OSError, ValueError, KeyError, TypeError):
            raise HTTPException(503, '资料清单或切块文件暂不可读，请检查本地导入结果。') from None

    @app.get('/admin/api/sessions')
    def sessions(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                 account=Depends(admin_identity)):
        return get_store().admin_sessions(limit, offset)

    @app.get('/admin/api/sessions/{identifier}')
    def session(identifier: str, account=Depends(admin_identity)):
        try:
            return get_store().admin_session(identifier)
        except KeyError:
            raise HTTPException(404, '会话不存在或已删除。') from None

    def missing(work):
        try:
            return work()
        except (KeyError, FileNotFoundError):
            raise HTTPException(404, '记录不存在。') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post('/admin/api/documents/drafts', status_code=201)
    def create_draft(body: DocumentInput, account=Depends(admin_identity)):
        return missing(lambda: workspace.create_draft(body))

    @app.put('/admin/api/documents/drafts/{identifier}/pdf')
    async def upload_pdf(identifier: str, request: Request, account=Depends(admin_identity)):
        draft = missing(lambda: workspace.draft(identifier))
        if draft['status'] != 'awaiting_pdf':
            raise HTTPException(409, '该草稿已上传，请创建新草稿。')
        if request.headers.get('content-type', '').split(';')[0] != 'application/pdf':
            raise HTTPException(415, '请选择 PDF 文件。')
        if not workspace.lock.acquire(blocking=False):
            raise HTTPException(409, '资料正在处理，请稍后再试。')
        temporary = workspace.folder('drafts', identifier) / 'upload.tmp'
        try:
            if workspace.draft(identifier)['status'] != 'awaiting_pdf':
                raise HTTPException(409, '该草稿已上传。')
            size = 0
            with temporary.open('wb') as output:
                async for part in request.stream():
                    size += len(part)
                    if size > 20 * 1024 * 1024:
                        raise HTTPException(413, 'PDF 最大 20 MB。')
                    output.write(part)
            with temporary.open('rb') as source:
                if source.read(5) != b'%PDF-':
                    raise HTTPException(422, '文件不是有效 PDF。')
            os.replace(temporary, temporary.with_name('source.pdf'))
            try:
                await run_in_threadpool(workspace.prepare, identifier)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return workspace.preview(identifier)
        finally:
            temporary.unlink(missing_ok=True)
            workspace.lock.release()

    @app.get('/admin/api/documents/drafts/{identifier}')
    def preview(identifier: str, offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=20),
                account=Depends(admin_identity)):
        return missing(lambda: workspace.preview(identifier, offset, limit))

    @app.post('/admin/api/documents/drafts/{identifier}/publish', status_code=202)
    def publish(identifier: str, body: dict, background: BackgroundTasks, account=Depends(admin_identity)):
        if body.get('confirm_external') is not True:
            raise HTTPException(422, '入库会将文档正文发送至已配置嵌入服务，请明确确认。')
        draft = missing(lambda: workspace.draft(identifier))
        if draft['status'] != 'prepared' or draft['base_version'] != workspace.active()['id']:
            raise HTTPException(409, '草稿尚未准备好或在线版本已变化，请重新预览。')
        job = missing(lambda: workspace.start_job('publish', draft_id=identifier))
        background.add_task(workspace.run_job, job['id'],
                            lambda: workspace.publish(identifier, indexer or index_corpus, runner))
        return job

    @app.get('/admin/api/jobs')
    def jobs(account=Depends(admin_identity)):
        return workspace.jobs()

    @app.get('/admin/api/jobs/{identifier}')
    def job(identifier: str, account=Depends(admin_identity)):
        return missing(lambda: workspace.job(identifier))

    @app.post('/admin/api/evaluations', status_code=202)
    def evaluate(body: ReviewInput, background: BackgroundTasks, account=Depends(admin_identity)):
        if body.mode == 'judge' and not body.confirm_external:
            raise HTTPException(422, '模型评审会发送所选对话和检索正文，请明确确认。')
        saved = missing(lambda: get_store().admin_session(body.session_id))
        numbers = sorted(set(body.turns))
        if any(n < 1 or n > len(saved['turns']) for n in numbers):
            raise HTTPException(422, '请选择已有的会话轮次。')
        from supportpilot.evaluation.trajectory import normalize_record
        traces = []
        for number in numbers:
            record = saved['turns'][number-1]
            trace = normalize_record(record, record_id=f'{body.session_id}-turn-{number}')
            trace['source_sha256'] = sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            traces.append(trace)
        job = missing(lambda: workspace.start_job('evaluation', mode=body.mode, session_id=body.session_id))
        folder = workspace.folder('jobs', job['id'])
        try:
            write_json(folder / 'selection.json', {'mode':body.mode, 'notes':body.notes, 'traces':traces})
        except Exception:
            workspace.run_job(job['id'], lambda: (_ for _ in ()).throw(OSError('保存选择失败')))
            raise HTTPException(503, '选择快照未保存，请稍后重试。') from None
        def model():
            from supportpilot.providers.bailian import bailian
            return bailian()
        background.add_task(workspace.run_job, job['id'],
                            lambda: review_selection(folder, model_factory=judge_factory or model))
        return job

    @app.get('/admin/api/evaluations/{identifier}')
    def report(identifier: str, account=Depends(admin_identity)):
        job = missing(lambda: workspace.job(identifier))
        if job['kind'] != 'evaluation':
            raise HTTPException(404, '评测不存在。')
        return {'job':job, 'report':missing(lambda: read_json(workspace.folder('jobs', identifier) / 'result.json'))
                if job['status'] == 'completed' else None}

    @app.get('/admin/api/evaluations/{identifier}/report')
    def download(identifier: str, account=Depends(admin_identity)):
        job = missing(lambda: workspace.job(identifier))
        if job['kind'] != 'evaluation' or job['status'] != 'completed':
            raise HTTPException(409, '报告尚未生成。')
        return FileResponse(workspace.folder('jobs', identifier) / 'report.md', media_type='text/plain; charset=utf-8',
                            filename=f'evaluation-{identifier}.md', headers={'Cache-Control':'no-store'})
