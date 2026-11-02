"""有界礼物状态机：累计量取递增差额，迟到终包不重复结算。"""
import time
from collections import Counter, OrderedDict, deque
from dataclasses import asdict
from uuid import uuid4
from app.domain.events import LiveEvent


class GiftAggregator:
    """每个 Studio 会话独立持有礼物去重状态，不保存完整原始用户数据。"""
    def __init__(self, clock=time.monotonic, timeout=2.0, retention=600, capacity=5000):
        self.clock = clock  # 可替换时钟，超时测试不需要真实等待。
        self.timeout = timeout  # 静默暂结等待秒数。
        self.retention = retention  # 已结算组与消息 ID 的保留窗口。
        self.capacity = capacity  # 限制长期直播内存。
        self.seen = OrderedDict()  # 消息身份 -> 首次接收时刻。
        self.groups = OrderedDict()  # 复合身份 -> 聚合状态。
        self.records = deque(maxlen=200)  # 独立于普通弹幕的可见礼物记录。
        self.counts = Counter()  # 原始包、重复包、组数与结算增量。

    def _prune(self):
        """清理过期状态；窗口外不承诺跨重启或无限期去重。"""
        now = self.clock()
        for key,stamp in list(self.seen.items()):
            if now-stamp > self.retention:
                del self.seen[key]
        for key,state in list(self.groups.items()):
            if now-state['last'] > self.retention:
                del self.groups[key]
        while len(self.seen) > self.capacity:
            self.seen.popitem(last=False)

    def feed(self, gift):
        """接收一包并返回零或一个结算事件；无证据时只记录。"""
        self._prune()
        self.counts['raw_messages'] += 1
        message_key = (gift.room_id,gift.message_id) if gift.message_id else None
        if message_key and message_key in self.seen:
            self.counts['duplicates'] += 1
            return []
        if message_key:
            self.seen[message_key] = self.clock()
        # 同一个 groupId 下仍隔离赠送者、接收者和礼物，包装消息不单独分组。
        grouped = bool(gift.group_id and gift.user_id and gift.gift_id)
        key = (gift.room_id,gift.user_id,gift.recipient_id,gift.gift_id,gift.group_id) if grouped else ('message',gift.room_id,gift.message_id or uuid4().hex)
        blocked = bool(gift.issues or not gift.message_id and not grouped)
        if gift.combo and not grouped:
            blocked = True
        state = self.groups.get(key)
        if state is None:
            if len(self.groups) >= self.capacity:
                # 不驱逐仍可能迟到的活跃组来冒险重复计数，新组明确标记容量不足。
                self.counts['capacity_rejected'] += 1
                self.records.append({**asdict(gift),'status':'capacity_rejected','quantity':None})
                return []
            record = {**asdict(gift),'status':'unverified' if blocked else 'collecting',
                      'quantity':gift.cumulative, 'settled_quantity':0}
            self.records.append(record)
            state = {'gift':gift,'maximum':0,'settled':0,'last':self.clock(),
                     'blocked':blocked,'record':record,'identity':uuid4().hex}
            self.groups[key] = state
            self.counts['groups'] += 1
        # 原始状态不明确时整组保持保守，避免后续终包掩盖先前数量冲突。
        state['blocked'] = state['blocked'] or blocked
        state['last'] = self.clock()
        if gift.cumulative is not None and gift.cumulative >= state['maximum']:
            state['maximum'] = gift.cumulative
            state['gift'] = gift
        state['record'].update({'quantity':state['maximum'] or None,'last_message_id':gift.message_id,
                                'repeat_end':gift.repeat_end,
                                'issues':list(dict.fromkeys(state['record']['issues']+gift.issues))})
        if state['blocked']:
            state['record']['status'] = 'unverified'
            self.counts['unverified_messages'] += 1
            return []
        if gift.repeat_end or not gift.combo:
            event = self._settle(state,'ended' if gift.combo else 'single')
            return [event] if event else []
        return []

    def _settle(self, state, reason):
        """只结算此前未处理的正增量；结算不等于已经播报。"""
        delta = state['maximum']-state['settled']
        if delta <= 0:
            if reason == 'ended':
                state['record']['status'] = 'ended'
            return None
        gift = state['gift']
        previous = state['settled']
        state['settled'] = state['maximum']
        state['record'].update(status=reason,settled_quantity=state['settled'],
                              diamond_count=gift.diamond_count,price_source=gift.price_source,
                              name=gift.name,metadata_source=gift.metadata_source)
        self.counts['quantity'] += delta
        self.counts['settlements'] += 1
        # 历史目录价格只用于展示，不加入已知价值合计。
        if gift.diamond_count is not None and gift.price_source == 'event':
            self.counts['known_diamonds'] += delta*gift.diamond_count
        else:
            self.counts['unpriced_quantity'] += delta
        return LiveEvent(event_type='gift',event_id=state['identity']+':'+str(state['settled']),
            room_id=gift.room_id,user_id=gift.user_id,nickname=gift.nickname or '匿名观众',
            recipient_id=gift.recipient_id,recipient_name=gift.recipient_name,
            gift_id=gift.gift_id,gift_name=gift.name,gift_count=delta,gift_total=state['maximum'],
            diamond_count=gift.diamond_count,group_id=gift.group_id,
            settlement='late_delta' if previous else reason,metadata_source=gift.metadata_source,
            price_source=gift.price_source,source_method=gift.method,source_message_id=gift.message_id,
            quantity_fields=gift.quantities)

    def flush_due(self):
        """静默超时暂结；结算量留存以处理迟到增长或重复终包。"""
        events = []
        for state in self.groups.values():
            if not state['blocked'] and self.clock()-state['last'] >= self.timeout:
                event = self._settle(state,'timeout')
                if event:
                    events.append(event)
        self._prune()
        return events

    def cancel_pending(self):
        """停止时标记未结算组，不把旧房间礼物延后发送。"""
        for state in self.groups.values():
            if state['maximum'] > state['settled']:
                state['record']['status'] = 'stopped_unsettled'
                state['blocked'] = True

    def snapshot(self):
        """返回有限历史与独立统计。"""
        return {'counts':dict(self.counts),'records':list(self.records),
                'dedupe_retention_seconds':self.retention}
