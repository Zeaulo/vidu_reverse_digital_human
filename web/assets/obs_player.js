// OBS 浏览器源通过本机播放令牌接收独立 WebRTC 音视频。
(() => {
  const token = decodeURIComponent(location.hash.slice(1)); // URL 片段不会发送到服务器访问日志。
  const video = document.querySelector('#video'); // OBS 输出视频。
  const freeze = document.querySelector('#freeze'); // 重连期间的最后一帧。
  const status = document.querySelector('#status'); // 空字符串时不遮挡视频。
  const sound = document.querySelector('#sound'); // 浏览器阻止有声自动播放时的手动入口。
  let peer = null, liveId = null, busy = false, retryAfter = 0, hasFrame = false, lastTime = -1, stopped = false;

  async function request(path, body) {
    const response = await fetch('/api/obs/' + path, {method:body ? 'POST' : 'GET',cache:'no-store',
      headers:{'X-Obs-Token':token, ...(body ? {'Content-Type':'application/json'} : {})},body:body ? JSON.stringify(body) : undefined});
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.detail || 'OBS 播放请求失败'); error.status = response.status; throw error; }
    return data;
  }
  function cacheFrame() {
    // 未解码出新帧时保留上一帧，避免黑画面覆盖缓存。
    if (!peer || !video.srcObject || video.readyState < 2 || !video.videoWidth || !video.videoHeight || video.currentTime === lastTime) return;
    try {
      if (freeze.width !== video.videoWidth || freeze.height !== video.videoHeight) { freeze.width = video.videoWidth; freeze.height = video.videoHeight; }
      freeze.getContext('2d').drawImage(video, 0, 0, freeze.width, freeze.height);
      lastTime = video.currentTime; hasFrame = true; freeze.hidden = true;
    } catch { /* 无法缓存时仍播放原始视频。 */ }
  }
  const cacheTimer = setInterval(cacheFrame, 250); // 保留断流前最近的已解码帧。
  function close(keepFrame) {
    if (keepFrame) cacheFrame();
    if (peer) peer.close(); peer = null; liveId = null; video.srcObject = null; lastTime = -1;
    freeze.hidden = !(keepFrame && hasFrame);
    if (!keepFrame) { hasFrame = false; freeze.width = 0; freeze.height = 0; }
  }
  async function play() {
    try { await video.play(); sound.hidden = true; }
    catch { sound.hidden = false; status.textContent = '请在 OBS 中右键浏览器源并选择交互，点击启用声音'; }
  }
  sound.onclick = play;
  async function connect(id) {
    close(true); busy = true;
    const connection = new RTCPeerConnection({iceServers:[]}); peer = connection; liveId = id;
    try {
      connection.addTransceiver('video',{direction:'recvonly'}); connection.addTransceiver('audio',{direction:'recvonly'});
      connection.ontrack = event => { if (peer === connection) { video.srcObject = event.streams[0]; play(); } };
      await connection.setLocalDescription(await connection.createOffer());
      await new Promise((resolve,reject) => {
        if (connection.iceGatheringState === 'complete') return resolve();
        const timer = setTimeout(() => reject(new Error('OBS 媒体协商超时')),10000);
        connection.onicegatheringstatechange = () => { if (connection.iceGatheringState === 'complete') { clearTimeout(timer); resolve(); } };
      });
      const answer = await request('answer',{type:'offer',sdp:connection.localDescription.sdp,live_id:id});
      if (peer !== connection) return;
      await connection.setRemoteDescription(answer);
      if (sound.hidden) status.textContent = '';
    } catch (error) {
      if (peer === connection) close(true);
      status.textContent = error.message; retryAfter = Date.now() + 5000;
    } finally { busy = false; }
  }
  async function poll() {
    if (stopped) return;
    if (!token) { status.textContent = '缺少 OBS 链接凭证，请从控制台复制完整链接'; return; }
    try {
      const state = await request('status');
      if (!state.media_connected || !state.live_id) {
        const ended = ['idle','stopped'].includes(state.state); // 用户手动停止时清空静态画面。
        if (!busy) close(!ended);
        status.textContent = ended ? '等待数字人通话媒体' : hasFrame ? '画面暂存 · 等待通话恢复' : '等待数字人通话媒体';
      } else if (!busy && Date.now() >= retryAfter && (liveId !== state.live_id || !peer || ['failed','closed','disconnected'].includes(peer.connectionState))) {
        await connect(state.live_id);
      } else if (peer?.connectionState === 'connected' && sound.hidden) status.textContent = '';
    } catch (error) {
      if (error.status === 401 || error.status === 403) { close(false); status.textContent = error.message; stopped = true; return; }
      status.textContent = '本地服务暂不可达，正在等待恢复';
    } finally { if (!stopped) setTimeout(poll,2000); }
  }
  window.addEventListener('pagehide', () => { stopped = true; clearInterval(cacheTimer); close(false); });
  poll();
})();
