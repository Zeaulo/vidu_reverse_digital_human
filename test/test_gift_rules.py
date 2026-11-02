"""礼物规则、独立互动开关与接口隔离的行为测试。"""
import asyncio
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import app
from app.services.live_bridge import LiveBridge
from app.services.gift_rules import GiftRule, GiftRulesBody
from app.services.gift_images import safe_gift_image
from app.domain.events import LiveEvent
from test_gifts import packet


def test_threshold_late_growth_and_thanks():
    """暂结未达门槛不发送，迟到增长只触发一次并先答谢。"""
    async def run():
        class Call:
            """仅记录接口收到的文本，不连接真实 Vidu。"""
            status = 'connected'
            def __init__(self):
                self.sent = []
            async def send(self, text):
                self.sent.append(text)
                return {'accepted': True}
        now = [100.0]
        call = Call()
        bridge = LiveBridge(call, lambda:now[0])
        try:
            bridge.set_gift_rules([GiftRule(gift_id='2001',min_count=3,instruction='向{昵称}比心，收到{数量}个{礼物名称}')])
            bridge.handle_payload(packet(2,0,'a'))
            now[0] += 3
            await bridge.dispatch_once()
            assert not call.sent
            bridge.handle_payload(packet(3,1,'b'))
            await bridge.dispatch_once()
            assert len(call.sent) == 1
            assert '请先说“谢谢观众送来的3个玫瑰”' in call.sent[0]
            assert '然后执行以下指令：向观众比心，收到3个玫瑰' in call.sent[0]
            bridge.handle_payload(packet(5,1,'c'))
            now[0] += 4
            await bridge.dispatch_once()
            assert len(call.sent) == 1
            assert bridge.archive.all()[1]['delivery'] == 'accepted'
        finally:
            bridge.archive.close()
    asyncio.run(run())


def test_rule_edit_cancels_pending_without_replay_and_thanks_optional():
    """保存变更会撤销队列；同组不可利用编辑再次触发。"""
    bridge = LiveBridge(None)
    try:
        bridge.set_gift_rules([GiftRule(gift_id='2001',instruction='比心',thanks=False)])
        bridge.handle_payload(packet(1,1,'a'))
        assert bridge.queue[0][2]['instruction'] == '比心'
        bridge.set_gift_rules([GiftRule(gift_id='2001',instruction='挥手')])
        assert not bridge.queue and bridge.archive.all()[0]['delivery'] == 'dropped'
        bridge.handle_payload(packet(2,1,'b'))
        assert not bridge.queue
        bridge.handle_payload(packet(1,1,'c',group='new'))
        assert len(bridge.queue) == 1
        bridge.set_gift_rules([])
        assert not bridge.queue
    finally:
        bridge.archive.close()


def test_independent_automation_and_gift_queue():
    """关闭回复仅取消评论，不影响礼物、欢迎或点赞。"""
    bridge = LiveBridge(None)
    try:
        assert bridge.automation == {'enter':False,'like':False,'comment':True}
        bridge.set_automation({'enter':True,'like':True})
        for kind in ['enter','like','comment','gift']:
            bridge.receive(LiveEvent(event_type=kind,nickname='用户',gift_count=1))
        bridge.set_automation({'comment':False})
        assert {item[1].event_type for item in bridge.queue} == {'enter','like','gift'}
        bridge.set_automation({'enter':False})
        assert {item[1].event_type for item in bridge.queue} == {'like','gift'}
        bridge.pause_for_policy()
        assert not bridge.queue
    finally:
        bridge.archive.close()


def test_rules_validation_and_session_isolation():
    """规则接口拒绝跨站、重复 ID、空白指令且默认开启答谢。"""
    headers = {'X-Studio-Request':'1'}
    with TestClient(app) as first, TestClient(app) as second:
        first.get('/api/vidu/status'); second.get('/api/vidu/status')
        body = {'rules':[{'gift_id':'2001','instruction':'比心'}]}
        result = first.post('/api/gifts/rules',headers=headers,json=body)
        assert result.status_code == 200 and result.json()['rules'][0]['thanks'] is True
        assert second.get('/api/gifts/rules',headers=headers).json()['rules'] == []
        assert first.post('/api/gifts/rules',headers={**headers,'Origin':'https://other.example'},json=body).status_code == 403
        body['rules'] *= 2
        assert first.post('/api/gifts/rules',headers=headers,json=body).status_code == 422
        assert first.post('/api/session/automation',headers=headers,json={'enter':True,'like':False,'comment':False}).json()['automation']['enter'] is True
    with pytest.raises(ValidationError):
        GiftRule(gift_id='1',instruction='  ')


def test_image_allowlist_and_no_untrusted_url():
    """拒绝脚本、HTTP 和伪装域名，不代理任意图片 URL。"""
    assert safe_gift_image({'url_list':['https://p3-webcast.douyinpic.com/gift.png']})
    for url in ['javascript:alert(1)','http://p3.douyinpic.com/x','https://douyinpic.com.evil.test/x']:
        assert safe_gift_image(url) is None
