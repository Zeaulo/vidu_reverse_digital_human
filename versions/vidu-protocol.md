# Vidu 登录与指令接口实测记录

更新：v0.3.0 的排查与恢复状态见 recovery-v0.3.0.md；以下为 v0.2.0 历史实测，当前主接口已切换到浏览器网络运行环境。

记录日期：2026-10-30，版本：0.2.0。只记录协议与测试结果，不含真实手机号、验证码、Cookie 或媒体令牌。

## 已确认字段

| 字段 | 来源 | 作用 |
|---|---|---|
| JWT Cookie | POST /iam/v1/users/login 响应设置，域 service.vidu.cn，HttpOnly | 网页业务接口与 WebSocket 鉴权 |
| live.id | POST /live/v1/live/claim 响应 | live_id |
| rtc.user_id | 同一个 claim 响应 | 信令 user_id、RTC 用户标识 |
| rtc.token | 同一个 claim 响应 | 媒体 SDK 令牌，不等同于登录 JWT |
| rtc.app_id/channel_id/token_expire_at/rtc_provider | 同一个 claim 响应 | 媒体 SDK 初始化参数 |
| conn_id | WebSocket 初始化回执 | 当前信令连接标识，不能复用旧连接值 |

## 请求结构

短信接口 POST /iam/v1/users/send-auth-code：channel=sms，receiver=+86 加手机号，purpose=login，locale=en。

登录接口 POST /iam/v1/users/login：id_type=phone，identity=+86 加手机号，auth_type=authcode，credential=验证码，device_id=稳定的 DEVICE_ UUID，invite_code 与 team_invite_code 为空，receive_marketing_msg=false。

创建接口 POST /live/v1/live/claim：avatar_id=角色 ID，call_mode=video，live_mode=avatar，rtc_provider=volcengine。响应必须校验 is_success、live.id 和 rtc.user_id。

业务信令连接 wss://service.vidu.cn/live/ws/live/connect?live_id=会话ID。当前网页版通过 Cookie 鉴权；静态代码另有 token 参数路径，但不能把该路径与 Cookie 路径直接混用。

初始化发送 type=1、seq_id、live_id，等待 type=2 的 payload.conn_init_ack.success=true 和 conn_id。NOT_READY 在有限时间内重试。

文本发送 type=12、递增 seq_id、live_id、rtc.user_id 对应的 user_id、conn_id；payload.text_input 包含 client_msg_id、content、毫秒 timestamp。

成功依据为 type=14、payload.text_input_ack.client_msg_id 匹配且 accepted=true。此处仅证明接收，不证明音视频生成完成。type=6/10 表示结束，type=15 表示错误。超时不自动重发。

## 实测结果与限制

1. 手机验证码在官网登录成功；用户完成个人信息授权。
2. 会话准备曾等待麦克风授权。授权并刷新后取得 claim，业务 WS 初始化成功。
3. 在已有浏览器媒体会话中，新建 WebSocket，未操作输入框，发送测试指令，收到 type=14、accepted=true。
4. Cookie 经本机内存转交 Python 后，用户接口返回 HTTP 200 / text/html，未取得 JSON；Python 独立 WebSocket 未连接成功。未证明纯 Python 登录与发送可用，也未定位 HTML 响应的最终原因。
5. Studio 短信与登录入口已实现请求结构和内存会话，尚未完成真实端到端短信复测。不要自动重发短信或把接口失败显示为成功。
6. Studio 尚无 RTC SDK 播放器；claim 不会自行接通媒体。弹幕队列仍未接入自动调度，OBS 实际推流未验证。
7. test/test_vidu.py 验证 Cookie 接收、claim 字段映射、回执匹配、HTML 错误、跨站拒绝、凭据脱敏和会话隔离。模拟测试不代替服务端联调。
