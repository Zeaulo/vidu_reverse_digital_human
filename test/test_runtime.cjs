// 使用本地 WebSocket 替身验证混合发送序号、回执匹配和停止行为。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
class FakeSocket {
  static OPEN = 1;
  // 保存消息和事件处理器，避免接触任何外部服务。
  constructor() {this.readyState=1; this.events={}; this.frames=[];}
  addEventListener(name, callback) {(this.events[name] ||= []).push(callback);}
  send(raw) {this.frames.push(JSON.parse(raw));}
  emit(frame) {for(const cb of this.events.message||[]) cb({data:JSON.stringify(frame)});}
}
const context={window:{WebSocket:FakeSocket},location:{href:'https://www.vidu.cn'},URL,Date,Map,JSON,Boolean,
  crypto:{randomUUID},setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync('app/adapters/vidu_runtime.js','utf8'), context);
(async()=>{
  const socket=new context.window.WebSocket('wss://service.vidu.cn/live/ws/live/connect?live_id=123');
  socket.send(JSON.stringify({type:1,seq_id:0}));
  socket.emit({type:2,conn_id:'connection',payload:{conn_init_ack:{success:true}}});
  socket.send(JSON.stringify({type:11,seq_id:1,user_id:'user',payload:{media_status:{is_call_ready:true,has_video_track:true,video_frames_received_delta_3s:3}}}));
  const pending=context.window.__studioVidu.send('测试');
  const frame=socket.frames.at(-1);
  assert.equal(frame.type,12);
  socket.emit({type:14,payload:{text_input_ack:{client_msg_id:'wrong',accepted:true}}});
  socket.emit({type:14,payload:{text_input_ack:{client_msg_id:frame.payload.text_input.client_msg_id,accepted:true}}});
  assert.equal((await pending).accepted,true);
  const moderated = context.window.__studioVidu.send('被审核拒绝的指令'); // 真实审核结果用替身模拟，不触发平台审核。
  socket.emit({type:15});
  context.window.__studioVidu.moderationRejected();
  assert.equal((await moderated).code, 'moderation_rejected');
  assert.equal(context.window.__studioVidu.status().reason, null);
  assert.equal(context.window.__studioVidu.status().ready, true);
  const nextMessage = context.window.__studioVidu.send('下一条指令'); // 审核拒绝后仍可发送。
  const nextFrame = socket.frames.at(-1);
  socket.emit({type:14,payload:{text_input_ack:{client_msg_id:nextFrame.payload.text_input.client_msg_id,accepted:true}}});
  assert.equal((await nextMessage).accepted,true);
  socket.send(JSON.stringify({type:11,seq_id:2,user_id:'user'}));
  assert.deepEqual(socket.frames.map(f=>f.seq_id),[0,1,2,3,4,5]);
  context.window.__studioVidu.stop();
  assert.equal(socket.frames.at(-1).type,5);
  assert.equal(context.window.__studioVidu.status().reason,'user_hangup');
  const next = new context.window.WebSocket('wss://service.vidu.cn/live/ws/live/connect?live_id=456'); // 独立模拟未解释的断线。
  for (const callback of next.events.close || []) callback({});
  assert.equal(context.window.__studioVidu.status().reason, 'connection_lost');
  const unknown = new context.window.WebSocket('wss://service.vidu.cn/live/ws/live/connect?live_id=789'); // 未匹配弹窗的指令错误不能挂断通话。
  unknown.send(JSON.stringify({type:1,seq_id:0}));
  unknown.emit({type:2,conn_id:'connection',payload:{conn_init_ack:{success:true}}});
  unknown.send(JSON.stringify({type:11,user_id:'user',payload:{media_status:{is_call_ready:true,has_video_track:true,video_frames_received_delta_3s:1}}}));
  const unconfirmed = context.window.__studioVidu.send('未知错误测试');
  unknown.emit({type:15});
  assert.equal((await unconfirmed).error, '服务端拒绝或指令状态未知，请检查内容后重试');
  assert.equal(context.window.__studioVidu.status().reason, null);
  assert.equal(context.window.__studioVidu.status().ready, true);
  assert.equal(unknown.frames.some(frame => frame.type === 5), false); // 未发生主动挂断。
  const afterFailure = context.window.__studioVidu.send('后续消息');
  const afterFailureFrame = unknown.frames.at(-1);
  unknown.emit({type:14,payload:{text_input_ack:{client_msg_id:afterFailureFrame.payload.text_input.client_msg_id,accepted:true}}});
  assert.equal((await afterFailure).accepted,true);
  unknown.emit({type:6,payload:{hangup:{hangup_reason:'audit_rejected'}}}); // 审核原因本身不触发本机主动挂断。
  assert.equal(context.window.__studioVidu.status().reason, 'audit_rejected');
  assert.equal(context.window.__studioVidu.status().signal_open, true);
  assert.equal(unknown.frames.some(frame => frame.type === 5), false);
  unknown.readyState = 3; // 模拟浏览器在 close 事件前更新连接状态。
  for (const callback of unknown.events.close || []) callback({});
  assert.equal(context.window.__studioVidu.status().signal_open, false); // 审核后真实断线仍可辨识。
  console.log('runtime sequence / ack / stop: passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
