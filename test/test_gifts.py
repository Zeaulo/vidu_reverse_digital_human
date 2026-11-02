"""礼物状态机边界回放：消息样本均为合成，不冒充真实赠送。"""
import asyncio
import pytest
from fastapi.testclient import TestClient
from app.adapters.douyin_gifts import parse_gift
from app.services.gift_aggregator import GiftAggregator
from app.services.gift_catalog import GiftCatalog
from app.services.live_bridge import LiveBridge
from app.main import app


def packet(count=1, end=0, msg='m1', group='g1', uid='u1', gift_id='2001', combo=True):
    """生成字段明确的合成普通礼物消息。"""
    return {'method':'WebcastGiftMessage','common':{'msgId':msg},
        'user':{'id':uid,'nickname':'观众'},'toUser':{'id':'host','nickname':'主播'},
        'giftId':gift_id,'gift':{'id':gift_id,'name':'玫瑰','diamondCount':1,'combo':combo,'type':1 if combo else 2},
        'groupId':group,'repeatCount':count,'repeatEnd':end}


def test_combo_end_duplicate_and_out_of_order():
    """1→3→2→3 仅感谢三个，重复终包和包装终包不重复。"""
    agg = GiftAggregator()
    assert not agg.feed(parse_gift(packet(1,msg='a'),'r'))
    assert not agg.feed(parse_gift(packet(3,msg='b'),'r'))
    assert not agg.feed(parse_gift(packet(2,msg='c'),'r'))
    result = agg.feed(parse_gift(packet(3,1,'d'),'r'))
    assert len(result)==1 and result[0].gift_count==3
    assert not agg.feed(parse_gift(packet(3,1,'d'),'r'))
    wrapper={'method':'WebcastBindingGiftMessage','msg':packet(3,1,'d'),'common':{'msgId':'outer'}}
    assert not agg.feed(parse_gift(wrapper,'r'))
    assert agg.counts['quantity']==3 and agg.counts['duplicates']==2


def test_timeout_late_delta_and_same_total_end():
    """超时先结算三，迟到五只增加二；同数量终包不会重放。"""
    now=[100.0]
    agg=GiftAggregator(clock=lambda:now[0])
    agg.feed(parse_gift(packet(3),'r'))
    now[0]+=2
    event=agg.flush_due()[0]
    assert event.gift_count==3 and event.settlement=='timeout'
    assert not agg.feed(parse_gift(packet(3,1,'end'),'r'))
    event=agg.feed(parse_gift(packet(5,1,'late'),'r'))[0]
    assert event.gift_count==2 and event.settlement=='late_delta'
    assert agg.counts['quantity']==5 and agg.counts['known_diamonds']==5


@pytest.mark.parametrize('change',[{'group':'g2'},{'uid':'u2'},{'gift_id':'15012'}])
def test_independent_gifts_not_merged(change):
    """同昵称、同数量、同名不同 ID 或不同组均独立处理。"""
    agg=GiftAggregator()
    first=agg.feed(parse_gift(packet(1,1,'a'),'r'))[0]
    second=agg.feed(parse_gift(packet(1,1,'b',**change),'r'))[0]
    assert first.event_id!=second.event_id and agg.counts['groups']==2


def test_recipient_and_room_isolation():
    """不同房间和接收者不能共享连击。"""
    agg=GiftAggregator()
    first=packet(1,1,'a')
    second=packet(1,1,'b');second['toUser']['id']='other'
    assert agg.feed(parse_gift(first,'r'))
    assert agg.feed(parse_gift(second,'r'))
    assert agg.feed(parse_gift(first,'r2'))
    assert agg.counts['groups']==3


def test_missing_identity_quantity_and_light_are_not_announced():
    """缺组 ID、轻量缺用户、成组数量未知时只记录，不报错数量。"""
    agg=GiftAggregator()
    assert not agg.feed(parse_gift(packet(2,1,group=''),'r'))
    light={'method':'WebcastLightGiftMessage','common':{'msgId':'light'},
           'giftInfo':{'giftId':'2001','diamondCount':1},'repeatCount':2}
    gift=parse_gift(light,'r')
    assert gift.gift_id=='2001' and not gift.user_id and gift.cumulative is None
    assert not agg.feed(gift)
    grouped=packet(3,1,'grouped');grouped['groupCount']=10
    assert not agg.feed(parse_gift(grouped,'r'))
    assert all(row['status']=='unverified' for row in agg.records)


def test_snake_case_and_string_zero_end():
    """字符串 0 不是终包；下划线格式及大整数 ID 均保持准确。"""
    gift=parse_gift({'method':'WebcastGiftMessage','common':{'msg_id':'90071992547409999'},
        'gift_id':'2001','gift':{'name':'玫瑰','type':1,'diamond_count':'0'},
        'user':{'id':'u'},'repeat_count':'3','repeat_end':'0','group_id':'g'},'r')
    assert gift.message_id=='90071992547409999' and gift.diamond_count==0
    assert not gift.repeat_end and gift.cumulative==3


def test_cancel_pending_and_capacity():
    """停止取消未结算组，容量溢出可见，不悄悄驱逐活跃组。"""
    now=[10.0]
    agg=GiftAggregator(clock=lambda:now[0],capacity=1)
    agg.feed(parse_gift(packet(),'r'))
    agg.feed(parse_gift(packet(msg='b',group='g2'),'r'))
    assert agg.counts['capacity_rejected']==1
    agg.cancel_pending();now[0]+=3
    assert not agg.flush_due()
    assert agg.records[0]['status']=='stopped_unsettled'


def test_catalog_nested_pages_same_name_and_fallback(tmp_path):
    """目录失败不清空缓存；同名异 ID 保留，事件值优先于历史。"""
    catalog=GiftCatalog(baseline=tmp_path/'missing.json')
    catalog.import_response('r',{'status_code':0,'data':{'gifts':[],
        'pages':[{'gifts':[{'id':'1','name':'同名','diamond_count':1,'is_displayed_on_panel':True},
                           {'id':'2','name':'同名','diamond_count':999,'is_displayed_on_panel':True}]}]}})
    assert catalog.query('r','同名')['total']==2
    with pytest.raises(ValueError):
        catalog.import_response('r',{'status_code':0,'data':{'gifts':[]}})
    assert catalog.query('r')['total']==2
    event=packet(1,1,gift_id='1');event['gift']['name']='实时名称';event['gift']['diamondCount']=5
    gift=catalog.enrich(parse_gift(event,'r'))
    assert gift.name=='实时名称' and gift.diamond_count==5 and gift.price_source=='event'
    event=packet(1,1,'new',gift_id='2');event['gift'].pop('name');event['gift'].pop('diamondCount')
    gift=catalog.enrich(parse_gift(event,'r'))
    assert gift.name=='同名' and gift.price_source=='catalog_reference'
    assert catalog.query('other')['total']==0


def test_bridge_gift_dispatch_and_expiry():
    """真实调度入口使用聚合结果；停止通话不损失接收统计。"""
    async def run():
        class Call:
            status='connected'
            def __init__(self):
                self.sent=[]
            async def send(self,text):
                self.sent.append(text);return {'accepted':True,'client_msg_id':'ack'}
        now=[100.0];call=Call();bridge=LiveBridge(call,clock=lambda:now[0]);bridge.room_id='r'
        bridge.handle_payload(packet(1,1,'a',group='one'))
        bridge.handle_payload(packet(1,1,'b',group='two'))
        assert len(bridge.queue)==2  # 八秒内容去重不能吞掉独立礼物。
        await bridge.dispatch_once()
        assert bridge.counts['accepted']==1 and '玫瑰' in call.sent[0]
        now[0]+=31;await bridge.dispatch_once()
        assert bridge.counts['dropped']==1 and bridge.gifts.counts['quantity']==2
        assert bridge.history['gift'][-1]['delivery']=='expired'
    asyncio.run(run())


def test_catalog_api_session_and_origin():
    """礼物 API 继承账号隔离和同源限制。"""
    with TestClient(app) as client:
        assert client.get('/api/gifts/catalog').status_code==403
        client.get('/api/vidu/status')
        headers={'X-Studio-Request':'1'}
        data=client.get('/api/gifts/catalog?search=小心心',headers=headers).json()
        assert {row['id'] for row in data['items']} >= {'463'}
        assert '15012' not in {row['id'] for row in data['items']}
        all_data=client.get('/api/gifts/catalog?search=小心心&include_hidden=true',headers=headers).json()
        assert {row['id'] for row in all_data['items']} >= {'463','15012'}
        assert client.post('/api/gifts/refresh',headers={**headers,'Origin':'https://example.com'}).status_code==403
        assert client.post('/api/gifts/refresh',headers=headers).status_code==502


def test_catalog_hides_system_ids_by_default_and_can_include_them(tmp_path):
    """目录默认只展示用户面板礼物，显式参数才展示系统隐藏 ID。"""
    catalog = GiftCatalog(baseline=tmp_path/'missing.json')
    catalog.baseline = {
        '463': {'id':'463','name':'小心心','is_displayed_on_panel':True},
        '15012': {'id':'15012','name':'小心心','is_displayed_on_panel':False},
    }
    default = catalog.query('', '小心心')
    hidden = catalog.query('', '小心心', include_hidden=True)
    assert {row['id'] for row in default['items']} == {'463'}
    assert {row['id'] for row in hidden['items']} == {'463','15012'}
    assert default['visible_count'] == 1 and default['hidden_count'] == 1
    assert hidden['include_hidden'] is True


def test_import_response_preserves_douyin_visibility_flag(tmp_path):
    """目录响应中的 is_displayed_on_panel 不被名称和图片覆盖。"""
    catalog = GiftCatalog(baseline=tmp_path/'missing.json')
    catalog.import_response('r', {'status_code':0,'data':{'gifts':[
        {'id':'463','name':'小心心','is_displayed_on_panel':True},
        {'id':'15012','name':'小心心','is_displayed_on_panel':False},
    ]}})
    assert catalog.entries('r')['463']['is_displayed_on_panel'] is True
    assert catalog.entries('r')['15012']['is_displayed_on_panel'] is False


def test_missing_visibility_is_unknown_and_does_not_erase_snapshot(tmp_path):
    """缺少布尔字段时不猜测；同 ID 可沿用有来源的历史证据。"""
    catalog = GiftCatalog(baseline=tmp_path/'missing.json')
    catalog.baseline = {'463': {'id':'463','name':'小心心','is_displayed_on_panel':True}}
    catalog.import_response('r', {'status_code':0,'data':{'gifts':[
        {'id':'463','name':'小心心'}, {'id':'99999','name':'新礼物'},
    ]}})
    result = catalog.query('r', include_hidden=True)
    rows = {row['id']:row for row in result['items']}
    assert rows['463']['is_displayed_on_panel'] is True
    assert rows['463']['visibility_source'] == 'historical_snapshot'
    assert rows['99999']['is_displayed_on_panel'] is None
    assert result['unknown_count'] == 1
    assert {row['id'] for row in catalog.query('r')['items']} == {'463'}


def test_catalog_ttl_and_reference_value_excluded(tmp_path):
    """过期房间目录不再补缺，历史价格不计入已知金额。"""
    now=[100.0];catalog=GiftCatalog(baseline=tmp_path/'none',clock=lambda:now[0])
    catalog.import_response('r',{'status_code':0,'data':{'gifts':[{'id':'2001','name':'目录玫瑰','diamond_count':9}]}})
    payload=packet(2,1);payload['gift'].pop('name');payload['gift'].pop('diamondCount')
    gift=catalog.enrich(parse_gift(payload,'r'));agg=GiftAggregator()
    agg.feed(gift)
    assert gift.name=='目录玫瑰' and agg.counts['known_diamonds']==0
    assert agg.counts['unpriced_quantity']==2
    now[0]+=3601
    assert catalog.query('r')['total']==0


def test_same_room_reconnect_dedup_and_switch_cleanup():
    """同房重连保留去重，不同房清理未播报队列和旧组。"""
    async def run():
        class Call:
            status='starting'
        bridge=LiveBridge(Call())
        async def idle():
            await asyncio.Event().wait()
        bridge.collect=idle;bridge.consume=idle  # 生命周期测试不接真实网络。
        try:
            await bridge.start('r')
            bridge.handle_payload(packet(1,1,'a'))
            assert len(bridge.queue)==1
            previous = bridge.gift_deliveries[0]  # 新版重连清空展示，旧记录仍应标记丢弃。
            await bridge.start('r')
            bridge.handle_payload(packet(1,1,'a'))
            assert not bridge.queue and bridge.gifts.counts['duplicates']==1
            assert previous['delivery']=='dropped' and not bridge.gift_deliveries
            await bridge.start('different')
            assert not bridge.gifts.records and not bridge.gift_deliveries
        finally:
            await bridge.stop()
    asyncio.run(run())


def test_gift_unknown_ack_not_replayed():
    """礼物发送超时后，重复终包不会创建第二次发送。"""
    async def run():
        class Call:
            status='connected'
            attempts=0
            async def send(self,text):
                self.attempts+=1
                raise TimeoutError()
        call=Call();bridge=LiveBridge(call);bridge.room_id='r'
        bridge.handle_payload(packet(1,1))
        await bridge.dispatch_once()
        bridge.handle_payload(packet(1,1,msg='different-end-id'))
        await bridge.dispatch_once()
        assert call.attempts==1 and bridge.gift_deliveries[0]['delivery']=='unknown'
    asyncio.run(run())


def test_invalid_nested_payload_rejected():
    """上游畸形礼物嵌套结构转换为可计数的无效包。"""
    payload=packet();payload['gift']='invalid'
    with pytest.raises(ValueError):
        parse_gift(payload,'r')
