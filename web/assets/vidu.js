// Studio 账号和业务信令面板；验证码和令牌不写入浏览器存储。
const panel = document.createElement('section'); // 独立的 Vidu 功能区域。
panel.className = 'glass rounded-3xl p-8 mt-6';
panel.innerHTML = '<p class="section-index">01 / CONNECTION</p><h2 class="text-xl">Vidu 账号与接口指令</h2>' +
  '<p class="mt-3 text-slate-300">通过短信登录并开始数字人通话。指令直接通过信令发送。连接超时后可有限次自动恢复，官方 SDK 的音视频通过本机 WebRTC 显示在下方。</p>' +
  '<details id="step-browser" class="step" open><summary>步骤 1 · 启动窗口 <span id="step-browser-state"></span></summary><div class="step-body"><button id="vidu-browser" class="button">启动窗口</button><p id="vidu-browser-result" role="status" class="mt-3 text-cyan-200"></p></div></details>' +
  '<details id="step-login" class="step"><summary>步骤 2 · 登录账号 <span id="step-login-state"></span></summary><fieldset id="login-fields" class="step-body" disabled><div class="mt-4 flex flex-wrap gap-3"><input id="vidu-phone" class="control" aria-label="手机号" placeholder="手机号" list="history-phone" autocomplete="off"><datalist id="history-phone"></datalist><button id="vidu-sms" class="button">获取验证码</button>' +
  '<input id="vidu-code" class="control" type="password" aria-label="验证码" placeholder="验证码" autocomplete="one-time-code"><button id="vidu-login" class="button">登录</button><button id="vidu-logout" class="button">清除当前登录态</button></div><div class="mt-4 flex flex-wrap gap-3"><select id="vidu-saved-account" class="control" aria-label="已保存的账号"><option value="">无可用的保存账号</option></select><button id="vidu-restore" class="button button-secondary">一键登录</button><button id="vidu-forget" class="button button-secondary">清除所选保存账号</button></div>' +
  '<label class="block mt-4"><input type="checkbox" id="vidu-consent" checked> 我已阅读并同意 Vidu <a href="https://www.vidu.cn/terms" target="_blank" rel="noopener">用户协议</a>、<a href="https://www.vidu.cn/privacy" target="_blank" rel="noopener">隐私协议</a>、<a href="https://www.vidu.cn/personal-info-collection" target="_blank">信息收集清单</a>、<a href="https://www.vidu.cn/personal-info-sharing" target="_blank">信息共享清单</a></label><button type="button" id="clear-phone-history" class="history-clear">清除手机号历史</button><p id="vidu-account-result" role="status" class="mt-3 text-cyan-200"></p></fieldset></details>' +
  '<details id="step-call" class="step"><summary>步骤 3 · 选择角色并连接 <span id="step-call-state"></span></summary><fieldset id="call-fields" class="step-body" disabled><div class="mt-5 flex flex-wrap gap-3"><input id="vidu-avatar" class="control" aria-label="角色 ID" placeholder="Vidu 角色 ID" list="history-avatar" autocomplete="off"><datalist id="history-avatar"></datalist><button id="vidu-claim" class="button">开始通话</button><button id="vidu-stop" class="button">断开连接并切换角色</button></div><button type="button" id="clear-avatar-history" class="history-clear">清除角色 ID 历史</button><p id="vidu-call-result" role="status" class="mt-3 text-cyan-200"></p>' +
  '<label class="block mt-4"><input type="checkbox" id="vidu-auto" checked> 连接超时最多自动重启 3 次；明确的内容审核结束最多恢复 1 次，可能消耗通话额度</label><p id="vidu-call-state" role="status" class="mt-3">通话未开始</p>' +
  '<label class="block mt-4"><input type="checkbox" id="vidu-live-consent" checked disabled> 我已完成并同意 <a href="https://www.vidu.cn/consent-live" target="_blank">通话个人信息规则</a>、<a href="https://www.vidu.cn/consent-voice" target="_blank">声纹授权</a>、<a href="https://www.vidu.cn/consent-face" target="_blank">面部特征授权</a></label>' +
  '</fieldset></details><details id="step-send" class="step"><summary>步骤 4 · 自定义发送 <span id="step-send-state"></span></summary><fieldset id="send-fields" class="step-body" disabled><div class="mt-5 flex flex-wrap gap-3"><input id="vidu-message" class="control" aria-label="接口指令" placeholder="输入自定义指令，回车发送" list="history-message" autocomplete="off"><datalist id="history-message"></datalist><button id="vidu-send" class="button" disabled>通过 WebSocket 发送</button></div><button type="button" id="clear-message-history" class="history-clear">清除消息历史</button><p id="vidu-send-hint" class="mt-2 text-slate-300">通话媒体连接后才能发送指令。</p><p role="status" id="vidu-result" class="mt-4 text-cyan-200">请选择操作。</p></fieldset></details>';
document.querySelector('#events').closest('section').before(panel);
const field = (name) => document.querySelector('#vidu-' + name); // 局部控件查询。
messageHistory.render();
document.querySelector('#clear-message-history').onclick = () => { field('result').textContent = messageHistory.clear() ? '消息历史已清除。' : '无法清除消息历史。'; };
field('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing && !event.repeat && !field('send').disabled) { event.preventDefault(); field('send').click(); } }); // 输入法选词和重复按键不触发发送。
let pendingAvatar = null; // 等待媒体实际连通后才记录角色 ID。
for (const type of ['phone', 'avatar']) {
  inputHistory.render(type);
  document.querySelector('#clear-' + type + '-history').onclick = () => {
    const result = field(type === 'phone' ? 'account-result' : 'call-result'); // 显示清除结果。
    result.textContent = inputHistory.clear(type) ? '本浏览器的历史记录已清除。' : '无法清除历史记录，请检查浏览器存储权限。';
  };
}

// 统一调用本机接口，错误消息仅渲染为文本。
async function viduRequest(path, body) {
  await window.studioReady; // 首次页面加载只初始化一次会话，避免并发 Cookie 竞争。
  const response = await fetch('/api/vidu/' + path, {
    method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: {'Content-Type': 'application/json', 'X-Studio-Request': '1'},
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入格式有误，请检查手机号、验证码、角色 ID 或指令');
  return data;
}

// 每个按钮等待请求完成，验证码无论成功失败都立即清空。
function bindVidu(name, action) {
  field(name).addEventListener('click', async () => {
    const result = field(name === 'browser' ? 'browser-result' : ['sms', 'login', 'logout', 'restore', 'forget'].includes(name) ? 'account-result' : ['claim', 'stop'].includes(name) ? 'call-result' : 'result'); // 反馈放在对应操作组。
    field(name).disabled = true; field(name).dataset.busy = '1';
    result.textContent = '正在' + field(name).textContent + '，请稍候…';
    try { result.textContent = await action(); await updateSteps(); }
    catch (error) { result.textContent = '操作失败：' + error.message; }
    finally { delete field(name).dataset.busy; field(name).disabled = name === 'send' && !window.viduConnected; }
  });
}
async function refreshSavedAccounts() {
  const data = await viduRequest('accounts'); const select = field('saved-account'); const selected = select.value;
  select.replaceChildren();
  const placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = data.accounts.length ? '选择一天内登录过的账号' : '无可用的保存账号'; select.append(placeholder);
  for (const phone of data.accounts) { const option = document.createElement('option'); option.value = phone; option.textContent = phone; select.append(option); }
  if (data.accounts.includes(selected)) select.value = selected;
}
window.studioReady.then(refreshSavedAccounts).catch(() => {}); // 页面刷新后恢复账号列表，不自动登录。
bindVidu('browser', async () => { await viduRequest('browser/start', {}); await refreshSavedAccounts(); return '窗口已启动，请保持窗口打开。'; });
bindVidu('restore', async () => { const phone = field('saved-account').value; if (!phone) throw new Error('请先选择保存的账号'); await viduRequest('accounts/restore', {phone}); return '保存的账号已验证并登录。'; });
bindVidu('forget', async () => { const phone = field('saved-account').value; if (!phone) throw new Error('请先选择保存的账号'); await viduRequest('accounts/forget', {phone}); await refreshSavedAccounts(); return '已清除所选账号的保存登录态。'; });
bindVidu('sms', async () => {
  await viduRequest('sms', {phone:field('phone').value, consent:field('consent').checked});
  return '短信已请求，请输入验证码。';
});
bindVidu('login', async () => {
  try {
    const phone = field('phone').value.trim(); // 只在成功后记录手机号。
    const result = await viduRequest('login', {phone, code:field('code').value, consent:field('consent').checked});
    inputHistory.add('phone', phone);
    field('phone').value = '';
    if (result.saved) { try { await refreshSavedAccounts(); } catch {} }
    return result.saved ? 'Vidu 登录成功，已在本机加密保存登录态 24 小时。' : 'Vidu 登录成功，但本机未能保存登录态。';
  } finally { field('code').value = ''; }
});
bindVidu('logout', async () => { pendingAvatar = null; await viduRequest('logout', {}); await viduRequest('status'); return '登录态已清除。'; });
bindVidu('claim', async () => {
  const avatar = field('avatar').value.trim(); // 本次请求的角色 ID。
  pendingAvatar = null;
  const data = await viduRequest('claim', {avatar_id:avatar, consent:field('live-consent').checked, auto_restart:field('auto').checked});
  pendingAvatar = avatar;
  return '会话已创建：' + data.live_id + '，正在等待媒体连接。';
});
bindVidu('stop', async () => { pendingAvatar = null; const status = await viduRequest('status'); if (!['idle', 'stopped'].includes(status.state)) await viduRequest('stop', {}); return '连接已断开，可以输入新角色 ID；自动恢复已取消。'; });
bindVidu('send', async () => {
  const text = field('message').value.trim(); // 只在成功收到接受回执后记录消息。
  const result = await viduRequest('command', {text});
  if (result.accepted !== true) throw new Error('未收到接受回执');
  messageHistory.add(text);
  return '服务端已接收指令（accepted=true），不代表语音或动作已完成。';
});
// 登录状态独立显示，避免初始请求覆盖用户刚执行的操作结果。
const authState = document.createElement('p'); // 周期更新的账号状态。
authState.className = 'mt-3 text-slate-300'; authState.setAttribute('role', 'status');
panel.querySelector('h2').after(authState);
let currentStep = 0; // 仅在实际阶段变化时自动折叠，允许用户手动展开已完成步骤。
// 根据服务端真实状态控制步骤，不依赖点击次数。
function renderSteps(data) {
  const browser = !!data.browser_ready; // 有头窗口是否仍然可用。
  const loggedIn = browser && !!data.authenticated; // 登录依赖有效浏览器。
  const connected = loggedIn && data.state === 'connected'; // 只有媒体就绪才解锁发送。
  if (connected && pendingAvatar) { inputHistory.add('avatar', pendingAvatar); pendingAvatar = null; }
  const next = !browser ? 1 : !loggedIn ? 2 : !connected ? 3 : 4;
  for (const [name, enabled, label] of [
    ['browser', true, browser ? '已完成' : '等待启动'],
    ['login', browser, loggedIn ? '已完成' : browser ? '待登录' : '请先启动窗口'],
    ['call', loggedIn, connected ? '已连接' : loggedIn ? '待连接' : '请先登录'],
    ['send', connected, connected ? '可发送' : '请先连接角色']
  ]) {
    const step = document.querySelector('#step-' + name); // 对应折叠步骤。
    step.dataset.enabled = enabled ? '1' : '0';
    document.querySelector('#step-' + name + '-state').textContent = ' · ' + label;
    if (!enabled) step.open = false;
  }
  document.querySelector('#login-fields').disabled = !browser;
  document.querySelector('#call-fields').disabled = !loggedIn;
  document.querySelector('#send-fields').disabled = !connected;
  window.viduConnected = connected;
  field('send').disabled = !connected || field('send').dataset.busy === '1';
  field('send-hint').textContent = connected ? '通话已连接，可以发送指令。' : '发送不可用：请先登录并开始通话，等待媒体连接。';
  if (next !== currentStep) {
    for (const [index, name] of ['browser', 'login', 'call', 'send'].entries()) {
      document.querySelector('#step-' + name).open = index + 1 === next;
    }
    currentStep = next;
  }
}
for (const step of panel.querySelectorAll('.step')) {
  step.querySelector('summary').addEventListener('click', event => {
    if (step.dataset.enabled === '0') event.preventDefault(); // 未解锁步骤不能展开。
  });
}
async function updateSteps() { renderSteps(await viduRequest('status')); } // 操作结束立即刷新步骤。

// 独立显示恢复状态，轮询不覆盖用户操作结果，也不并发堆积请求。
async function refreshCallState() {
  const labels = {idle:'未开始', stopped:'已停止', starting:'等待媒体', connected:'媒体已连接', audit_check:'收到审核提示，正在检查画面；指令已暂停',
    retry_wait:'等待自动重启', restarting:'正在重建通话', attention:'需要处理', exhausted:'重试已达上限'};
  const reasons = {content_policy_ended:'官网提示内容不符合规范，通话已结束；自动消息已暂停', policy_recovery_failed:'审核结束后的恢复失败，请检查登录和额度', audit_rejected:'收到审核信号'}; // 审核原因以中文提示。
  try {
    const data = await viduRequest('status');
    renderSteps(data);
    authState.textContent = data.authenticated ? '账号状态：已登录' : '账号状态：未登录，请先获取验证码并登录';
    field('call-state').textContent = (labels[data.state] || data.state) +
      ' · 已重启 ' + data.attempts + '/' + data.max_attempts +
      (data.retry_in ? ' · ' + data.retry_in + ' 秒后重试' : '') +
      (data.reason ? ' · 原因：' + (reasons[data.reason] || data.reason) : '') +
      (data.reason === 'content_policy_ended' && data.state === 'attention' && data.policy_attempted ? '；已尝试一次，停止自动恢复' : '');
    window.viduConnected = data.state === 'connected'; // 发送必须等待媒体连接完成。
    field('send').disabled = !window.viduConnected || field('send').dataset.busy === '1';
    field('send-hint').textContent = window.viduConnected ? '通话已连接，可以发送指令。' : '发送不可用：请先登录并开始通话，等待媒体连接。';
  } catch { authState.textContent = '账号状态：无法获取'; field('call-state').textContent = '本地服务连接失败，请检查启动窗口'; field('send').disabled = true; }
  finally { setTimeout(refreshCallState, 2000); }
}
refreshCallState();
