"""真实协议结构、会话隔离、优先级、节流和未知回执测试。"""
import asyncio
from app.adapters.douyin import DouyinAdapter
from app.domain.events import LiveEvent
from app.services.live_bridge import LiveBridge
from fastapi.testclient import TestClient
from app.main import app
from app.adapters.vidu_api import ViduModerationError


def test_real_protocol_fields_and_system_ignored():
    """实测 camelCase 字段与系统包严格区分。"""
    assert DouyinAdapter.normalize({'type':'system','code':'ROOM_ONLINE'}) is None
    event = DouyinAdapter.normalize({'method':'WebcastChatMessage','user':{'id':'1','nickname':'观众'},
        'content':'你好','common':{'msgId':'123'}})
    assert event.content == '你好' and event.event_id == '123'
    assert DouyinAdapter.normalize({'method':'WebcastGiftMessage','gift':{'type':1},'repeatEnd':0}) is None
    gift = DouyinAdapter.normalize({'method':'WebcastGiftMessage','gift':{'type':1,'name':'玫瑰'},'repeatEnd':1,'repeatCount':3})
    assert gift.gift_count == 3 and gift.gift_name == '玫瑰'


def test_event_types_keep_independent_history():
    """大量点赞不能挤掉评论，各类型历史保持有界。"""
    bridge = LiveBridge(None)
    bridge.receive(LiveEvent(event_type='comment', content='保留评论'))
    for _ in range(100):  # 模拟高频点赞。
        bridge.receive(LiveEvent(event_type='like', like_count=1))
    events = bridge.snapshot()['events']
    assert len([event for event in events if event['event_type'] == 'like']) == 80
    assert any(event['content'] == '保留评论' for event in events)


def test_export_contains_all_events_and_reconnect_clears():
    """完整导出不受显示上限影响，重新连接清除旧记录。"""
    async def run():
        bridge = LiveBridge(None)
        try:
            for index in range(100):  # 超过单类别展示上限。
                bridge.receive(LiveEvent(event_type='like', nickname=str(index)))
            assert len(bridge.snapshot()['events']) == 80
            assert len(bridge.archive.all()) == 100
            await bridge.start('123')
            assert bridge.archive.all() == []
            assert not bridge.snapshot()['events']
            await bridge.stop()
        finally:
            bridge.archive.close()
    asyncio.run(run())


def test_export_requires_session_and_returns_complete_records():
    """导出受会话保护，空记录提示明确，返回中文和最新调度状态。"""
    with TestClient(app) as client:
        headers = {'X-Studio-Request': '1'}
        assert client.get('/api/events/export', headers=headers).status_code == 401
        client.get('/api/vidu/status')
        assert client.get('/api/events/export', headers=headers).status_code == 404
        for index in range(90):  # 构造超过界面历史长度的事件。
            response = client.post('/api/danmaku', headers=headers, json={'event_type': 'like', 'nickname': f'观众{index}'})
            assert response.status_code == 200
        response = client.get('/api/events/export', headers=headers)
        assert response.status_code == 200
        assert len(response.json()['events']) == 90
        assert response.json()['events'][0]['nickname'] == '观众0'
        assert '_archive_sequence' not in response.text


def test_scheduler_priority_expiry_and_no_ambiguous_replay():
    """礼物先发，未连接不发，过期丢弃，超时不重放。"""
    async def run():
        class Call:
            """记录所有实际发送尝试，不伪造业务队列结果。"""
            status = 'starting'
            def __init__(self):
                self.sent = []
            async def send(self, text):
                self.sent.append(text)
                if len(self.sent) == 2:
                    raise TimeoutError()
                return {'accepted':True,'client_msg_id':'ack1'}
        now = [100.0]  # 可控的时间轴。
        call = Call()
        bridge = LiveBridge(call,lambda:now[0])
        bridge.set_warmup(True)
        other = LiveBridge(call,lambda:now[0])
        bridge.receive(LiveEvent(event_type='comment',nickname='甲',content='你好'))
        bridge.receive(LiveEvent(event_type='gift',nickname='乙',gift_name='花',gift_count=1))
        await bridge.dispatch_once()
        assert not call.sent and not other.queue
        call.status = 'connected'
        await bridge.dispatch_once()
        assert '花' in call.sent[0] and bridge.counts['accepted'] == 1
        await bridge.dispatch_once()
        assert len(call.sent) == 1
        now[0] += 4
        await bridge.dispatch_once()
        assert bridge.counts['failed'] == 1 and not bridge.queue
        await bridge.dispatch_once()
        assert len(call.sent) == 2
        bridge.receive(LiveEvent(event_type='comment',nickname='丙',content='过期'))
        now[0] += 31
        await bridge.dispatch_once()
        assert not bridge.queue and bridge.counts['dropped'] == 1
    asyncio.run(run())


def test_warmup_switch_greetings_and_queue_cleanup():
    """暖场开启后覆盖入场、点赞、礼物，关闭后清掉未发送的暖场事件。"""
    bridge = LiveBridge(None)
    try:
        bridge.receive(LiveEvent(event_type='enter', nickname='小明'))
        assert not bridge.queue
        bridge.set_warmup(True)
        for kind in ('enter', 'like', 'gift'):
            event = LiveEvent(event_type=kind, nickname='小明', gift_name='花')
            bridge.receive(event)
            assert '小明' in event.to_prompt()
        assert len(bridge.queue) == 3
        bridge.set_warmup(False)
        assert not bridge.queue
        assert bridge.counts['dropped'] == 3
    finally:
        bridge.archive.close()


def test_moderation_rejects_one_event_and_continues():
    """审核拒绝单条弹幕并记录，后续弹幕仍能发送。"""
    async def run():
        class Call:
            status = 'connected'
            calls = 0
            async def send(self, text):
                self.calls += 1
                if self.calls == 1:
                    raise ViduModerationError('内容审核未通过')
                return {'accepted': True}
        now = [100.0]  # 可控时间用于跳过发送间隔。
        call = Call()
        bridge = LiveBridge(call, lambda: now[0])
        try:
            bridge.receive(LiveEvent(event_type='comment', nickname='甲', content='第一条'))
            bridge.receive(LiveEvent(event_type='comment', nickname='乙', content='第二条'))
            await bridge.dispatch_once()
            assert bridge.history['comment'][0]['delivery'] == 'moderation_rejected'
            assert bridge.archive.all()[0]['delivery'] == 'moderation_rejected'
            now[0] += 4
            await bridge.dispatch_once()
            assert bridge.history['comment'][1]['delivery'] == 'accepted'
            assert call.calls == 2
        finally:
            bridge.archive.close()
    asyncio.run(run())
