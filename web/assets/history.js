// 保存少量成功使用的手机号与角色 ID；不保存验证码、Cookie 或令牌。
const inputHistory = (() => {
  const prefix = 'vidu-studio-history-v1-'; // 浏览器本地存储键的前缀。
  const patterns = {phone: /^1[3-9]\d{9}$/, avatar: /^\d+$/, room: /^\d+$/}; // 仅允许合法的号码和数字 ID。
  function read(type) {
    try {
      const values = JSON.parse(localStorage.getItem(prefix + type) || '[]'); // 本浏览器最近使用的列表。
      return Array.isArray(values) ? values.filter(value => typeof value === 'string' && patterns[type].test(value)).slice(0, 20) : [];
    } catch { return []; }
  }
  function render(type) {
    const list = document.querySelector('#history-' + type); // 对应输入框的原生候选列表。
    if (!list) return;
    list.replaceChildren(...read(type).map(value => { const option = document.createElement('option'); option.value = value; return option; }));
  }
  function add(type, value) {
    value = value.trim();
    if (!patterns[type].test(value)) return;
    try { localStorage.setItem(prefix + type, JSON.stringify([value, ...read(type).filter(item => item !== value)].slice(0, 20))); } catch { return; }
    render(type);
  }
  function clear(type) {
    try { localStorage.removeItem(prefix + type); render(type); return true; } catch { return false; }
  }
  return {render, add, clear};
})();

// 成功发送的消息按使用频率和最近时间排序，保存在当前浏览器。
const messageHistory = (() => {
  const key = 'vidu-studio-message-history-v1'; // 只包含用户主动发送的消息，不含验证码或 Cookie。
  function read() {
    try { const data = JSON.parse(localStorage.getItem(key) || '[]'); return Array.isArray(data) ? data.filter(item => typeof item.text === 'string').slice(0, 50) : []; }
    catch { return []; }
  }
  function render() {
    const list = document.querySelector('#history-message');
    list.replaceChildren(...read().sort((a,b) => (b.count || 0) - (a.count || 0) || (b.time || 0) - (a.time || 0)).map(item => {
      const option = document.createElement('option'); option.value = item.text; option.label = '使用 ' + (item.count || 1) + ' 次'; return option;
    }));
  }
  function add(text) {
    text = text.trim(); if (!text) return;
    try {
      const items = read(); const existing = items.find(item => item.text === text);
      localStorage.setItem(key, JSON.stringify([{text, count:(existing?.count || 0) + 1, time:Date.now()}, ...items.filter(item => item.text !== text)].slice(0, 50)));
      render();
    } catch { /* 不影响已成功发送的消息。 */ }
  }
  function clear() { try { localStorage.removeItem(key); render(); return true; } catch { return false; } }
  return {render, add, clear};
})();
