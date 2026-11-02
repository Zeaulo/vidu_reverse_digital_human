"""用可控时钟验证超时重建、取消、预算和不可恢复事件。"""
import asyncio
from app.services.call_recovery import CallRecovery
from app.adapters.vidu_api import ViduError


class FakeApi:
    """不接触外部平台的媒体会话替身。"""
    def __init__(self):
        self.authenticated = True
        self.runtime = {'reason':None, 'media':False}
        self.starts = 0
        self.stops = 0
    async def start_call(self, avatar):
        """每次创建返回不同 ID。"""
        self.starts += 1
        self.runtime = {'reason':None, 'media':False}
        return {'live_id':str(self.starts)}
    async def stop_call(self):
        """记录挂断次数。"""
        self.stops += 1
    async def request(self, *args):
        """模拟仍有效的登录校验。"""
        return {}
    async def runtime_status(self):
        """返回测试设置的信令状态。"""
        return self.runtime


def test_timeout_retry_budget_and_new_id():
    """真实超时只按 5、10、20 秒恢复三次，成功不重置总预算。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda:now[0])
        try:
            await call.start('123')
            for index, delay in enumerate((5,10,20)):
                api.runtime = {'reason':'client_reconnect_timeout', 'media':False}
                await call.tick()
                assert call.status == 'retry_wait'
                now[0] += delay-1
                await call.tick()
                assert api.starts == index+1
                now[0] += 1
                await call.tick()
                assert api.starts == index+2
                api.runtime = {'reason':None, 'media':True}
                await call.tick()
                assert call.status == 'connected'
            api.runtime = {'reason':'client_reconnect_timeout', 'media':False}
            await call.tick()
            assert call.status == 'exhausted'
            assert api.starts == 4
        finally:
            await call.stop()
    asyncio.run(run())


def test_stop_cancels_retry_and_login_expiry_blocks_restart():
    """停止取消待执行的重启；失效登录不会继续创建。"""
    async def run():
        now = [100.]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda:now[0])
        await call.start('123')
        api.runtime = {'reason':'timeout_hangup'}
        await call.tick()
        await call.stop()
        now[0] += 30
        await call.tick()
        assert api.starts == 1
        assert call.task is None
        await call.start('123')
        api.authenticated = False
        await call.tick()
        assert call.reason == 'login_required'
        assert not call.enabled
        await call.stop()
    asyncio.run(run())


def test_no_retry_for_user_stop_quota_or_unknown():
    """不把手动挂断、额度结束和未知失败误当连接超时。"""
    async def run():
        for reason in ('user_hangup','duration_expired','server_error','browser_closed'):
            api = FakeApi()
            call = CallRecovery(api)
            await call.start('123')
            api.runtime = {'reason':reason}
            await call.tick()
            assert not call.enabled and api.starts == 1
            await call.stop()
    asyncio.run(run())


def test_audit_keeps_live_media_without_restart_or_page_navigation():
    """审核标记出现时，官网帧持续增加则保留通话，停止增帧后提示处理。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123')
            api.runtime = {'reason': 'audit_rejected', 'media': False, 'signal_open': True, 'source_live': True, 'source_frames': 100}
            await call.tick()
            assert call.status == 'audit_check' and call.media_connected
            now[0] += 2
            api.runtime['source_frames'] = 130
            await call.tick()
            assert call.status == 'audit_check' and call.media_connected
            assert api.stops == 0 and api.starts == 1
            api.runtime['signal_open'] = False  # 即使业务信令关闭，只要官网视频持续更新仍保留画面。
            api.runtime['source_frames'] = 150
            now[0] += 2
            await call.tick()
            assert call.status == 'audit_check' and call.media_connected and api.stops == 0
            try:
                await call.send('测试')
                assert False, '审核检查期间不能发送'
            except ViduError:
                pass
            now[0] += 11
            await call.tick()
            assert call.status == 'attention' and not call.media_connected
            assert api.stops == 0 and api.starts == 1 and not call.enabled
        finally:
            await call.stop()
    asyncio.run(run())


def test_audit_with_closed_signal_does_not_recreate_or_navigate():
    """审核后短暂等待官网结束提示，超时后保留页面供用户处理。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123')
            api.runtime = {'reason': 'audit_rejected', 'signal_open': False, 'source_live': False, 'source_frames': 0}
            await call.tick()
            assert call.status == 'audit_check'
            now[0] += 11
            await call.tick()
            assert call.status == 'attention' and not call.enabled
            assert api.stops == 0 and api.starts == 1
        finally:
            await call.stop()
    asyncio.run(run())


def test_media_timeout_stops_instead_of_claim_loop():
    """无媒体证据时停止而不反复消耗会话额度。"""
    async def run():
        now = [100.]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda:now[0])
        await call.start('123')
        now[0] += 91
        await call.tick()
        assert call.reason == 'media_not_ready'
        assert api.starts == 1 and api.stops == 1
        await call.stop()
    asyncio.run(run())


def test_failed_command_does_not_stop_healthy_call():
    """单条指令被拒绝后，只要媒体仍连接就不能主动挂断。"""
    async def run():
        api = FakeApi()
        async def reject_message(text):
            raise ViduError('服务端拒绝或指令状态未知')
        api.send_message = reject_message
        call = CallRecovery(api)
        try:
            await call.start('123')
            api.runtime = {'reason': None, 'media': True}
            await call.tick()
            try:
                await call.send('测试指令')
                assert False, '模拟的指令应被拒绝'
            except ViduError:
                pass
            await call.tick()
            assert call.status == 'connected'
            assert api.stops == 0
            assert api.starts == 1
        finally:
            await call.stop()
    asyncio.run(run())


def test_media_loss_uses_loss_time_not_call_start():
    """长时间通话后短暂丢帧不应被当成已经失联九十秒。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123')
            api.runtime = {'reason': None, 'media': True}
            await call.tick()
            now[0] += 300
            api.runtime = {'reason': None, 'media': False}
            await call.tick()
            assert api.stops == 0
            now[0] += 89
            await call.tick()
            assert api.stops == 0
            now[0] += 2
            await call.tick()
            assert api.stops == 1 and call.reason == 'media_not_ready'
        finally:
            await call.stop()
    asyncio.run(run())


def test_duration_limit_retries_and_honors_manual_stop():
    """单次时长到限后按退避恢复，手动停止时不能复活。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123')
            api.runtime = {'reason': 'duration_limit', 'media': False}
            await call.tick()
            assert call.status == 'retry_wait' and call.attempts == 0
            now[0] += 5
            await call.tick()
            assert api.starts == 2 and call.attempts == 1
            api.runtime = {'reason': 'duration_limit', 'media': False}
            await call.tick()
            assert call.status == 'retry_wait'
            await call.stop()
            now[0] += 30
            await call.tick()
            assert api.starts == 2 and call.status == 'stopped'
        finally:
            await call.stop()
    asyncio.run(run())
