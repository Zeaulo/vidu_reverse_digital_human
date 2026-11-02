// 房间采集和调度状态；外部昵称、评论始终按文本显示。
const roomInput = document.querySelector('#room-id'); // 用户输入的房间号。
const eventsBox = document.querySelector('#events'); // 有限事件历史。
const activity = document.createElement('div'); // 点赞和进入记录使用独立小框。
activity.className = 'activity-grid';
activity.innerHTML = '<div class="activity-box"><h3>进入直播间 <span id="enter-count">0</span></h3><div id="enter-events" class="activity-list"></div></div><div class="activity-box"><h3>点赞 <span id="like-count">0</span></h3><div id="like-events" class="activity-list"></div></div>';
eventsBox.after(activity);
const giftBox = document.createElement('div'); // 礼物及关注单独展示，不混入评论。
giftBox.className = 'other-events'; giftBox.id = 'other-events'; activity.after(giftBox);
const statusText = document.querySelector('#service-status'); // 上游房间状态。
const roomText = document.querySelector('#current-room'); // 当前已连接房间。
const queueText = document.querySelector('#queue-size'); // 队列长度。
const summary = document.createElement('p'); // 收到与发送分开统计。
summary.className = 'event-summary';
document.querySelector('.event-heading').before(summary);
const roomResult = document.createElement('p'); // 显示采集操作结果，不被轮询覆盖。
roomResult.className = 'mt-4 text-cyan-200'; roomResult.setAttribute('role', 'status');
document.querySelector('#save-room').parentElement.after(roomResult);
const stopRoom = document.createElement('button'); // 停止本机采集。
stopRoom.className = 'button button-secondary'; stopRoom.textContent = '停止采集';
document.querySelector('#save-room').after(stopRoom);
document.querySelector('#save-room').textContent = '连接直播间并自动调度';

async function bridgeRequest(path, body) {
  // 使用同一 HttpOnly 会话和同源请求头，禁止跨账号事件消费。
  const response = await fetch(path,{method:body?'POST':'GET',cache:'no-store',
    headers:{'Content-Type':'application/json','X-Studio-Request':'1'},body:body?JSON.stringify(body):undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入不符合要求，请检查房间号');
  return data;
}

let roomGeneration = 0; // 连接新直播间后忽略先前轮询的过期结果。
let connectingRoom = false; // 切换期间暂停旧快照渲染。
let warmupBusy = false; // 变更期间避免轮询覆盖用户选择。
let historyRoomRecorded = ''; // 避免每次轮询重复写入历史。
async function refreshBridge() {
  // 控制台轮询，不将采集 socket 建立误认为上游房间已连通。
  try {
    const generation = roomGeneration; // 记录请求所属的连接轮次。
    const data = await bridgeRequest('/api/events');
    if (generation !== roomGeneration || connectingRoom) return;
    const labels = {idle:'未连接',stopped:'已停止',connecting:'连接中',online:'直播间已连接',disconnected:'采集已断开',room_not_found:'直播间不存在',room_status_unknown:'直播间状态未知'};
    statusText.textContent = labels[data.state] || data.state;
    roomText.textContent = data.room_id || '未设置'; queueText.textContent = data.queue_size;
    if (data.state === 'online' && data.room_id && data.room_id !== historyRoomRecorded) { inputHistory.add('room', data.room_id); historyRoomRecorded = data.room_id; } // 仅记录已确认连接的直播间。
    if (!warmupBusy) document.querySelector('#warmup').checked = !!data.warmup;
    const count = data.counts;
    const detail = data.state === 'room_status_unknown' ? '上游未返回可验证的房间状态，采集已停止，请稍后重试。' : data.detail; // 本项目不会在未知状态下继续轮询。
    summary.textContent = '收到 '+(count.received||0)+' · 评论 '+(count.comment||0)+' · 点赞增量 '+(count.likes||0)+' · 礼物事件 '+(count.gift||0)+' · 累计入队 '+(count.queued||0)+' · 发送 '+(count.sent||0)+' · Vidu接受 '+(count.accepted||0)+' · 审核未通过 '+(count.moderation_rejected||0)+' · 丢弃或过期 '+(count.dropped||0)+' · 回执不明 '+(count.failed||0)+(detail?' · '+detail:'');
    eventsBox.replaceChildren(); giftBox.replaceChildren();
    const likeEvents = document.querySelector('#like-events'); // 点赞列表。
    const enterEvents = document.querySelector('#enter-events'); // 入场列表。
    likeEvents.replaceChildren(); enterEvents.replaceChildren();
    document.querySelector('#like-count').textContent = '事件 ' + (count.like || 0) + ' · 点赞 ' + (count.likes || 0);
    document.querySelector('#enter-count').textContent = '事件 ' + (count.enter || 0);
    for (const event of data.events.slice().sort((a,b) => new Date(b.timestamp) - new Date(a.timestamp))) {
      const article = document.createElement('article');
      article.className = 'event-item';
      const title = document.createElement('div');
      title.className = 'text-xs text-slate-400';
      const deliveryLabels = {observed:'已收到，未入队',queued:'排队中',sending:'发送中',accepted:'Vidu 已接受',moderation_rejected:'审核未通过',expired:'已过期',dropped:'已丢弃',unknown:'回执不明'}; // 区分采集和实际发送结果。
      const moment = new Date(event.timestamp); // 展示浏览器本地时间，原始记录保留 UTC。
      const timestamp = Number.isNaN(moment.getTime()) ? '时间未知' : moment.toLocaleString('zh-CN', {hour12:false});
      title.textContent = timestamp+' · '+event.nickname+' · '+(deliveryLabels[event.delivery] || event.delivery);
      const content = document.createElement('p');
      content.textContent = event.event_type === 'like' ? '点赞 ' + (event.like_count || 0) + ' 次' : event.event_type === 'enter' ? '进入直播间' : event.content || event.gift_name || event.event_type;
      article.append(title,content);
      const destination = event.event_type === 'like' ? likeEvents : event.event_type === 'enter' ? enterEvents : event.event_type === 'comment' ? eventsBox : giftBox; // 每类独立展示。
      destination.append(article);
    }
    for (const [container, message] of [[eventsBox,'还没有收到评论'],[enterEvents,'等待观众进入'],[likeEvents,'等待点赞']]) {
      if (!container.children.length) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = message; container.append(empty); }
    }
  } catch (error) {statusText.textContent=error.message;}
  finally {setTimeout(refreshBridge,2000);}
}
// 采集启停提供独立的进行中、结果和错误提示。
async function roomAction(button, message, action) {
  button.disabled = true; roomResult.textContent = message;
  try { roomResult.textContent = await action(); }
  catch (error) { roomResult.textContent = '操作失败：' + error.message; }
  finally { button.disabled = false; }
}
document.querySelector('#save-room').onclick = event => roomAction(event.currentTarget, '正在提交直播间连接请求…', async () => {
  await window.studioReady;
  connectingRoom = true; roomGeneration += 1;
  try {
    await bridgeRequest('/api/session/room',{room_id:roomInput.value.trim()});
    historyRoomRecorded = ''; // 重新连接成功后允许更新历史排序。
    for (const container of [eventsBox, giftBox, document.querySelector('#like-events'), document.querySelector('#enter-events')]) container.replaceChildren();
    statusText.textContent = '连接中'; roomText.textContent = roomInput.value.trim(); queueText.textContent = '0'; summary.textContent = '已清空上一轮记录，正在等待直播间事件。';
    return '连接请求已提交，请查看上方服务状态；连接成功不代表已经收到事件。';
  } finally { connectingRoom = false; }
});
stopRoom.onclick = event => roomAction(event.currentTarget, '正在停止采集…', async () => {
  await window.studioReady; await bridgeRequest('/api/session/room/stop',{});
  return '采集已停止，待处理队列已清空；Vidu 通话不受影响。';
});
document.querySelector('#warmup').onchange = async event => {
  const toggle = event.currentTarget; warmupBusy = true; toggle.disabled = true;
  try { await window.studioReady; await bridgeRequest('/api/session/warmup', {enabled:toggle.checked}); roomResult.textContent = toggle.checked ? '暖场已开启；进入、点赞和礼物将按队列依次发送。' : '暖场已关闭，尚未发送的暖场事件已移除。'; }
  catch (error) { toggle.checked = !toggle.checked; roomResult.textContent = '暖场设置失败：' + error.message; }
  finally { warmupBusy = false; toggle.disabled = false; }
};
document.querySelector('#export-events').onclick = event => roomAction(event.currentTarget, '正在准备直播记录…', async () => {
  await window.studioReady;
  const response = await fetch('/api/events/export', {headers:{'X-Studio-Request':'1'},cache:'no-store'}); // 下载当前会话的完整记录。
  if (!response.ok) { const error = await response.json(); throw new Error(error.detail || '保存失败'); }
  const data = await response.json();
  const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json;charset=utf-8'}); // UTF-8 JSON 可保留中文。
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = '直播记录_' + data.room_id + '_' + new Date().toISOString().replace(/[:.]/g,'-') + '.json';
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  return '直播记录已导出，共 ' + data.events.length + ' 条。';
});
// 先创建一次会话，后续所有页面模块复用同一个 Cookie。
window.studioReady = bridgeRequest('/api/vidu/status');
window.studioReady.then(() => inputHistory.render('room')).catch(() => {}); // 历史模块在脚本加载完毕后可用。
document.querySelector('#clear-room-history').onclick = () => { roomResult.textContent = inputHistory.clear('room') ? '本浏览器的直播间 ID 历史已清除。' : '无法清除直播间 ID 历史。'; };
window.studioReady.then(refreshBridge).catch(error => {statusText.textContent=error.message;});
