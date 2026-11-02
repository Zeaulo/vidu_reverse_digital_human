// 将官方 SDK 的远端音视频轨道通过本机 WebRTC 发送到 Studio，不抓屏。
(() => {
  const peers = new Map(); // 控制台与 OBS 分别保留自己的接收连接。
  const senders = new Map(); // 每个接收端独立视频发送器。
  let sourceTrack = null; // 官方 SDK 的原始视频轨道，仅用于读取尺寸。
  let videoSender = null; // 本机转发的视频发送端。
  let tuning = '未设置'; // 编码优化结果，不影响媒体协商成功。
  async function configure(sender, percent) {
    // 优先保持分辨率：拥塞时允许浏览器先降低帧率；不改变官方原始轨道。
    function verified(detail) {
      try {
        const scale = sender.getParameters().encodings?.[0]?.scaleResolutionDownBy; // 回读设置，不能把请求成功误报为生效。
        return typeof scale === 'number' && Math.abs(scale - 100 / percent) < 0.01
          ? {applied:true, detail} : {applied:false, detail:'浏览器未确认所选缩放比例'};
      } catch { return {applied:false, detail:'无法读取浏览器编码参数'}; }
    }
    let parameters;
    try { parameters = sender.getParameters(); }
    catch { return {applied:false, detail:'浏览器未提供编码参数'}; }
    if (!parameters.encodings?.length) return {applied:false, detail:'浏览器未提供编码参数'};
    for (const encoding of parameters.encodings) { encoding.scaleResolutionDownBy = 100 / percent; encoding.maxBitrate = 8000000; }
    parameters.degradationPreference = 'maintain-resolution';
    try { await sender.setParameters(parameters); }
    catch {
      // 旧版浏览器不支持画质优先属性时，仍尝试设置缩放比例。
      try {
        const fallback = sender.getParameters();
        if (!fallback.encodings?.length) return {applied:false, detail:'浏览器未提供编码参数'};
        for (const encoding of fallback.encodings) { encoding.scaleResolutionDownBy = 100 / percent; encoding.maxBitrate = 8000000; }
        await sender.setParameters(fallback);
        return verified('比例已设置；浏览器不支持分辨率优先');
      } catch { return {applied:false, detail:'浏览器未接受编码参数'}; }
    }
    return verified('比例已设置；请求分辨率优先');
  }
  window.__studioMedia = {
    stop() { for (const peer of peers.values()) peer.close(); peers.clear(); senders.clear(); sourceTrack = null; videoSender = null; tuning = '未设置'; },
    closeTarget(target) { const peer = peers.get(target); if (peer) peer.close(); peers.delete(target); senders.delete(target); }, // 只关闭指定接收端。
    async setQuality(percent) {
      if (![100,80,50].includes(percent)) throw new Error('无效转发比例');
      const results = {}; // 分别报告控制台与 OBS 的应用结果。
      for (const [target, sender] of senders) results[target] = await configure(sender, percent);
      if (results.studio) tuning = results.studio.detail;
      return results;
    },
    async answer(offer, target = 'studio', percent = 100) {
      if (!['studio', 'obs'].includes(target)) throw new Error('无效媒体接收端');
      if (![100,80,50].includes(percent)) throw new Error('无效转发比例');
      if (peers.has(target)) peers.get(target).close(); // 仅替换同一接收端，避免互相挤掉。
      senders.delete(target);
      const tracks = new Map(); // 按轨道 ID 去重，包含独立 audio 元素。
      for (const element of document.querySelectorAll('video,audio')) {
        for (const track of element.srcObject?.getTracks?.() || []) {
          if (track.readyState === 'live') tracks.set(track.id, track);
        }
      }
      if (![...tracks.values()].some(track => track.kind === 'video')) throw new Error('媒体未就绪');
      const stream = new MediaStream([...tracks.values()]); // 只复用轨道，不停止 SDK 原始轨道。
      sourceTrack = stream.getVideoTracks()[0];
      const connection = new RTCPeerConnection({iceServers:[]}); // 本机直连，无第三方 TURN。
      peers.set(target, connection);
      connection.addEventListener('connectionstatechange', () => {
        if (['failed','closed'].includes(connection.connectionState) && peers.get(target) === connection) { peers.delete(target); senders.delete(target); }
      }); // 清理失效接收端，避免旧连接影响新连接。
      let targetSender = null; // 当前接收端的视频发送器。
      for (const track of stream.getTracks()) { // 只调整视频发送端，不修改原始轨道。
        const sender = connection.addTrack(track, stream);
        if (track.kind === 'video') { targetSender = sender; if (target === 'studio') videoSender = sender; }
      }
      await connection.setRemoteDescription(offer);
      await connection.setLocalDescription(await connection.createAnswer());
      const result = await configure(targetSender, percent); // 设置失败时保持浏览器默认画质，继续播放。
      if (target === 'studio') tuning = result.detail;
      if (peers.get(target) !== connection) throw new Error('媒体接收端已替换');
      senders.set(target, targetSender);
      await new Promise((resolve, reject) => {
        if (connection.iceGatheringState === 'complete') return resolve();
        const timer = setTimeout(() => reject(new Error('本机媒体协商超时')), 10000);
        connection.addEventListener('icegatheringstatechange', () => {
          if (connection.iceGatheringState === 'complete') {clearTimeout(timer); resolve();}
        });
      });
      if (peers.get(target) !== connection) throw new Error('媒体接收端已替换');
      return {type:connection.localDescription.type,sdp:connection.localDescription.sdp};
    },
    async quality() {
      // 只暴露分辨率和发送统计，不传递轨道、令牌或 SDP。
      const settings = sourceTrack?.getSettings?.() || {};
      const result = {source_width:settings.width || null, source_height:settings.height || null,
        source_fps:settings.frameRate || null, tuning, sent_width:null, sent_height:null, sent_fps:null, sent_bytes:null, sent_timestamp:null,
        limitation:null, applied_scale:null, degradation_preference:null, obs_active:senders.has('obs'), obs_width:null, obs_height:null, obs_fps:null, obs_limitation:null, obs_scale:null};
      if (videoSender) {
        try {
          const params = videoSender.getParameters(); // 实际参数回读和统计不可混为一谈。
          result.applied_scale = params.encodings?.[0]?.scaleResolutionDownBy ?? null;
          result.degradation_preference = params.degradationPreference ?? null;
          const stats = await videoSender.getStats();
          for (const stat of stats.values()) {
            if (stat.type === 'outbound-rtp' && (stat.kind === 'video' || stat.mediaType === 'video')) {
              result.sent_width = stat.frameWidth || null; result.sent_height = stat.frameHeight || null;
              result.sent_fps = stat.framesPerSecond || null; result.sent_bytes = stat.bytesSent ?? null; result.sent_timestamp = stat.timestamp ?? null;
              result.limitation = stat.qualityLimitationReason || null;
            }
          }
        } catch { /* 统计不可用时保留空值，播放不受影响。 */ }
      }
      if (senders.has('obs')) {
        try {
          result.obs_scale = senders.get('obs').getParameters().encodings?.[0]?.scaleResolutionDownBy ?? null;
          for (const stat of (await senders.get('obs').getStats()).values()) {
            if (stat.type === 'outbound-rtp' && (stat.kind === 'video' || stat.mediaType === 'video')) {
              result.obs_width = stat.frameWidth || null; result.obs_height = stat.frameHeight || null;
              result.obs_fps = stat.framesPerSecond || null; result.obs_limitation = stat.qualityLimitationReason || null;
            }
          }
        } catch { /* OBS 统计不可用时不影响控制台。 */ }
      }
      return result;
    }
  };
})();
