const $ = (id) => document.getElementById(id);
let sessionId = null, busy = false, closed = false, failedText = null;
let products = [], activeProduct = null;
const welcome = $('welcome').cloneNode(true);
const kindNames = {answer:'产品解答',ask_user:'需要确认',recommend_check:'下一项检查',resolved:'问题已恢复',handoff:'建议人工协助'};

async function request(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
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
    activeProduct = selected;
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
    $('message').value = ''; $('ended').hidden = true;
  } catch(error) {
    if (activeProduct) $('product-select').value = activeProduct.product_id;
    showError(error);
  }
  finally { setBusy(false); }
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
      $('ended').textContent = data.response.kind === 'resolved' ? '本次问题已恢复。如有其他问题，请新建会话。' : '建议联系人工支持。本页面未提交工单，可展开记录摘要供沟通参考。';
      $('ended').hidden = false;
    }
  } catch(error) { showError(error); }
  finally { setBusy(false); $('messages').scrollTop = $('messages').scrollHeight; if (!closed) $('message').focus(); }
}
$('composer').addEventListener('submit', e => {e.preventDefault(); send($('message').value.trim());});
$('message').addEventListener('keydown', e => {if(e.key === 'Enter' && !e.shiftKey && !e.isComposing){e.preventDefault(); $('composer').requestSubmit();}});
$('messages').addEventListener('click', e => {const button = e.target.closest('[data-question]'); if(button && !busy){$('message').value = button.dataset.question; $('message').focus();}});
$('new-chat').addEventListener('click', startSession);
$('product-select').addEventListener('change', startSession);
$('retry').addEventListener('click', () => {if(failedText) send(failedText, true);});
setBusy(true);
request('/products').then(data => {
  products = data;
  $('product-select').replaceChildren(...products.map(p => {
    const option = element('option', `${p.name} · US V1`);
    option.value = p.product_id;
    return option;
  }));
  return startSession();
}).catch(error => {showError(error); setBusy(false);});
