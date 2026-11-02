"""通话超时恢复：有界退避、单实例监测、停止优先，不重放用户指令。"""

import asyncio
import time

from app.adapters.vidu_api import ViduError, ViduModerationError
from app.utils.diagnostics import record

RETRY_REASONS = {'client_reconnect_timeout', 'sip_reconnect_timeout', 'timeout_hangup',
                 'prepared_timeout', 'waiting_timeout', 'connection_lost', 'duration_limit'}  # 用户要求到达单次时长上限后尝试恢复。


class CallRecovery:
    """一次手动开始最多自动重建三次，成功后也不重置本轮预算。"""

    def __init__(self, api, clock=time.monotonic):
        """保存会话依赖与恢复状态；不保存登录凭据。"""
        self.api = api
        self.clock = clock
        self.lock = asyncio.Lock()  # 开始、恢复、发送互斥。
        self.task = None  # 单个后台监控任务。
        self.enabled = False  # 仅用户开始后启用。
        self.avatar_id = None
        self.attempts = 0
        self.next_retry = 0.0
        self.started_at = 0.0
        self.media_wait_since = None  # 记录本次媒体等待或中断的起点。
        self.status = 'idle'
        self.reason = None
        self.media_connected = False
        self.live_id = None
        self.generation = 0  # 用户停止时递增，阻止正在创建的旧请求重新开启监控。
        self.audit_check_since = None  # 审核原因首次出现的时间。
        self.audit_last_frames = None  # 上次采样的官网累计解码帧数。
        self.audit_last_progress = None  # 最近一次观察到实际解码帧增加的时间。
        self.policy_attempted = False  # 每次手动开始后，审核结束最多恢复一次。
        self.policy_pending = False  # 已创建新通话但尚未确认媒体恢复。
        self.policy_seen_since = None  # 官网页面明确结束提示的首次观察时间。
        self.policy_last_frames = None  # 结束提示出现后的官网累计解码帧。
        self.policy_last_progress = None  # 结束提示后最后一次观察到增帧的时间。
        self.on_policy_pause = lambda: None  # 按会话注入队列暂停回调。
        self.on_policy_resume = lambda: None  # 按会话注入队列恢复回调。

    def snapshot(self):
        """返回 Studio 需要的状态，不暴露 RTC 用户或令牌。"""
        return {'state': self.status, 'auto_restart': self.enabled, 'attempts': self.attempts,
                'max_attempts': 3, 'reason': self.reason, 'media_connected': self.media_connected,
                'live_id': self.live_id, 'policy_attempted': self.policy_attempted,
                'retry_in': max(0, round(self.next_retry-self.clock())) if self.next_retry else 0}

    async def start(self, avatar_id, auto_restart=True):
        """先停止上一轮，再建立新通话；用户同意在 API 层检查。"""
        await self.stop()
        generation = self.generation
        async with self.lock:
            self.avatar_id = avatar_id
            self.attempts = 0
            self.reason = None
            self.audit_check_since = self.audit_last_frames = self.audit_last_progress = None
            self.policy_attempted = self.policy_pending = False
            self.policy_seen_since = self.policy_last_frames = self.policy_last_progress = None
            self.on_policy_resume()  # 明确手动开启新一轮后允许接收新事件。
            self.enabled = auto_restart
            self.status = 'starting'
            try:
                result = await self.api.start_call(avatar_id)
            except ViduError:
                self.status = 'attention'
                self.enabled = False
                await self.api.stop_call()
                raise
            self.live_id = result['live_id']
            if generation != self.generation:
                await self.api.stop_call()
                self.live_id = None
                self.status = 'stopped'
                raise ViduError('通话创建已被用户停止')
            self.started_at = self.clock()
            self.media_wait_since = self.started_at
            self.task = asyncio.create_task(self.monitor())
            return {**result, **self.snapshot()}

    async def tick(self):
        """一次观察与恢复决策，拆出便于模拟时钟测试。"""
        async with self.lock:
            if self.status in ('stopped', 'idle', 'attention', 'exhausted'):
                return
            if not self.api.authenticated:
                self.status = 'attention'; self.reason = 'login_required'; self.enabled = False
                record('call_disconnected', 'login_required')
                self.media_connected = False
                await self.api.stop_call()
                self.live_id = None
                return
            runtime = await self.api.runtime_status()
            self.media_connected = runtime.get('media', False)
            reason = runtime.get('reason')
            if reason == 'content_policy_ended':
                await self.inspect_policy_end(runtime)
                return
            if reason == 'audit_rejected':
                self.inspect_audit(runtime)
                return
            if self.policy_pending and reason:
                self.status = 'attention'; self.reason = reason; self.enabled = False
                self.media_connected = False; self.policy_pending = False
                record('policy_recovery_failed', reason)
                return
            if self.media_connected and not reason:
                if self.policy_pending:
                    self.policy_pending = False
                    self.on_policy_resume()  # 新通话媒体连通后才处理新的直播事件。
                    record('policy_recovery_restored', 'content_policy_ended')
                self.media_wait_since = None  # 成功恢复后，下一次中断重新计时。
                self.status = 'connected'; self.reason = None; self.next_retry = 0
                return
            if not reason:
                self.status = 'starting'
                if self.media_wait_since is None:
                    self.media_wait_since = self.clock()  # 已连接通话发生媒体中断时，从中断开始计时。
                if self.clock() - self.media_wait_since > 90:
                    # 缺少明确结束原因时，不盲目创建下一通付费会话。
                    self.status = 'attention'; self.reason = 'media_not_ready'; self.enabled = False
                    self.policy_pending = False
                    record('call_disconnected', 'media_not_ready')
                    await self.api.stop_call()
                    self.live_id = None
                return
            self.reason = reason
            record('call_disconnected', reason)  # 只记录原因类别，不记录消息正文或账号。
            self.media_connected = False
            if reason not in RETRY_REASONS or not self.enabled:
                self.status = 'attention'; self.enabled = False
                await self.api.stop_call()
                self.live_id = None
                return
            if self.attempts >= 3:
                self.status = 'exhausted'; self.enabled = False
                await self.api.stop_call()
                self.live_id = None
                return
            if not self.next_retry:
                self.next_retry = self.clock() + (5, 10, 20)[self.attempts]
                self.status = 'retry_wait'
                return
            if self.clock() < self.next_retry:
                return
            self.attempts += 1
            self.next_retry = 0
            self.status = 'restarting'
            await self.api.stop_call()
            self.live_id = None
            # 重建前再次校验登录，避免 401 后不断 claim。
            await self.api.request('GET', '/iam/v1/users/me')
            result = await self.api.start_call(self.avatar_id)
            self.live_id = result['live_id']
            self.started_at = self.clock()
            self.media_wait_since = self.started_at
            self.reason = None
            self.status = 'starting'

    def inspect_audit(self, runtime):
        """审核原因出现后独立核验官网媒体，不主动跳页或创建新通话。"""
        now = self.clock()
        if self.audit_check_since is None:
            self.audit_check_since = now
            record('audit_check', 'audit_rejected')
        self.reason = 'audit_rejected'
        frames = runtime.get('source_frames')  # 官网视频累计解码帧。
        source_live = runtime.get('source_live') is True
        if source_live and isinstance(frames, (int, float)) and self.audit_last_frames is not None and frames > self.audit_last_frames:
            self.audit_last_progress = now
        if isinstance(frames, (int, float)):
            self.audit_last_frames = frames
        progressing = self.audit_last_progress is not None and now - self.audit_last_progress <= 10
        if source_live and progressing:
            self.media_connected = True
            self.status = 'audit_check'  # 画面继续播放，但信令已标记结束，暂停发送。
            self.next_retry = 0
            return
        if now - self.audit_check_since <= 10:
            self.status = 'audit_check'
            self.media_connected = source_live and frames is not None and frames > 0  # 短暂观察期间保留现有画面。
            return
        self.status = 'attention'
        self.media_connected = False
        self.enabled = False
        self.next_retry = 0
        record('audit_media_unavailable', 'audit_rejected')

    async def inspect_policy_end(self, runtime):
        """确认明确结束且视频停滞后，最多等待五秒并恢复一次。"""
        now = self.clock()  # 使用单调时钟控制观察和重试间隔。
        if self.policy_seen_since is None:
            self.policy_seen_since = now
            self.on_policy_pause()  # 队列清空后，恢复期间的新事件只做记录。
            record('policy_end_detected', 'content_policy_ended')
        self.reason = 'content_policy_ended'
        frames = runtime.get('source_frames')  # 官网视频累计解码帧。
        source_live = runtime.get('source_live') is True
        if source_live and isinstance(frames, (int, float)) and self.policy_last_frames is not None and frames > self.policy_last_frames:
            self.policy_last_progress = now
        if isinstance(frames, (int, float)):
            self.policy_last_frames = frames
        progressing = self.policy_last_progress is not None and now - self.policy_last_progress <= 10
        observing = now - self.policy_seen_since <= 10
        if source_live and (progressing or (observing and isinstance(frames, (int, float)) and frames > 0)):
            self.status = 'audit_check'; self.media_connected = True; self.next_retry = 0
            return
        if runtime.get('signal_open') is True and observing and self.next_retry == 0:
            self.status = 'audit_check'; self.media_connected = False
            return
        self.media_connected = False
        if not self.enabled or self.policy_attempted:
            self.status = 'attention'; self.enabled = False; self.next_retry = 0; self.policy_pending = False
            record('policy_recovery_stopped', 'content_policy_ended')
            return
        if not self.next_retry:
            self.next_retry = now + 5
            self.status = 'retry_wait'
            record('policy_recovery_wait', 'content_policy_ended')
            return
        if now < self.next_retry:
            return
        self.next_retry = 0; self.policy_attempted = True; self.policy_pending = True
        self.status = 'restarting'
        generation = self.generation  # 手动停止后旧恢复过程不能继续创建。
        record('policy_recovery_attempt', 'content_policy_ended')
        try:
            await self.api.stop_call()
            self.live_id = None
            if generation != self.generation:
                return
            await self.api.request('GET', '/iam/v1/users/me')
            if generation != self.generation:
                return
            result = await self.api.start_call(self.avatar_id)
            if generation != self.generation:
                await self.api.stop_call()
                return
        except Exception:
            self.status = 'attention'; self.reason = 'policy_recovery_failed'; self.enabled = False
            self.policy_pending = False
            record('policy_recovery_failed', 'policy_recovery_failed')
            return
        self.live_id = result['live_id']
        self.started_at = self.clock(); self.media_wait_since = self.started_at
        self.policy_seen_since = self.policy_last_frames = self.policy_last_progress = None
        self.reason = None; self.status = 'starting'

    async def monitor(self):
        """保持单个监控循环，任何未知错误停止自动创建。"""
        try:
            while self.status not in ('stopped', 'attention', 'exhausted'):
                await asyncio.sleep(2)
                await self.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.reason == 'audit_rejected':
                self.status = 'attention'; self.enabled = False; self.media_connected = False
                record('audit_media_unavailable', 'audit_rejected')  # 无法核验时保留页面，等待用户处理。
                return
            self.status = 'attention'; self.reason = 'recovery_failed'; self.enabled = False
            record('call_disconnected', 'recovery_failed')
            self.media_connected = False
            await self.api.stop_call()
            self.live_id = None

    async def send(self, text):
        """恢复期间不发送；已发送但未确认的指令不重播。"""
        async with self.lock:
            if self.status != 'connected':
                raise ViduError('通话媒体未就绪或正在恢复，请稍后发送')
            record('command_attempt')
            try:
                result = await self.api.send_message(text)
                record('command_accepted' if result.get('accepted') is True else 'command_unconfirmed')
                return result
            except ViduModerationError:
                record('command_moderation_rejected')
                raise
            except Exception:
                record('command_failed')
                raise

    async def stop(self):
        """先取消监控，再挂断；确保退避过程中点击停止不会复活。"""
        self.enabled = False
        self.generation += 1
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        async with self.lock:
            if self.status not in ('idle', 'stopped'):
                await self.api.stop_call()
            self.status = 'stopped'; self.media_connected = False; self.next_retry = 0; self.live_id = None
            self.media_wait_since = None
