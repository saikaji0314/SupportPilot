"""管理端文件存储与任务：草稿、不可变语料快照及离线评测报告。"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


class DocumentInput(BaseModel):
    document_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,79}$')
    product_id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{1,79}$')
    name: str = Field(min_length=1, max_length=80)
    variant: str = Field(min_length=1, max_length=120)
    source_url: str = Field(max_length=500)
    scope_note: str = Field(min_length=1, max_length=600)
    chunk_size: int = Field(default=1200, ge=300, le=3000)
    overlap: int = Field(default=200, ge=0, le=1000)

    @field_validator('name', 'variant', 'scope_note')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('资料说明不能为空')
        return value.strip()

    @field_validator('source_url')
    @classmethod
    def official_link(cls, value):
        from urllib.parse import urlsplit
        url = urlsplit(value)
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            raise ValueError('请提供有效的资料来源链接')
        return value


class ReviewInput(BaseModel):
    session_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    turns: list[int] = Field(min_length=1, max_length=12)
    mode: str = Field(pattern=r'^(inspect|judge)$')
    notes: str = Field(default='', max_length=2000)
    confirm_external: bool = False


class AdminWorkspace:
    def __init__(self, root, directory=None):
        self.root = Path(root)
        self.directory = Path(directory) if directory else self.root / '.local/admin'
        self.lock = Lock()
        self.task_lock = Lock()
        self.pointer = self.directory / 'active.json'
        # 中断任务不能在重启后被误显示为仍运行，也不自动重发付费请求。
        for path in (self.directory / 'jobs').glob('*/job.json'):
            job = read_json(path)
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', error_type='ServiceRestart')
                write_json(path, job)

    def folder(self, category, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise KeyError(identifier)
        path = self.directory / category / identifier
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
            raise KeyError(identifier)
        return path

    def active(self):
        if self.pointer.exists():
            identifier = read_json(self.pointer)['id']
            folder = self.folder('corpora', identifier)
            result = read_json(folder / 'manifest.json')
            result['chunks_path'] = folder / 'chunks.json'
            return result
        products = read_json(self.root / 'examples/rag/products.json')
        docs = [read_json(self.root / relative) for relative in read_json(self.root / 'examples/rag/corpus.json')['sources']]
        return {'id': 'baseline', 'products': products, 'documents': docs,
                'chunks_path': self.root / '.local/corpus/chunks.json', 'collection': None}

    def inventory(self):
        active = self.active()
        chunks = read_json(active['chunks_path']) if active['chunks_path'].exists() else []
        counts = Counter((c['metadata']['document_id'], c['metadata'].get('source_revision')) for c in chunks)
        docs = []
        for config in active['documents']:
            versions = [{'revision': rev or '未知', 'chunks': count} for (doc, rev), count in counts.items()
                        if doc == config['document_id']]
            docs.append({key: config[key] for key in ('document_id', 'product_id', 'source_url', 'scope_note')} |
                        {'versions': versions, 'chunk_count': sum(v['chunks'] for v in versions)})
        return {'documents': docs, 'active_version': active['id'],
                'index_status': '当前版本已通过发布时索引完整性检查。' if active['collection'] else '基线版本：此处仅统计切块，尚未通过管理端发布检查。'}

    def create_draft(self, metadata):
        if metadata.overlap >= metadata.chunk_size:
            raise ValueError('重叠长度必须小于片段长度')
        current = self.active()
        doc = next((d for d in current['documents'] if d['document_id'] == metadata.document_id), None)
        if doc and doc['product_id'] != metadata.product_id:
            raise ValueError('已有文档 ID 不能改绑其他产品，请使用新文档 ID')
        identifier = uuid4().hex
        draft = {'id': identifier, 'metadata': metadata.model_dump(), 'status': 'awaiting_pdf',
                 'base_version': current['id']}
        write_json(self.folder('drafts', identifier) / 'draft.json', draft)
        return draft

    def draft(self, identifier):
        return read_json(self.folder('drafts', identifier) / 'draft.json')

    def prepare(self, identifier):
        from pypdf import PdfReader
        from supportpilot.retrieval import chunk_pages
        folder = self.folder('drafts', identifier)
        draft = self.draft(identifier)
        path = folder / 'source.pdf'
        try:
            reader = PdfReader(path)
            if reader.is_encrypted or len(reader.pages) > 500:
                raise ValueError('仅接受未加密、最多 500 页的文本型 PDF')
            pages, size = [], 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                size += len(text)
                if size > 2_000_000:
                    raise ValueError('提取文字超过本地演示上限')
                pages.append({'page': number, 'text': text})
            if not any(p['text'].strip() for p in pages):
                raise ValueError('未提取到文字，请使用文本型 PDF；扫描件需先做 OCR')
            meta = {key: draft['metadata'][key] for key in ('document_id','product_id','source_url','scope_note')}
            meta['source_revision'] = sha256(path.read_bytes()).hexdigest()[:12]
            chunks = chunk_pages(pages, meta, chunk_size=draft['metadata']['chunk_size'], overlap=draft['metadata']['overlap'])
            if len(chunks) > 5000:
                raise ValueError('片段超过 5000 条，请调整资料范围或切块大小')
            write_json(folder / 'chunks.json', chunks)
            draft.update(status='prepared', page_count=len(pages), blank_pages=sum(not p['text'].strip() for p in pages),
                         chunk_count=len(chunks), revision=meta['source_revision'])
        except Exception as exc:
            draft.update(status='error', error_type=type(exc).__name__)
            write_json(folder / 'draft.json', draft)
            if isinstance(exc, ValueError):
                raise
            raise ValueError('PDF 解析失败，请确认文件有效且未加密') from None
        write_json(folder / 'draft.json', draft)
        return draft

    def preview(self, identifier, offset=0, limit=10):
        draft = self.draft(identifier)
        chunks = read_json(self.folder('drafts', identifier) / 'chunks.json') if draft['status'] in ('prepared','published') else []
        return {**draft, 'chunks': chunks[offset:offset+limit], 'offset': offset}

    def jobs(self):
        return [read_json(path) for path in sorted((self.directory / 'jobs').glob('*/job.json'), key=lambda p:p.stat().st_mtime, reverse=True)][:50]

    def job(self, identifier):
        return read_json(self.folder('jobs', identifier) / 'job.json')

    def start_job(self, kind, **fields):
        if not self.task_lock.acquire(blocking=False):
            raise ValueError('已有入库或评测任务运行，请等待完成')
        identifier = uuid4().hex
        job = {'id':identifier, 'kind':kind, 'status':'queued', **fields}
        try:
            write_json(self.folder('jobs', identifier) / 'job.json', job)
        except Exception:
            self.task_lock.release()
            raise
        return job

    def run_job(self, identifier, work):
        job = self.job(identifier)
        try:
            job['status'] = 'running'
            write_json(self.folder('jobs', identifier) / 'job.json', job)
            job.update(work(), status='completed')
        except Exception as exc:
            job.update(status='error', error_type=type(exc).__name__)
        finally:
            try:
                write_json(self.folder('jobs', identifier) / 'job.json', job)
            finally:
                self.task_lock.release()

    def publish(self, identifier, indexer, runner):
        draft = self.draft(identifier)
        if draft['status'] != 'prepared':
            raise ValueError('请先完成切块预览')
        active = self.active()
        if active['id'] != draft['base_version']:
            raise ValueError('在线版本已变化，请重新上传并预览，避免覆盖其他发布')
        metadata = draft['metadata']
        chunks = read_json(active['chunks_path']) if active['chunks_path'].exists() else []
        chunks = [c for c in chunks if c['metadata']['document_id'] != metadata['document_id']]
        chunks += read_json(self.folder('drafts', identifier) / 'chunks.json')
        if len(set(c['id'] for c in chunks)) != len(chunks):
            raise ValueError('片段 ID 冲突')
        folder = self.folder('corpora', identifier)
        write_json(folder / 'chunks.json', chunks)
        # 完整的新集合及 retriever 构建成功才进入发布事务。
        collection_name, retrieve = indexer(chunks, folder / 'chunks.json')
        products = deepcopy(active['products'])
        existing = next((p for p in products if p['product_id'] == metadata['product_id']), None)
        if existing is None:
            products.append({'product_id':metadata['product_id'], 'name':metadata['name'], 'variant':metadata['variant'],
                             'source_url':metadata['source_url'], 'questions':['如何开始使用这个设备？','设备出现异常，应该先确认哪些信息？']})
        docs = [d for d in active['documents'] if d['document_id'] != metadata['document_id']]
        docs.append({k: metadata[k] for k in ('document_id','product_id','source_url','scope_note')})
        manifest = {'id':identifier, 'products':products, 'documents':docs, 'collection':collection_name}
        write_json(folder / 'manifest.json', manifest)
        with self.lock:
            if self.active()['id'] != draft['base_version']:
                raise ValueError('发布版本冲突')
            # 同一进程中与 Runtime 切换串行；正在执行的轮次持有旧快照仍可完成。
            if hasattr(runner, 'publish_corpus'):
                runner.publish_corpus(folder / 'chunks.json', retrieve,
                                      lambda: write_json(self.pointer, {'id':identifier}))
            else:
                write_json(self.pointer, {'id':identifier})
        draft['status'] = 'published'
        warning = None
        try:
            write_json(self.folder('drafts', identifier) / 'draft.json', draft)
        except OSError:
            warning = '版本已发布，但草稿状态文件未更新；以在线版本为准。'
        return {'active_version':identifier, 'collection':collection_name, 'chunk_count':len(chunks), 'warning':warning}


def index_corpus(chunks, path):
    from supportpilot.rag_support import make_embedder, open_collection, index_chunks
    from supportpilot.chat_support import retriever_for_collection
    embedder = make_embedder()
    collection = open_collection(chunks, embedder)
    index_chunks(collection, embedder, chunks)
    expected = {c['id'] for c in chunks}
    actual = set()
    for start in range(0, len(chunks), 100):
        actual.update(collection.get(ids=[c['id'] for c in chunks[start:start+100]], include=[])['ids'])
    if actual != expected or collection.count() != len(chunks):
        raise ValueError('索引尚未完整，不发布')
    return collection.name, retriever_for_collection(collection, embedder, chunks)


def review_selection(folder, *, model_factory=None):
    from supportpilot.eval_demo import run_review
    from supportpilot.evaluation import RUBRIC
    from supportpilot.trajectory import render_trace
    selection = read_json(folder / 'selection.json')
    results, counts = [], Counter()
    model, initialization_error = None, None
    if selection['mode'] == 'judge':
        try:
            model = model_factory()
        except Exception as exc:
            initialization_error = type(exc).__name__
    for trace in selection['traces']:
        evaluation = run_review(trace, model=model)
        if initialization_error:
            evaluation.update(judge_status='error', error_type=initialization_error)
        counts[evaluation['judge_status']] += 1
        results.append({'trace':trace, 'evaluation':evaluation})
    report = {'mode':selection['mode'], 'notes':selection['notes'], 'rubric':RUBRIC,
              'evaluator_code_sha256':sha256((Path(__file__).parent / 'evaluation.py').read_bytes()).hexdigest(),
              'judge_status_counts':dict(counts), 'results':results}
    write_json(folder / 'result.json', report)
    content = '# 管理端评测报告\n\n仅评审保存的回复，不重跑客服。程序检查不保证语义正确。\n\n'
    content += f"模式：{selection['mode']}；选择轮数：{len(results)}。\n\n"
    notes = json.dumps({'notes':selection['notes'], 'judge_status_counts':dict(counts),
                        'evaluator_code_sha256':report['evaluator_code_sha256']}, ensure_ascii=False, indent=2)
    fence = '`' * max(3, max((len(s)+1 for s in re.findall(r'`+', notes)), default=3))
    content += f'## 备注与评审状态\n\n{fence}json\n{notes}\n{fence}\n\n'
    for item in results:
        content += render_trace(item['trace'], item['evaluation']) + '\n\n'
    (folder / 'report.md').write_text(content, encoding='utf-8')
    return {'judge_status_counts':dict(counts), 'turn_count':len(results)}
