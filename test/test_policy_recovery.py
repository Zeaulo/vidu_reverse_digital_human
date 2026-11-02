"""模拟官网审核结束、媒体变化和有限恢复，不连接外部平台。"""
import asyncio

from app.domain.events import LiveEvent
from app.adapters.vidu_browser import ViduBrowserApi
from app.services.call_recovery import CallRecovery
from app.services.live_bridge import LiveBridge
from test_recovery import FakeApi


def test_page_status_recognizes_only_complete_policy_notice():
    """在本地页面验证完整结束提示优先于信令，普通审核提示不触发。"""
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as driver:
            browser = await driver.chromium.launch(channel='chrome', headless=True)
            try:
                page = await browser.new_page()
                api = ViduBrowserApi()
                api.page = page
                await page.set_content('<body>审核未通过 当前内容不符合规范</body>')
                assert (await api.runtime_status())['reason'] is None
                await page.set_content('<body>通话已结束 当前内容不符合规范，直播已结束</body>')
                await page.evaluate("window.__studioVidu = {status: () => ({reason: 'audit_rejected'})}")
                assert (await api.runtime_status())['reason'] == 'content_policy_ended'
            finally:
                await browser.close()
    asyncio.run(run())


def test_policy_end_clears_queue_and_retries_once():
    """延迟出现结束文案后清空队列，只在新媒体连通后处理新事件。"""
    async def run():
        now = [100.0]  # 控制观察和五秒退避。
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        bridge = LiveBridge(call, clock=lambda: now[0])
        call.on_policy_pause = bridge.pause_for_policy
        call.on_policy_resume = bridge.resume_after_policy
        try:
            await call.start('123')
            bridge.receive(LiveEvent(event_type='comment', content='旧消息'))
            assert len(bridge.queue) == 1
            api.runtime = {'reason': 'audit_rejected', 'signal_open': False, 'source_live': False}
            await call.tick()
            assert call.status == 'audit_check'
            api.runtime = {'reason': 'content_policy_ended', 'source_live': False, 'signal_open': False}
            await call.tick()
            assert call.status == 'retry_wait' and bridge.policy_paused and not bridge.queue
            bridge.receive(LiveEvent(event_type='comment', content='暂停期间'))
            assert not bridge.queue and bridge.archive.all()[-1]['delivery'] == 'observed'
            now[0] += 5
            await call.tick()
            assert api.starts == 2 and call.policy_pending and bridge.policy_paused
            api.runtime = {'reason': None, 'media': True}
            await call.tick()
            assert call.status == 'connected' and not bridge.policy_paused
            bridge.receive(LiveEvent(event_type='comment', content='恢复之后'))
            assert len(bridge.queue) == 1
            api.runtime = {'reason': 'content_policy_ended', 'source_live': False, 'signal_open': False}
            await call.tick()
            assert call.status == 'attention' and not call.enabled and not bridge.queue
            assert api.starts == 2 and bridge.policy_paused
        finally:
            await call.stop()
            bridge.archive.close()
    asyncio.run(run())


def test_policy_end_preserves_progressing_video_and_disabled_auto():
    """官网仍在增帧时不重建，禁用自动恢复时也不会创建新会话。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123', auto_restart=False)
            api.runtime = {'reason': 'content_policy_ended', 'source_live': True, 'source_frames': 100}
            await call.tick()
            now[0] += 9
            api.runtime['source_frames'] = 120
            await call.tick()
            assert call.media_connected and call.status == 'audit_check' and api.starts == 1
            now[0] += 11
            await call.tick()
            assert call.status == 'attention' and api.starts == 1 and api.stops == 0
        finally:
            await call.stop()
    asyncio.run(run())


def test_policy_recovery_failure_and_manual_stop():
    """登录校验失败和退避期间手动停止都不会再次创建通话。"""
    async def run():
        now = [100.0]
        api = FakeApi()
        call = CallRecovery(api, clock=lambda: now[0])
        try:
            await call.start('123')
            api.runtime = {'reason': 'content_policy_ended', 'source_live': False}
            await call.tick()
            await call.stop()
            now[0] += 10
            await call.tick()
            assert api.starts == 1 and call.status == 'stopped'
            await call.start('123')
            api.runtime = {'reason': 'content_policy_ended', 'source_live': False}
            await call.tick()
            async def reject_login(*args):
                """模拟登录失效。"""
                raise RuntimeError('expired')
            api.request = reject_login
            now[0] += 5
            await call.tick()
            assert call.reason == 'policy_recovery_failed' and not call.enabled and api.starts == 2
        finally:
            await call.stop()
    asyncio.run(run())
