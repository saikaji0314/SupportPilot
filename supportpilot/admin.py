"""只读管理入口：复用账号凭据，授权名单由启动环境指定。"""
from collections import Counter
import json
import os

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse


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


def install_admin(app, *, get_store, root, web, admin_usernames=None):
    configured = (os.getenv('SUPPORTPILOT_ADMIN_USERS', '').split(',')
                  if admin_usernames is None else admin_usernames)
    allowed = frozenset(name.strip().lower() for name in configured if name.strip())
    app.state.reserved_admin_names = allowed

    def admin_identity(request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
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
            return document_inventory(root)
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
