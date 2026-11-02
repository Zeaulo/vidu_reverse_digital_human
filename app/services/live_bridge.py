"""会话隔离的采集、有限队列及 Vidu 回执调度。"""
import asyncio
import time
from collections import Counter, deque
from app.adapters.douyin import DouyinAdapter
from app.adapters.vidu_api import ViduModerationError
from app.config.settings import load_settings
from app.services.event_filter import EventFilter
from app.storage.event_archive import EventArchive


class LiveBridge:
    """每位 Studio 用户只向自己的通话发送弹幕。"""
    def __init__(self, call, clock=time.monotonic):
        self.call = call  # 专属通话控制器。
        self.clock = clock  # 可注入的单调时钟。
        self.settings = load_settings()
        self.filter = EventFilter(self.settings.events)
        self.tasks = []  # 采集和消费后台任务。
        self.queue = []  # 入队时刻、事件和展示记录。
        self.history = {kind: deque(maxlen=80) for kind in ('comment', 'like', 'enter', 'gift', 'follow')}  # 各类独立保留，避免点赞挤掉评论。
        self.archive = EventArchive()  # 完整记录存入本会话临时归档，不受展示上限影响。
        self.counts = Counter()  # 运行计数器。
        self.room_id = ''
        self.state = 'idle'
        self.detail = ''
        self.enabled = True  # 默认自动调度，媒体未就绪时等待。
        self.warmup = False  # 暖场必须由用户主动开启。
        self.policy_paused = False  # 审核结束后的恢复期间不收集待发送指令。
        self.last_sent = float('-inf')

    def snapshot(self):
        """返回脱敏状态及有限事件记录。"""
        return {'room_id':self.room_id, 'state':self.state, 'detail':self.detail,
                'enabled':self.enabled, 'warmup':self.warmup, 'policy_paused':self.policy_paused, 'counts':dict(self.counts), 'queue_size':len(self.queue),
                'events':sorted((record for records in self.history.values() for record in records), key=lambda record: record['timestamp'])}

    async def start(self, room_id):
        """切房时先取消旧任务并清空旧房间事件。"""
        await self.stop()
        self.room_id = room_id
        self.state = 'connecting'; self.detail = ''
        for records in self.history.values():  # 切房清理各类历史。
            records.clear()
        self.archive.clear()
        self.counts.clear()
        self.filter = EventFilter(self.settings.events)
        self.tasks = [asyncio.create_task(self.collect()), asyncio.create_task(self.consume())]

    async def stop(self):
        """取消采集和消费，状态不明的消息不会重放。"""
        for task in self.tasks:  # 同时请求取消，之后统一等待退出。
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        for _, _, record in self.queue:  # 停止采集时，尚未发送的事件不再排队。
            record['delivery'] = 'dropped'
            self.archive.update(record['_archive_sequence'], record)
            self.counts['dropped'] += 1
        self.queue.clear()
        self.state = 'stopped'

    def receive(self, event):
        """统计所有事件，仅将通过规则的事件放入优先队列。"""
        self.counts['received'] += 1
        self.counts[event.event_type] += 1
        if event.event_type == 'like':
            self.counts['likes'] += event.like_count
        record = {**event.model_dump(mode='json'), 'delivery':'observed'}
        record['_archive_sequence'] = self.archive.add(record)  # 内部序号用于同步后续回执。
        self.history[event.event_type].append(record)
        if not self.enabled or self.policy_paused or not self.filter.accept(event, warmup=self.warmup):
            return
        record['delivery'] = 'queued'
        self.archive.update(record['_archive_sequence'], record)
        self.queue.append((self.clock(), event, record))
        self.counts['queued'] += 1
        if len(self.queue) > self.settings.events.max_queue_size:
            victim = min(self.queue, key=lambda item:(item[1].priority,item[0]))
            self.queue.remove(victim); victim[2]['delivery'] = 'dropped'
            self.archive.update(victim[2]['_archive_sequence'], victim[2])
            self.counts['dropped'] += 1

    def pause_for_policy(self):
        """暂停自动发送并丢弃未发送队列，采集记录继续保留。"""
        self.policy_paused = True
        for _, _, record in self.queue:
            record['delivery'] = 'dropped'
            self.archive.update(record['_archive_sequence'], record)
            self.counts['dropped'] += 1
        self.queue.clear()

    def resume_after_policy(self):
        """新通话连通或用户手动开始时恢复新事件调度。"""
        self.policy_paused = False

    def set_warmup(self, enabled):
        """关闭暖场时移除尚未发送的欢迎、点赞及礼物事件。"""
        self.warmup = enabled
        if not enabled:
            for item in self.queue[:]:
                if item[1].event_type in ('enter', 'like', 'gift'):
                    self.queue.remove(item)
                    item[2]['delivery'] = 'dropped'
                    self.archive.update(item[2]['_archive_sequence'], item[2])
                    self.counts['dropped'] += 1

    async def collect(self):
        """只将上游 ROOM_ONLINE 认定为房间连接成功。"""
        try:
            adapter = DouyinAdapter(self.settings.douyin.ws_url, self.room_id)
            async for payload in adapter.frames():
                if payload.get('type') == 'system':
                    code = payload.get('code', '')
                    self.state = 'online' if code == 'ROOM_ONLINE' else code.lower()
                    self.detail = str(payload.get('message', ''))[:200]
                    if code in ('ROOM_STATUS_UNKNOWN', 'ROOM_NOT_FOUND'):
                        break  # 未知状态或验证要求不循环重试。
                    continue
                try:
                    event = adapter.normalize(payload)
                    if event:
                        if event.event_type == 'like' and payload.get('total'):
                            self.counts['likes_total'] = int(payload['total'])
                        self.receive(event)
                except (ValueError, TypeError):
                    self.counts['invalid'] += 1
            if self.state in ('online', 'connecting'):
                self.state = 'disconnected'
        except asyncio.CancelledError:
            raise
        except Exception:
            self.state = 'disconnected'; self.detail = '采集连接失败，请检查本机 douyinLive 服务'

    async def dispatch_once(self):
        """过期清理、礼物优先、间隔发送；回执不明绝不重试。"""
        now = self.clock()
        for item in self.queue[:]:
            if now - item[0] > 30:
                self.queue.remove(item); item[2]['delivery'] = 'expired'
                self.archive.update(item[2]['_archive_sequence'], item[2])
                self.counts['dropped'] += 1
        if not self.enabled or self.policy_paused or not self.queue or self.call.status != 'connected':
            return
        if now - self.last_sent < self.settings.events.min_interval_ms / 1000:
            return
        item = max(self.queue, key=lambda value:(value[1].priority,-value[0]))
        self.queue.remove(item); self.last_sent = now
        self.counts['sent'] += 1; item[2]['delivery'] = 'sending'
        self.archive.update(item[2]['_archive_sequence'], item[2])
        try:
            result = await self.call.send(item[1].to_prompt()[:500])
            if result.get('accepted') is not True:
                raise ValueError('未收到接受回执')
            item[2]['delivery'] = 'accepted'
            item[2]['client_msg_id'] = result.get('client_msg_id')
            self.counts['accepted'] += 1
        except asyncio.CancelledError:
            item[2]['delivery'] = 'unknown'
            self.archive.update(item[2]['_archive_sequence'], item[2])
            raise
        except ViduModerationError:
            item[2]['delivery'] = 'moderation_rejected'  # 明确的审核拒绝不终止通话、不重发。
            self.counts['moderation_rejected'] += 1
        except Exception:
            item[2]['delivery'] = 'unknown'; self.counts['failed'] += 1
        finally:
            self.archive.update(item[2]['_archive_sequence'], item[2])

    async def consume(self):
        """单消费者等待当前回执，防止多个发送请求叠加。"""
        while True:
            await self.dispatch_once()
            await asyncio.sleep(0.5)
