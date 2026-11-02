// 浏览器业务信令桥：复用官网连接，所有指令走 WebSocket，不操作输入控件。
(() => {
  if (window.__studioVidu) return;
  const NativeSocket = window.WebSocket; // 原生连接类，用于保留 RTC 内部连接行为。
  const state = {ready:false, media:false, reason:null, liveId:null, userId:null, connId:null};
  const pending = new Map(); // 当前等待回执的业务指令。
  let active = null; // 官网创建的业务信令连接。
  let sequence = 0; // 同一 socket 统一管理序号，避免与页面心跳冲突。
  let lastMedia = 0; // 最新媒体状态采样时刻。
  let errorTimer = null; // 等待审核提示出现，用于区分消息拒绝与未知服务错误。
  let recentModeration = 0; // 仅在有待处理消息时记录审核提示时间。

  function finishPending(error, code) {
    // 连接结束时立即结束等待，不重发状态不明的指令。
    for (const item of pending.values()) { clearTimeout(item.timer); item.resolve({error, ...(code ? {code} : {})}); }
    pending.clear();
  }

  window.WebSocket = class extends NativeSocket {
    constructor(...args) {
      super(...args);
      const url = new URL(String(args[0]), location.href); // 只接管固定服务的业务 socket。
      this.studioSignal = url.hostname === 'service.vidu.cn' && url.pathname === '/live/ws/live/connect';
      if (!this.studioSignal) return;
      if (errorTimer) clearTimeout(errorTimer); errorTimer = null; recentModeration = 0; // 旧连接的延迟错误不能污染新会话。
      if (active) finishPending('连接已替换，未自动重发');
      active = this; sequence = 0;
      Object.assign(state, {ready:false, media:false, reason:null, liveId:url.searchParams.get('live_id'), connId:null, userId:null});
      this.addEventListener('message', event => {
        if (active !== this) return;
        try {
          const frame = JSON.parse(String(event.data)); // 只在内存解析服务器信令。
          if (frame.conn_id) state.connId = frame.conn_id;
          if (frame.type === 2) {
            state.ready = frame.payload?.conn_init_ack?.success === true;
            const code = frame.payload?.conn_init_ack?.error_code;
            if (!state.ready && code !== 'NOT_READY') state.reason = 'init_rejected';
          }
          if (frame.type === 6 || frame.type === 10) {
            state.reason = frame.payload?.hangup?.hangup_reason || (frame.type === 10 ? 'timeout_hangup' : 'server_hangup');
            state.ready = false; state.media = false;
            finishPending(state.reason === 'audit_rejected' ? '收到审核提示，正在检查通话状态' : '会话已结束');
          }
          if (frame.type === 15) {
            const connection = this; // 错误必须归属于当前连接。
            const affected = [...pending.keys()]; // 只结束收到错误时正在等待的消息。
            if (errorTimer) clearTimeout(errorTimer);
            if (recentModeration && pending.size === 0 && Date.now() - recentModeration < 3000) { recentModeration = 0; }
            else {
              errorTimer = setTimeout(() => {
                errorTimer = null;
                if (active !== connection) return;
                for (const id of affected) { // 未关联到的后续消息不能被误判失败。
                  const item = pending.get(id);
                  if (!item) continue;
                  clearTimeout(item.timer); pending.delete(id);
                  item.resolve({error:'服务端拒绝或指令状态未知，请检查内容后重试'});
                }
              }, 3000); // 等待可能出现的审核提示，未知错误只影响对应消息。
            }
          }
          if (frame.type === 14) {
            const ack = frame.payload?.text_input_ack;
            const item = pending.get(ack?.client_msg_id);
            if (item) {
              clearTimeout(item.timer); pending.delete(ack.client_msg_id);
              item.resolve(ack.accepted === true ? {accepted:true, client_msg_id:ack.client_msg_id} : {error:'服务端未接受指令'});
            }
          }
        } catch {}
      });
      this.addEventListener('close', () => {
        if (active !== this) return;
        if (errorTimer) clearTimeout(errorTimer); errorTimer = null;
        if (!state.reason) state.reason = 'connection_lost'; // 明确标记未解释的业务连接断开。
        state.ready = false; state.media = false; finishPending('连接断开，未自动重发');
      });
    }

    send(raw) {
      // 官网心跳和 Studio 指令共享递增序号，其余 WebSocket 完全透传。
      if (!this.studioSignal) return super.send(raw);
      const frame = JSON.parse(String(raw));
      frame.seq_id = sequence++;
      if (frame.user_id) state.userId = frame.user_id;
      if (frame.type === 11) {
        const media = frame.payload?.media_status;
        state.media = Boolean(media?.is_call_ready && media?.has_video_track && media?.video_frames_received_delta_3s > 0);
        lastMedia = Date.now();
      }
      if (frame.type === 5) {
        state.reason = frame.payload?.hangup?.hangup_reason || 'user_hangup';
        state.ready = false; state.media = false;
      }
      return super.send(JSON.stringify(frame));
    }
  };

  window.__studioVidu = {
    moderationRejected() {
      // 仅官网明确显示审核拒绝且存在唯一待发送消息时，认定该消息被拒绝。
      if (pending.size !== 1) return;
      recentModeration = Date.now();
      if (errorTimer) clearTimeout(errorTimer); errorTimer = null;
      finishPending('内容审核未通过，请修改后重试', 'moderation_rejected');
    },
    status() {
      // 不把媒体 token、JWT 或完整帧暴露给 Studio。
      return {...state, media:state.media && Date.now() - lastMedia < 12000, signal_open:!!active && active.readyState === NativeSocket.OPEN};
    },
    send(text) {
      if (!active || active.readyState !== NativeSocket.OPEN || !state.ready || !state.connId || !state.userId)
        return Promise.resolve({error:'信令尚未就绪'});
      const id = crypto.randomUUID(); // 新业务消息标识，仅用于回执匹配。
      return new Promise(resolve => {
        const timer = setTimeout(() => {pending.delete(id); resolve({error:'回执超时，未自动重发'});}, 15000);
        pending.set(id, {resolve, timer});
        try {
          active.send(JSON.stringify({type:12, user_id:state.userId, conn_id:state.connId, live_id:state.liveId,
            payload:{text_input:{client_msg_id:id, content:text, timestamp:Date.now()}}}));
        } catch {clearTimeout(timer); pending.delete(id); resolve({error:'信令发送失败'});}
      });
    },
    stop() {
      if (errorTimer) clearTimeout(errorTimer); errorTimer = null;
      if (active?.readyState === NativeSocket.OPEN) active.send(JSON.stringify({type:5,
        user_id:state.userId, conn_id:state.connId, live_id:state.liveId, payload:{hangup:{hangup_reason:'user_hangup'}}}));
      state.reason = 'user_hangup'; state.ready = false; state.media = false;
      finishPending('用户已停止');
    }
  };
})();
