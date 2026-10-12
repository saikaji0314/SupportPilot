const $ = id => document.getElementById(id);
let offset = 0, total = 0, pending = false, products = [];
function el(tag, text, cls) {
  const node = document.createElement(tag); if(text !== undefined) node.textContent = text;
  if(cls) node.className = cls; return node;
}
async function get(path) {
  const response = await fetch(path, {cache:'no-store'});
  const data = await response.json();
  if(!response.ok) {
    if(response.status === 401 || response.status === 403) {
      $('admin-content').hidden = true; $('trace').replaceChildren(); $('sessions').replaceChildren();
    }
    throw new Error(typeof data.detail === 'string' ? data.detail : '读取失败，请稍后刷新。');
  }
  return data;
}
function error(e) { $('admin-error').textContent = e.message; $('admin-error').hidden = false; }
function busy(value) {
  pending = value; $('refresh').disabled = value;
  $('previous').disabled = value || offset === 0; $('next').disabled = value || offset + 30 >= total;
  $('sessions').querySelectorAll('button').forEach(b => b.disabled = value);
}
function productName(id) { return products.find(p => p.product_id === id)?.name || id; }
async function list() {
  const data = await get(`/admin/api/sessions?limit=30&offset=${offset}`); total = data.total;
  $('session-count').textContent = `${total} 条`;
  $('page-label').textContent = total ? `${offset + 1}–${offset + data.items.length} / ${total}` : '暂无会话';
  $('sessions').replaceChildren(...data.items.map(s => {
    const row = el('tr');
    for(const text of [s.title, s.username, productName(s.product_id), s.closed ? '已结束' : '可继续']) row.append(el('td',text));
    const cell = el('td'), button = el('button','查看轨迹','secondary');
    button.dataset.session = s.id; button.dataset.title = s.title; cell.append(button); row.append(cell); return row;
  }));
}
function jsonSection(parent, label, value) {
  parent.append(el('h3',label), el('pre', value === undefined ? '此记录未保存该字段' : JSON.stringify(value,null,2)));
}
async function inspect(id, title) {
  if(pending) return; busy(true); $('admin-error').hidden = true; $('trace-panel').hidden = true;
  try {
    const data = await get(`/admin/api/sessions/${encodeURIComponent(id)}`);
    $('trace-title').textContent = title;
    $('trace').replaceChildren(...data.turns.map((r,i) => {
      const turn = el('details',undefined,'trace-turn'); turn.open = i === data.turns.length - 1;
      turn.append(el('summary',`第 ${i+1} 轮 · ${r.user_text}`));
      turn.append(el('h3','助手回复'),el('div',r.response?.text || '无回复','trace-text'));
      jsonSection(turn,'1 · 用户反馈',r.feedback);
      jsonSection(turn,'2 · 更新后的事实与检查',r.updated);
      jsonSection(turn,'3 · 检索查询',r.query);
      jsonSection(turn,'4 · 检索正文与来源',r.passages);
      jsonSection(turn,'5 · 校验与候选修正',{accepted:r.accepted,errors:r.errors,repair_attempts:r.repair_attempts || []});
      return turn;
    }));
    if(!data.turns.length) $('trace').append(el('p','这条会话还没有已保存的回复。'));
    const state = el('details',undefined,'trace-turn'); state.append(el('summary','最终会话状态')); jsonSection(state,'State',data.state); $('trace').append(state);
    $('trace-panel').hidden = false; $('trace-panel').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(e) {error(e);} finally {busy(false);}
}
async function refresh() {
  if(pending) return; busy(true); $('admin-error').hidden = true; $('trace-panel').hidden = true;
  try {
    await get('/admin/api/me');
    products = await get('/products');
    const data = await get('/admin/api/documents');
    $('index-note').textContent = data.index_status;
    $('documents').replaceChildren(...data.documents.map(d => {
      const card = el('article',undefined,'document-card');
      card.append(el('h3',productName(d.product_id)),el('small',d.document_id),el('span',`${d.chunk_count} 个本地片段`,'badge'),el('p',d.scope_note));
      d.versions.forEach(v => card.append(el('small',`原文版本 ${v.revision} · ${v.chunks} 个片段`)));
      try {const url = new URL(d.source_url); if(['http:','https:'].includes(url.protocol)) {
        const link = el('a','官方资料 ↗'); link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer'; card.append(link);
      }} catch {}
      return card;
    }));
    offset = 0; await list(); $('admin-content').hidden = false;
  } catch(e) {error(e);} finally {busy(false);}
}
$('sessions').addEventListener('click', e => {const b=e.target.closest('[data-session]'); if(b) inspect(b.dataset.session,b.dataset.title);});
async function page(delta) {if(pending) return; const old=offset; offset += delta; busy(true); try {await list();} catch(e){offset=old;error(e);} finally{busy(false);}}
$('previous').onclick = () => page(-30); $('next').onclick = () => page(30); $('refresh').onclick = refresh;
refresh();
