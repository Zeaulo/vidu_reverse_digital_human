# v0.3.0 通话超时恢复实施与验证

用户已授权继续排查直连并增加自动重新开始通话。实现范围：浏览器内 HTTP、业务 WebSocket 发送、媒体状态观察、有限重建、Studio 开关和停止按钮。

## 新增证据

- Python 返回的 HTML 包含 EO_Bot_Ssid 与 __tst_status 的浏览器校验脚本。使用环境代理和关闭环境代理都返回此类页面，不能简单归因为代理设置。没有自行计算或伪造这些参数。
- 已有登录浏览器的用户接口返回 JSON；同账号新建隐藏浏览器仍为 net::ERR_FAILED，尚未定位该请求失败的最终原因。
- app/adapters/vidu_runtime.js 在已有登录浏览器实测成功：信令初始化完成、媒体采样显示视频帧到达、直接发送指令收到 accepted=true；之后主动发送用户挂断。
- 新建隐藏浏览器完整链路仍未通过，不能将以下状态机测试当成真实超时重连成功。

## 运行逻辑

1. Studio /api/vidu/claim 进入 CallRecovery.start，校验用户登录与已明确勾选的通话授权。
2. ViduBrowserApi 打开官网 live-pro 运行页，由官网建立 claim、RTC 与信令；无页面输入框发送行为。媒体输入使用测试音频设备，不采集实际麦克风。
3. vidu_runtime.js 复用官网业务 socket，统一递增 seq_id，type 12 文本与官网 type 11 媒体采样共享连接；type 14 按 client_msg_id 匹配。
4. 每 2 秒检查状态，只有 is_call_ready、视频轨道存在且帧到达才显示媒体连接。
5. 明确超时原因 client_reconnect_timeout、sip_reconnect_timeout、timeout_hangup、prepared_timeout、waiting_timeout、connection_lost 才进入自动重建。客户端准确显示“通话已结束”且“直播连接超时”时作为补充证据。
6. 退避 5/10/20 秒，每次手动开始最多重建三次。恢复成功不重置本轮预算。重建前挂断旧通话并校验登录，再创建新 live_id 和 RTC 连接。
7. 手动停止、额度到期、审核拒绝、服务端未知错误、登录失效不重建。90 秒媒体仍未就绪时停止并提示。
8. 指令回执未知不重发；恢复中不发送；停止先取消监控任务，再挂断，防止等待中的重启复活。

## 文件与验证

- app/adapters/vidu_browser.py：浏览器生命周期、HTTP、媒体页、信令调用。
- app/adapters/vidu_runtime.js：业务 socket 包装，不记录凭据或原始帧。
- app/services/call_recovery.py：有限恢复状态机。
- app/api/vidu.py：开始/状态/指令/停止/登录接口，与会话锁集成。
- web/assets/vidu.js：自动恢复开关、次数与倒计时、停止按钮。
- test/test_recovery.py：可控时钟验证预算、新 ID、取消、登录失效、不可恢复错误、无媒体。
- test/test_runtime.cjs：WebSocket 替身验证序号、回执匹配、挂断。
- test/network_probe.py、test/probe_browser.py：脱敏网络诊断与临时浏览器联调；不属于产品启动链路。

当前仍未完成：新建运行环境真实登录和通话、真实超时后的自动恢复、Studio 视频输出、弹幕队列调度、OBS 推流。
