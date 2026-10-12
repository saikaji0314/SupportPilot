const $ = id => document.getElementById(id);
let offset = 0, total = 0, pending = false, products = [];
let draftId = null, draftOffset = 0, draftCount = 0, inspectedSession = null, timer = null;
let jobStatuses = new Map();
function el(tag, text, cls) {
  const node = document.createElement(tag); if(text !== undefined) node.textContent = text;
  if(cls) node.className = cls; return node;
}
async function get(path, options = {}) {
  const response = await fetch(path, {cache:'no-store', ...options});
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
  $('import-form').querySelectorAll('button,input').forEach(b => b.disabled = value);
  $('eval-form').querySelectorAll('button,input,textarea,select').forEach(b => b.disabled = value);
  $('publish').disabled = value || !$('publish-consent').checked || !draftId;
}
function post(path, body) {return get(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
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
    inspectedSession = id;
    $('eval-notes').value = ''; $('judge-consent').checked = false;
    $('trace-title').textContent = title;
    $('trace').replaceChildren(...data.turns.map((r,i) => {
      const turn = el('details',undefined,'trace-turn'); turn.open = i === data.turns.length - 1;
      turn.append(el('summary',`第 ${i+1} 轮 · ${r.user_text}`));
      const label=el('label',undefined,'consent'), check=el('input'); check.type='checkbox'; check.value=i+1; check.dataset.turn=i+1;
      label.append(check,document.createTextNode('将本轮选入评测')); turn.append(label);
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
    $('known-products').replaceChildren(...products.map(p=>{const option=el('option');option.value=p.product_id;option.label=p.name;return option;}));
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
    offset = 0; await list(); await loadJobs(); $('admin-content').hidden = false;
  } catch(e) {error(e);} finally {busy(false);}
}
$('sessions').addEventListener('click', e => {const b=e.target.closest('[data-session]'); if(b) inspect(b.dataset.session,b.dataset.title);});
async function page(delta) {if(pending) return; const old=offset; offset += delta; busy(true); try {await list();} catch(e){offset=old;error(e);} finally{busy(false);}}
$('previous').onclick = () => page(-30); $('next').onclick = () => page(30); $('refresh').onclick = refresh;
const statuses={queued:'等待执行',running:'运行中',completed:'已完成',error:'执行失败',interrupted:'服务重启中断'};
async function loadJobs() {
  const jobs=await get('/admin/api/jobs');
  $('jobs').replaceChildren(...jobs.map(job=>{
    const row=el('div',undefined,'job-row');
    row.append(el('span',`${job.kind==='publish'?'入库发布':'离线评测'} · ${statuses[job.status] || job.status}`),el('small',job.id.slice(0,8)));
    if(job.error_type) row.append(el('span',job.error_type,'job-error'));
    if(job.warning) row.append(el('span',job.warning,'job-error'));
    if(job.judge_status_counts) row.append(el('small',`裁判状态：${JSON.stringify(job.judge_status_counts)}`));
    if(job.kind==='evaluation'&&job.status==='completed') {const b=el('button','查看报告','secondary');b.dataset.report=job.id;row.append(b);}
    if(job.kind==='publish'&&['error','interrupted'].includes(job.status)) {const b=el('button','重新预览草稿','secondary');b.dataset.draft=job.draft_id;row.append(b);}
    return row;
  }));
  if(!jobs.length) $('jobs').append(el('p','还没有任务。'));
  const published = jobs.some(j=>j.kind==='publish'&&j.status==='completed'&&['queued','running'].includes(jobStatuses.get(j.id)));
  jobStatuses=new Map(jobs.map(j=>[j.id,j.status]));
  clearTimeout(timer);
  if(jobs.some(j=>['queued','running'].includes(j.status))) timer=setTimeout(()=>loadJobs().catch(error),1800);
  if(published && !pending) await refresh();
}
async function draftPreview() {
  const data=await get(`/admin/api/documents/drafts/${draftId}?offset=${draftOffset}`);
  draftCount=data.chunk_count || 0;
  $('draft-summary').textContent=`${data.metadata.name} / ${data.metadata.document_id} · ${data.page_count} 页 · ${draftCount} 个片段 · ${data.blank_pages} 页未提取到文字 · 原文版本 ${data.revision}`;
  $('draft-chunks').replaceChildren(...data.chunks.map(c=>{const block=el('details',undefined,'trace-turn');block.append(el('summary',`PDF 第 ${c.metadata.page} 页 · 片段 ${c.metadata.section+1}`),el('pre',c.text));return block;}));
  $('draft-page').textContent=`${draftOffset+1}–${Math.min(draftOffset+10,draftCount)} / ${draftCount}`;
  $('draft-previous').disabled=draftOffset===0; $('draft-next').disabled=draftOffset+10>=draftCount;
  $('draft-panel').hidden=false;
}
$('import-product').addEventListener('change',()=>{
  const p=products.find(p=>p.product_id===$('import-product').value);if(p){$('import-name').value=p.name;$('import-variant').value=p.variant;}
});
$('import-form').addEventListener('submit',async e=>{
  e.preventDefault(); if(pending)return; const file=$('import-pdf').files[0];
  if(!file || file.size>20*1024*1024){error(new Error('请选择不超过 20 MB 的 PDF。'));return;}
  busy(true);$('admin-error').hidden=true;draftId=null;$('draft-panel').hidden=true;$('publish-consent').checked=false;
  try {
    const draft=await post('/admin/api/documents/drafts',{
      product_id:$('import-product').value,document_id:$('import-document').value,name:$('import-name').value,
      variant:$('import-variant').value,source_url:$('import-url').value,scope_note:$('import-scope').value,
      chunk_size:Number($('import-size').value),overlap:Number($('import-overlap').value)});
    await get(`/admin/api/documents/drafts/${draft.id}/pdf`,{method:'PUT',headers:{'Content-Type':'application/pdf'},body:file});
    draftId=draft.id;draftOffset=0;await draftPreview();
  }catch(e){error(e);}finally{busy(false);}
});
$('draft-previous').onclick=async()=>{if(pending||draftOffset===0)return;draftOffset-=10;try{await draftPreview();}catch(e){error(e);}};
$('draft-next').onclick=async()=>{if(pending||draftOffset+10>=draftCount)return;draftOffset+=10;try{await draftPreview();}catch(e){error(e);}};
$('publish-consent').onchange=()=>{$('publish').disabled=pending||!draftId||!$('publish-consent').checked;};
$('publish').onclick=async()=>{
  if(pending||!draftId||!$('publish-consent').checked)return;busy(true);
  try{await post(`/admin/api/documents/drafts/${draftId}/publish`,{confirm_external:true});draftId=null;$('publish-consent').checked=false;await loadJobs();}
  catch(e){error(e);}finally{busy(false);}
};
$('eval-mode').onchange=()=>{$('judge-consent-row').hidden=$('eval-mode').value!=='judge';$('judge-consent').checked=false;};
$('eval-form').addEventListener('submit',async e=>{
  e.preventDefault();if(pending||!inspectedSession)return;
  const turns=Array.from($('trace').querySelectorAll('[data-turn]:checked')).map(c=>Number(c.value));
  const mode=$('eval-mode').value;
  if(!turns.length || turns.length>12){error(new Error('请选择 1–12 个轮次。'));return;}
  if(mode==='judge'&&!$('judge-consent').checked){error(new Error('模型评审需勾选发送与费用确认。'));return;}
  busy(true);$('admin-error').hidden=true;
  try{await post('/admin/api/evaluations',{session_id:inspectedSession,turns,mode,notes:$('eval-notes').value,confirm_external:$('judge-consent').checked});await loadJobs();$('jobs').scrollIntoView({behavior:'smooth'});}
  catch(e){error(e);}finally{busy(false);}
});
$('jobs').addEventListener('click',async e=>{
  const draft=e.target.closest('[data-draft]');
  if(draft && !pending) {
    busy(true);$('publish-consent').checked=false;
    try {draftId=draft.dataset.draft;draftOffset=0;await draftPreview();$('draft-panel').scrollIntoView({behavior:'smooth'});}
    catch(e){draftId=null;error(e);}finally{busy(false);}return;
  }
  const button=e.target.closest('[data-report]');if(!button||pending)return;busy(true);
  try {
    const data=await get(`/admin/api/evaluations/${button.dataset.report}`), report=data.report;
    $('report-download').href=`/admin/api/evaluations/${button.dataset.report}/report`;
    $('report-content').replaceChildren(el('p',`评测方式：${report.mode} · 选择轮数：${report.results.length}`),el('p',`人工备注：${report.notes || '无'}`));
    report.results.forEach(item=>{
      const block=el('details',undefined,'trace-turn');block.open=true;block.append(el('summary',item.trace.payload.user_text));
      const evaluation=item.evaluation, names={grounding:'正文支持',preconditions:'操作前提',history:'会话历史'}, verdicts={pass:'通过',fail:'未通过',unclear:'无法判断',not_applicable:'不适用'};
      block.append(el('p',`程序检查：${evaluation.rules?.status==='completed' ? (evaluation.rules.errors.length ? '发现问题' : '通过有限规则') : '未完成'} · 模型评审状态：${evaluation.judge_status}`));
      (evaluation.review?.items || []).forEach(r=>block.append(el('p',`${names[r.criterion_id] || r.criterion_id}：${verdicts[r.verdict] || r.verdict}。${r.reason}`)));
      jsonSection(block,'评审详情（无效评审不计入成绩）',evaluation);$('report-content').append(block);
    });
    $('report-panel').hidden=false;$('report-panel').scrollIntoView({behavior:'smooth'});
  }catch(e){error(e);}finally{busy(false);}
});
refresh();
