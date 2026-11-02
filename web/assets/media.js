// Studio 通过本机 WebRTC 接收真实音视频轨道，重建通话后重新协商。
const mediaPanel = document.createElement('section'); // 独立播放器区域。
mediaPanel.className = 'glass rounded-3xl p-8 mt-6';
mediaPanel.innerHTML = '<p class="section-index">02 / PREVIEW</p><h2 class="text-xl">数字人视频源</h2><div class="media-stage mt-4"><video id="avatar-video" autoplay muted playsinline controls class="w-full rounded-2xl bg-black" style="max-height:520px"></video><canvas id="avatar-freeze" class="media-freeze" hidden aria-label="恢复期间保留的上一帧画面"></canvas></div><div class="mt-4 flex gap-3"><button id="media-sound" class="button">开启声音</button><button id="media-retry" class="button button-secondary">重新连接画面</button></div><p id="media-state" class="mt-3">等待通话媒体</p>';
mediaPanel.insertAdjacentHTML('beforeend', '<p id="media-result" role="status" class="mt-2 text-cyan-200"></p><div class="obs-controls"><div><strong>OBS 浏览器源</strong><p>复制本机播放链接，粘贴到 OBS 的浏览器源。</p></div><div class="flex flex-wrap gap-3"><button id="obs-copy" class="button">复制 OBS 链接</button><button id="obs-regenerate" class="button button-secondary">重新生成</button><button id="obs-revoke" class="button button-secondary">撤销链接</button></div><input id="obs-url" class="control" aria-label="OBS 浏览器源链接" readonly hidden><p id="obs-result" role="status" class="text-cyan-200"></p></div>'); // OBS 链接只用于本地播放。
mediaPanel.insertAdjacentHTML('beforeend', '<div class="quality-controls"><label for="relay-percent">转发比例</label><select id="relay-percent" class="control"><option value="100">100% · 原始尺寸</option><option value="80">80%</option><option value="50">50%</option></select><span>控制台与 OBS 使用相同目标；实际画质由浏览器决定。</span></div><p id="quality-result" role="status" class="media-quality"></p><p id="media-quality" class="media-quality">画质数据将在视频连接后显示。</p>'); // 展示设置与实际统计。
document.querySelector('#events').closest('section').before(mediaPanel);
const avatarVideo = document.querySelector('#avatar-video'); // 本机接收的视频元素。
const freezeCanvas = document.querySelector('#avatar-freeze'); // 恢复时展示最近一个已解码视频帧。
const mediaState = document.querySelector('#media-state'); // 当前播放器状态。
let mediaPeer = null; // 当前媒体连接。
let mediaLiveId = null; // 关联的业务通话，变化后重建。
let mediaBusy = false; // 防止并行协商。
let mediaRetryAfter = 0; // 失败后的有限间隔。
let lastReceive = null; // 上次接收字节及时间，用于计算实时码率。
let lastSend = null; // 上次发送字节及时间，用于计算本机转发码率。
let hasFrozenFrame = false; // 是否已经成功捕获一帧。
let lastFrameTime = -1; // 防止重复捕获同一帧。
let qualityBusy = false; // 设置过程中不能由轮询覆盖用户选择。
let relayPercent = 100; // 默认请求原始尺寸，服务端负责会话内保存。
let qualityGeneration = 0; // 丢弃设置前已发出的旧状态响应。
const qualitySelect = document.querySelector('#relay-percent');
qualitySelect.onchange = async () => {
  const previous = relayPercent; const value = Number(qualitySelect.value); // 保留失败时回滚的选项。
  qualityBusy = true; qualityGeneration += 1; qualitySelect.disabled = true;
  const resultBox = document.querySelector('#quality-result'); resultBox.textContent = '正在应用转发比例…';
  try {
    const data = await viduRequest('media/quality/settings', {percent:value});
    relayPercent = data.percent;
    const results = Object.values(data.results || {}); // 当前连接的两个发送端分别应用。
    resultBox.textContent = results.some(item => !item.applied) ? '目标已保存，但部分接收端未能应用，请检查浏览器或重新连接。' : results.length ? '转发目标已更新，请查看下方实际尺寸。' : '转发目标已保存，连接视频后生效。';
  } catch (error) { qualitySelect.value = String(previous); resultBox.textContent = '设置失败：' + error.message; }
  finally { qualityBusy = false; qualitySelect.disabled = false; }
};

function cacheCurrentFrame() {
  // 仅在视频有实际画面时更新缓存，停止期间不得用黑帧覆盖。
  if (!mediaPeer || !avatarVideo.srcObject || avatarVideo.readyState < 2 || !avatarVideo.videoWidth || !avatarVideo.videoHeight || avatarVideo.currentTime === lastFrameTime) return;
  try {
    if (freezeCanvas.width !== avatarVideo.videoWidth || freezeCanvas.height !== avatarVideo.videoHeight) {
      freezeCanvas.width = avatarVideo.videoWidth; freezeCanvas.height = avatarVideo.videoHeight;
    }
    freezeCanvas.getContext('2d').drawImage(avatarVideo, 0, 0, freezeCanvas.width, freezeCanvas.height);
    lastFrameTime = avatarVideo.currentTime; hasFrozenFrame = true;
    freezeCanvas.hidden = true; // 新连接真正出现画面后才移除静态帧。
  } catch { /* 无法读取当前帧时继续播放，不中断通话。 */ }
}
const frameCacheTimer = setInterval(cacheCurrentFrame, 250); // 定期缓存，避免断流后已经无法取帧。

function bitrate(currentBytes, currentTime, previous) {
  // 两次累计字节之差除以时间差；时间戳以毫秒计。
  if (!previous || currentBytes == null || currentTime == null || currentTime <= previous.time || currentBytes < previous.bytes) return null;
  return Math.round((currentBytes - previous.bytes) * 8 / (currentTime - previous.time));
}
function dimensions(width, height) { return width && height ? width + '×' + height : '暂不可用'; } // 不将缺失值误当成零画质。
function fps(value) { return Number.isFinite(value) && value > 0 ? Math.round(value) + ' fps' : '帧率暂不可用'; }
function speed(value) { return value == null ? '码率采样中' : value + ' kbps'; }

async function updateMediaQuality(peer) {
  // 源轨道取自 Vidu 页面，中转发送和本地接收分别使用各自的 WebRTC 统计。
  const source = await viduRequest('media/quality');
  const stats = await peer.getStats();
  if (peer !== mediaPeer) return; // 连接已更换时丢弃旧统计。
  let incoming = null; // 本机视频接收统计。
  for (const stat of stats.values()) if (stat.type === 'inbound-rtp' && (stat.kind === 'video' || stat.mediaType === 'video')) incoming = stat;
  const sentRate = bitrate(source.sent_bytes, source.sent_timestamp, lastSend);
  if (source.sent_bytes != null && source.sent_timestamp != null) lastSend = {bytes:source.sent_bytes,time:source.sent_timestamp};
  const receivedRate = bitrate(incoming?.bytesReceived, incoming?.timestamp, lastReceive);
  if (incoming?.bytesReceived != null && incoming?.timestamp != null) lastReceive = {bytes:incoming.bytesReceived,time:incoming.timestamp};
  const targetWidth = source.source_width ? Math.round(source.source_width * relayPercent / 100) : null; // 未知源尺寸时不猜测目标。
  const targetHeight = source.source_height ? Math.round(source.source_height * relayPercent / 100) : null;
  const limits = {none:'无已报告限制', cpu:'CPU 性能限制', bandwidth:'带宽限制', other:'其他限制'}; // 浏览器提供的编码限制原因。
  const actualConfig = source.applied_scale > 0 ? Math.round(100 / source.applied_scale) + '%' : '不可用'; // 回读的参数不等于实际分辨率。
  const preference = source.degradation_preference === 'maintain-resolution' ? '优先分辨率' : source.degradation_preference || '不可用';
  document.querySelector('#media-quality').textContent = 'Vidu 源轨道：' + dimensions(source.source_width, source.source_height) + ' · ' + fps(source.source_fps) +
    '  |  目标（' + relayPercent + '%）：约 ' + dimensions(targetWidth, targetHeight) +
    '  |  本机转发：' + dimensions(source.sent_width, source.sent_height) + ' · ' + fps(source.sent_fps) + ' · ' + speed(sentRate) +
    '  |  控制台接收：' + dimensions(avatarVideo.videoWidth, avatarVideo.videoHeight) + ' · ' + fps(incoming?.framesPerSecond) + ' · ' + speed(receivedRate) +
    '  |  控制台画质限制：' + (limits[source.limitation] || '统计不可用') +
    (source.obs_active ? '  |  OBS 转发：' + dimensions(source.obs_width, source.obs_height) + ' · ' + fps(source.obs_fps) + ' · ' + (limits[source.obs_limitation] || '限制原因不可用') : '') +
    '  |  参数回读：' + actualConfig + ' · ' + preference + '  |  ' + (source.tuning || '画质参数暂不可用');
}

function closeMedia(keepFrame = false) {
  // 只关闭本机接收端，不结束 Vidu 通话。
  if (keepFrame) cacheCurrentFrame(); // 在关闭前尝试保存最新可用画面。
  if (mediaPeer) mediaPeer.close();
  mediaPeer = null; mediaLiveId = null; avatarVideo.srcObject = null;
  freezeCanvas.hidden = !(keepFrame && hasFrozenFrame);
  if (!keepFrame) { hasFrozenFrame = false; freezeCanvas.width = 0; freezeCanvas.height = 0; }
  lastFrameTime = -1;
  lastReceive = null; lastSend = null;
  document.querySelector('#media-quality').textContent = '画质数据将在视频连接后显示。';
}

async function connectMedia(liveId) {
  // 收齐本机 ICE 候选后一次性提交 SDP，不把 RTC 密钥暴露给页面。
  closeMedia(true);
  mediaBusy = true;
  const peer = new RTCPeerConnection({iceServers:[]});
  mediaPeer = peer; mediaLiveId = liveId;
  peer.addTransceiver('video', {direction:'recvonly'});
  peer.addTransceiver('audio', {direction:'recvonly'});
  peer.ontrack = event => {
    avatarVideo.srcObject = event.streams[0];
    avatarVideo.play().catch(() => {mediaState.textContent = '点击播放器开始播放';});
  };
  try {
    mediaState.textContent = '正在协商本机音视频';
    await peer.setLocalDescription(await peer.createOffer());
    await new Promise((resolve,reject) => {
      if (peer.iceGatheringState === 'complete') return resolve();
      const timer = setTimeout(() => reject(new Error('播放器协商超时')),10000);
      peer.onicegatheringstatechange = () => {
        if (peer.iceGatheringState === 'complete') {clearTimeout(timer);resolve();}
      };
    });
    const answer = await viduRequest('media/answer', {type:'offer',sdp:peer.localDescription.sdp});
    await peer.setRemoteDescription(answer);
    mediaState.textContent = '媒体协商完成，等待播放帧';
  } catch (error) {
    mediaState.textContent = error.message; closeMedia(true); mediaRetryAfter = Date.now()+10000;
  } finally { mediaBusy = false; }
}

async function pollMedia() {
  // 根据通话 ID 自动跟随超时恢复，显示实际解码帧数。
  try {
    const generation = qualityGeneration; // 本次轮询发出时的设置版本。
    const status = await viduRequest('status');
    if (!qualityBusy && generation === qualityGeneration && [100,80,50].includes(status.relay_percent)) { relayPercent = status.relay_percent; qualitySelect.value = String(relayPercent); } // 刷新后恢复当前会话目标。
    if (!status.media_connected) {
      const stopped = ['idle', 'stopped'].includes(status.state); // 手动停止时清除静态画面。
      if (!mediaBusy) closeMedia(!stopped);
      const recovering = ['starting', 'retry_wait', 'restarting'].includes(status.state);
      mediaState.textContent = recovering && hasFrozenFrame ? '画面已暂存 · 正在后台恢复' : !stopped && hasFrozenFrame ? '画面已暂存 · 请查看通话状态' : '等待数字人通话媒体';
    } else if (!mediaBusy && Date.now() >= mediaRetryAfter &&
        (mediaLiveId !== status.live_id || !mediaPeer || ['failed','closed','disconnected'].includes(mediaPeer.connectionState))) {
      await connectMedia(status.live_id);
    } else if (mediaPeer?.connectionState === 'connected') {
      const frames = avatarVideo.getVideoPlaybackQuality().totalVideoFrames;
      mediaState.textContent = '音视频已连接 · 已解码 '+frames+' 帧 · '+(avatarVideo.muted?'静音预览':'声音开启');
      try { await updateMediaQuality(mediaPeer); } catch { document.querySelector('#media-quality').textContent = '画质统计暂不可用，视频播放不受影响。'; }
    }
  } catch { mediaState.textContent = '本地服务不可达'; }
  finally { setTimeout(pollMedia,2000); }
}
document.querySelector('#media-sound').onclick = async () => {
  const result = document.querySelector('#media-result'); // 提示播放权限和实际媒体状态。
  avatarVideo.muted = false;
  if (!avatarVideo.srcObject) { result.textContent = '已开启声音，等待通话媒体连接。'; return; }
  try { await avatarVideo.play(); result.textContent = '声音已开启；若仍无声，请检查设备音量。'; }
  catch (error) { result.textContent = '播放失败：' + error.message; }
};
document.querySelector('#media-retry').onclick = () => {
  document.querySelector('#media-result').textContent = mediaBusy ? '正在协商画面，请稍候。' : '已请求重新连接；有可用通话媒体后开始协商。';
  if (!mediaBusy) { closeMedia(true); mediaRetryAfter=0; }
};
let obsUrl = ''; // 令牌仅保存在当前页面内存和 OBS 链接片段中。
async function generateObsUrl(rotate = false) {
  const data = await viduRequest('obs/link', {rotate}); // 显式轮换时旧地址才失效。
  obsUrl = location.origin + '/obs#' + encodeURIComponent(data.token);
  const input = document.querySelector('#obs-url'); input.value = obsUrl; input.hidden = false;
  return obsUrl;
}
async function obsAction(button, action) {
  button.disabled = true;
  const result = document.querySelector('#obs-result'); result.textContent = '正在处理…';
  try { result.textContent = await action(); }
  catch (error) { result.textContent = '操作失败：' + error.message; }
  finally { button.disabled = false; }
}
document.querySelector('#obs-copy').onclick = event => obsAction(event.currentTarget, async () => {
  const url = await generateObsUrl(); // 即使页面刷新也复用会话中已有的链接。
  try { await navigator.clipboard.writeText(url); return '已复制。请在 OBS 添加浏览器源并粘贴链接。'; }
  catch { document.querySelector('#obs-url').select(); return '无法自动复制，请复制上方链接。'; }
});
document.querySelector('#obs-regenerate').onclick = event => obsAction(event.currentTarget, async () => { await generateObsUrl(true); return '新链接已生成，旧链接已失效。'; });
document.querySelector('#obs-revoke').onclick = event => obsAction(event.currentTarget, async () => {
  await viduRequest('obs/revoke', {}); obsUrl = ''; const input = document.querySelector('#obs-url'); input.value = ''; input.hidden = true;
  return 'OBS 链接已撤销。';
});
window.addEventListener('pagehide', () => { clearInterval(frameCacheTimer); closeMedia(); });
pollMedia();
