# v0.4.0 实施与验证记录

实施范围：有头 Chrome 承载官方 SDK；WebRTC 轨道中继；校准 douyinLive v2 JSON；会话隔离采集和调度；默认通话授权；更新控制台、测试及开发手册。用户已授权继续实施及真实直播间测试。

## 真实测试证据（2026-10-30）

- 隐藏浏览器原有 net::ERR_FAILED；改成 headless=False 后，用户接口、claim、媒体和业务指令成功。
- 使用授权角色与独立测试通话；角色及通话标识已脱敏。
- 使用匿名直播间配置，不使用抖音登录 Cookie；房间标识已脱敏。
- 上游 ROOM_ONLINE；283 条标准化事件：33 评论、161 点赞事件、89 进场；点赞增量 1425。
- 入队 32、发送 21、回执接受 21；观察时过期丢弃 5，停止采集清空剩余队列。
- 一条真实评论收到匹配回执；评论正文及消息标识已脱敏。
- Studio WebRTC 视频 383×682，解码帧从 252 到 857；audio 和 video 均为 live。
- 音频接收能量 totalAudioEnergy=0.028201910091729728，证明不是只有空轨道。
- 页面刷新后播放器重新协商，五秒后已有 74 帧。
- 授权复选框 checked=true；截图 output/playwright/studio-live.png。

## 实现边界

官网 SDK 负责上游 RTC；本机 RTCPeerConnection 复用媒体元素的音视频轨道传给 Studio。自定义指令用 type 12，按 client_msg_id 匹配 type 14。浏览器仍是运行依赖，未移植为独立 Volcengine SDK 客户端。

每个 studio_session 有独立 LiveBridge；队列最大 30，过期 30 秒，默认最小间隔 3.5 秒；礼物优先。上游系统消息不当作弹幕；不认识的 protobuf 方法忽略。收到事件、排队、发送、接受、未知回执分别记录。

真实礼物未出现，仅解析与连击终包测试通过。自动恢复的模拟测试通过，但没有制造真实官网超时。新短信未重发，沿用用户已授权登录态。OBS 推流未完成。

## 依赖来源

参考 cyber-xiaoya/cyber-xiaoya-danmaku 的架构与接入说明，实际运行 jwwsjlm/douyinLive v2.3.2（MIT）官方 Windows 发布包，没有复制前者 AGPL 代码。使用实际默认端口 1088 和 /ws/{roomId} 路由。发布包 SHA256 与 release checksums.txt 一致。
