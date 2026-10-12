const $ = (id) => document.getElementById(id);
let sessionId = null, busy = false, closed = false, failedText = null;
let products = [], activeProduct = null;
let deleteTarget = null;
const welcome = $('welcome').cloneNode(true);
const kindNames = {answer:'产品解答',ask_user:'需要确认',recommend_check:'下一项检查',resolved:'问题已恢复',handoff:'建议人工协助'};

async function request(path, body, method) {
  const response = await fetch(path, {method: method || (body === undefined ? 'GET' : 'POST'),
    headers: {'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请检查输入后重试。');
  return data;
}
function setBusy(value) {
  busy = value;
  $('busy').hidden = !value;
  $('send').disabled = value || closed || !sessionId;
  $('message').disabled = value || closed;
  $('new-chat').disabled = value;
  $('retry').disabled = value;
  $('product-select').disabled = value || !products.length;
  $('history-list').querySelectorAll('button').forEach(button => button.disabled = value);
  $('open-auth').disabled = value; $('logout').disabled = value;
  $('state-label').textContent = value ? '处理中' : closed ? '本次会话已结束' : '准备就绪';
}
function showError(error) {
  $('error-text').textContent = error.message || '连接中断，请确认服务仍在运行。';
  $('error').hidden = false;
  $('retry').hidden = !failedText;
}
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function addMessage(role, text, kind) {
  $('welcome')?.remove();
  const wrapper = element('article', undefined, `message ${role}`);
  wrapper.append(element('div', role === 'user' ? '你' : `SUPPORTPILOT · ${kindNames[kind] || '售后助手'}`, 'message-label'));
  wrapper.append(element('div', text, 'message-text'));
  $('messages').append(wrapper);
  return wrapper;
}
function addSources(wrapper, sources) {
  const container = element('div', undefined, 'sources');
  for (const source of sources) {
    const details = element('details');
    details.append(element('summary', `${source.title} · PDF 第 ${source.page ?? '?'} 页`));
    details.append(element('pre', source.text));
    try {
      const url = new URL(source.url);
      if (url.protocol === 'https:' || url.protocol === 'http:') {
        const link = element('a', '打开官方资料 ↗');
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; details.append(link);
      }
    } catch {}
    container.append(details);
  }
  wrapper.append(container);
}
function addSummary(wrapper, summary) {
  if (!summary) return;
  const details = element('details', undefined, 'summary');
  details.append(element('summary', '查看本次记录摘要'));
  const results = {unknown:'结果未确认',not_done:'尚未执行',passed:'检查正常／达到预期',failed:'检查异常／未达到预期'};
  details.append(element('p', ['已记录的信息', ...summary.facts, '', '检查与反馈',
    ...summary.checks.map((c,i) => `${i+1}. ${c.text}\n结果：${results[c.result] || c.result}`)].join('\n')));
  wrapper.append(details);
}
async function startSession() {
  setBusy(true); failedText = null; $('error').hidden = true;
  try {
    const selected = products.find(p => p.product_id === $('product-select').value);
    const data = await request('/sessions', {product_id: selected.product_id});
    sessionId = data.session_id; closed = false;
    showProduct(selected);
    localStorage.setItem('supportpilot_session', sessionId);
    $('message').value = ''; $('ended').hidden = true;
    await refreshHistory();
  } catch(error) {
    if (activeProduct) $('product-select').value = activeProduct.product_id;
    showError(error);
  }
  finally { setBusy(false); }
}
function showProduct(selected) {
    activeProduct = selected;
    $('product-select').value = selected.product_id;
    $('product-name').textContent = selected.name;
    $('product-variant').textContent = selected.variant;
    $('manual').href = selected.source_url;
    $('device-art').hidden = selected.name !== 'Archer AX55';
    const intro = welcome.cloneNode(true);
    intro.querySelectorAll('[data-question]').forEach((button, i) => {
      button.dataset.question = selected.questions[i];
      button.textContent = selected.questions[i];
    });
    $('messages').replaceChildren(intro);
}
async function refreshHistory() {
  const sessions = await request('/sessions');
  $('history-list').replaceChildren(...sessions.map(s => {
    const product = products.find(p => p.product_id === s.product_id);
    const button = element('button');
    button.append(element('span', s.title || '新会话', 'history-title'),
      element('span', `${product?.name || s.product_id} · ${s.closed ? '已结束' : '可继续'}`, 'history-meta'));
    button.title = s.title || '新会话';
    button.type = 'button'; button.dataset.session = s.id;
    button.classList.toggle('selected', s.id === sessionId);
    const row = element('div', undefined, 'history-row');
    const remove = element('button', '删除');
    remove.type = 'button'; remove.dataset.delete = s.id;
    remove.setAttribute('aria-label', `删除会话：${s.title || '新会话'}`);
    row.append(button, remove);
    return row;
  }));
}
function showEnded(kind) {
  $('ended').textContent = kind === 'resolved' ? '本次问题已恢复。如有其他问题，请新建会话。' : '建议联系人工支持。本页面未提交工单，可展开记录摘要供沟通参考。';
  $('ended').hidden = false;
}
async function restoreSession(identifier) {
  setBusy(true); $('error').hidden = true;
  try {
    const data = await request(`/sessions/${identifier}`);
    const product = products.find(p => p.product_id === data.product_id);
    if (!product) throw new Error('该会话产品当前不可用。');
    showProduct(product);
    sessionId = data.session_id; closed = data.closed; failedText = null;
    $('message').value = ''; $('ended').hidden = true;
    for (const turn of data.turns) {
      addMessage('user', turn.user_text);
      const wrapper = addMessage('assistant', turn.response.text, turn.response.kind);
      addSources(wrapper, turn.sources); addSummary(wrapper, turn.summary);
    }
    if (closed && data.turns.length) showEnded(data.turns.at(-1).response.kind);
    localStorage.setItem('supportpilot_session', sessionId);
    await refreshHistory();
  } catch(error) {
    if (activeProduct) $('product-select').value = activeProduct.product_id;
    showError(error);
  } finally {
    setBusy(false); $('messages').scrollTop = $('messages').scrollHeight;
  }
}
async function send(text, retry = false) {
  if (busy || closed || !sessionId || !text.trim()) return;
  if (!retry) addMessage('user', text);
  $('message').value = ''; $('error').hidden = true; failedText = text; setBusy(true);
  $('messages').scrollTop = $('messages').scrollHeight;
  try {
    const data = await request(`/sessions/${sessionId}/messages`, {text});
    const wrapper = addMessage('assistant', data.response.text, data.response.kind);
    addSources(wrapper, data.sources); addSummary(wrapper, data.summary);
    failedText = null; closed = data.closed;
    if (closed) {
      showEnded(data.response.kind);
    }
    await refreshHistory();
  } catch(error) { showError(error); }
  finally { setBusy(false); $('messages').scrollTop = $('messages').scrollHeight; if (!closed) $('message').focus(); }
}
$('composer').addEventListener('submit', e => {e.preventDefault(); send($('message').value.trim());});
$('message').addEventListener('keydown', e => {if(e.key === 'Enter' && !e.shiftKey && !e.isComposing){e.preventDefault(); $('composer').requestSubmit();}});
$('messages').addEventListener('click', e => {const button = e.target.closest('[data-question]'); if(button && !busy){$('message').value = button.dataset.question; $('message').focus();}});
$('new-chat').addEventListener('click', startSession);
$('product-select').addEventListener('change', startSession);
$('history-list').addEventListener('click', e => {
  if (busy) return;
  const remove = e.target.closest('[data-delete]');
  if (remove) {deleteTarget = remove.dataset.delete; $('delete-dialog').showModal(); return;}
  const button = e.target.closest('[data-session]'); if(button) restoreSession(button.dataset.session);
});
$('cancel-delete').addEventListener('click', () => $('delete-dialog').close());
$('confirm-delete').addEventListener('click', async () => {
  if (busy || !deleteTarget) return;
  $('delete-dialog').close(); setBusy(true);
  try {
    const result = await request(`/sessions/${deleteTarget}`, undefined, 'DELETE');
    const wasCurrent = deleteTarget === sessionId;
    if (wasCurrent) {sessionId = null; closed = false; failedText = null; localStorage.removeItem('supportpilot_session');}
    await refreshHistory();
    if (wasCurrent) await chooseHistory();
    if (!result.logs_removed) showError(new Error('会话已删除，但部分本地诊断日志未清理成功。'));
  } catch(error) {showError(error);}
  finally {deleteTarget = null; setBusy(false);}
});
$('open-auth').addEventListener('click', () => {$('auth-error').hidden = true; $('auth-dialog').showModal();});
$('cancel-auth').addEventListener('click', () => {$('password').value = ''; $('auth-dialog').close();});
$('auth-dialog').addEventListener('close', () => {$('password').value = '';});
async function updateIdentity() {
  const data = await request('/auth/me');
  $('account-label').textContent = data.authenticated ? data.username : '临时访客';
  $('open-auth').hidden = data.authenticated; $('logout').hidden = !data.authenticated;
}
async function chooseHistory() {
  const sessions = await request('/sessions');
  const remembered = localStorage.getItem('supportpilot_session');
  const target = sessions.find(s => s.id === remembered) || sessions[0];
  return target ? restoreSession(target.id) : startSession();
}
$('auth-form').addEventListener('submit', async e => {
  e.preventDefault(); if (busy) return;
  setBusy(true); $('auth-error').hidden = true;
  const buttons = $('auth-form').querySelectorAll('button'); buttons.forEach(b => b.disabled = true);
  try {
    await request(`/auth/${e.submitter?.value || 'login'}`, {
      username: $('username').value, password: $('password').value, migrate_guest: $('migrate-guest').checked});
    $('password').value = ''; $('auth-dialog').close();
    sessionId = null; failedText = null;
    await updateIdentity(); await chooseHistory();
  } catch(error) {$('auth-error').textContent = error.message; $('auth-error').hidden = false;}
  finally {buttons.forEach(b => b.disabled = false); setBusy(false);}
});
$('logout').addEventListener('click', async () => {
  if (busy) return; setBusy(true);
  try {
    await request('/auth/logout', {});
    sessionId = null; closed = false; failedText = null; localStorage.removeItem('supportpilot_session');
    await updateIdentity(); await startSession();
  } catch(error) {showError(error);} finally {setBusy(false);}
});
$('retry').addEventListener('click', () => {if(failedText) send(failedText, true);});
setBusy(true);
request('/products').then(async data => {
  products = data;
  $('product-select').replaceChildren(...products.map(p => {
    const option = element('option', `${p.name} · US V1`);
    option.value = p.product_id;
    return option;
  }));
  await updateIdentity();
  return chooseHistory();
}).catch(error => {showError(error); setBusy(false);});
