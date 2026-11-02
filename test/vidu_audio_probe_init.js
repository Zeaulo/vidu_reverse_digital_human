// 仅供隔离测试：记录信令结构和 RTC 音频指标，不记录凭据或消息内容。
(() => {
  const probe = window.__audioProbe = {signals:[], peers:[], audioRequests:0, started:false}; // 当前测试的脱敏状态。
  const NativeSocket = window.WebSocket; // 官网业务信令仍使用原连接。
  window.WebSocket = class extends NativeSocket {
    constructor(...args) {
      super(...args);
      const url = new URL(String(args[0]), location.href); // 限定官网业务信令。
      this.inspect = url.hostname === 'service.vidu.cn' && url.pathname === '/live/ws/live/connect';
      if (this.inspect) this.addEventListener('message', event => record('in', event.data));
    }
    send(data) { if (this.inspect) record('out', data); return super.send(data); }
  };
  function record(direction, data) {
    // 只记录类型和字段名称，不保留正文、身份、连接参数或密钥。
    if (typeof data !== 'string') { probe.signals.push({direction, binary:true, bytes:data?.byteLength ?? data?.size ?? null}); return; }
    try {
      const frame = JSON.parse(data);
      probe.signals.push({direction, type:frame.type ?? null, payloadKeys:Object.keys(frame.payload || {})});
    } catch { probe.signals.push({direction, nonJson:true}); }
    if (probe.signals.length > 150) probe.signals.shift();
  }
  const NativePeer = window.RTCPeerConnection; // 只采样本页创建的 RTC 连接指标。
  if (NativePeer) window.RTCPeerConnection = class extends NativePeer {
    constructor(...args) { super(...args); probe.peers.push(this); }
  };
  const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  let context = null, destination = null, decoded = null, analyser = null; // 用户音频模拟为当前测试页的本地麦克风。
  navigator.mediaDevices.getUserMedia = async constraints => {
    const stream = await originalGetUserMedia(constraints); // 保留官网所需的其他设备行为。
    if (!constraints?.audio) return stream;
    probe.audioRequests++;
    if (!context) {
      context = new AudioContext(); destination = context.createMediaStreamDestination();
      const binary = Uint8Array.from(atob(window.__audioProbeSample), char => char.charCodeAt(0));
      decoded = context.decodeAudioData(binary.buffer);
    }
    for (const track of stream.getAudioTracks()) track.stop(); // 仅停止本测试请求创建的假麦克风。
    return new MediaStream([...stream.getVideoTracks(), ...destination.stream.getAudioTracks()]);
  };
  probe.play = async () => {
    if (!context || !decoded) return false;
    await context.resume();
    const source = context.createBufferSource(); source.buffer = await decoded;
    analyser = context.createAnalyser(); source.connect(analyser); analyser.connect(destination);
    source.start(); probe.started = true;
    return true;
  };
  probe.inputLevel = () => {
    if (!analyser) return 0;
    const data = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(data);
    return Math.sqrt(data.reduce((total, value) => total + value * value, 0) / data.length);
  }; // 仅保存能量指标，不输出音频内容。
  probe.audioStats = async () => {
    let bytes = 0, packets = 0, encoders = 0, receivedBytes = 0, receivers = 0, matchingSenders = 0, totalAudioEnergy = 0; // 分别统计发送与接收。
    for (const peer of probe.peers) {
      try {
        matchingSenders += peer.getSenders().filter(sender => sender.track?.kind === 'audio' && sender.track.id === destination?.stream.getAudioTracks()[0]?.id).length;
        for (const stat of (await peer.getStats()).values()) {
          if (stat.type === 'outbound-rtp' && (stat.kind === 'audio' || stat.mediaType === 'audio')) {
            bytes += stat.bytesSent || 0; packets += stat.packetsSent || 0; encoders++;
          }
          if (stat.type === 'inbound-rtp' && (stat.kind === 'audio' || stat.mediaType === 'audio')) {
            receivedBytes += stat.bytesReceived || 0; receivers++;
          }
          if (stat.type === 'media-source' && (stat.kind === 'audio' || stat.mediaType === 'audio')) totalAudioEnergy += stat.totalAudioEnergy || 0;
        }
      } catch { /* 忽略已关闭的 RTC 连接。 */ }
    }
    return {bytes, packets, encoders, receivedBytes, receivers, matchingSenders, totalAudioEnergy};
  };
  probe.startRecording = async () => {
    // 仅录制远端 RTC 接收轨道，不能把本地输入误判成数字人输出。
    let track = null;
    for (const peer of probe.peers) for (const receiver of peer.getReceivers()) {
      if (receiver.track?.kind !== 'audio' || receiver.track.readyState !== 'live' || receiver.track.muted) continue;
      try {
        const stats = await receiver.getStats();
        if ([...stats.values()].some(stat => stat.type === 'inbound-rtp' && (stat.bytesReceived || 0) > 0)) { track = receiver.track; break; }
      } catch { /* 忽略不可读取的接收端。 */ }
    }
    if (!track || !window.MediaRecorder) return false;
    const chunks = []; const recorder = new MediaRecorder(new MediaStream([track]), {mimeType:'audio/webm;codecs=opus'});
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    probe.recorded = new Promise(resolve => { recorder.onstop = () => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.readAsDataURL(new Blob(chunks,{type:'audio/webm'})); }; });
    probe.recorder = recorder; recorder.start(1000); return true;
  };
  probe.stopRecording = async () => {
    if (!probe.recorder || probe.recorder.state === 'inactive') return null;
    probe.recorder.stop(); return await probe.recorded;
  };
})();
