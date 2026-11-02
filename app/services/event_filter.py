"""实现直播事件过滤、敏感词检查和简单去重。"""

import time

from app.domain.events import LiveEvent


class EventFilter:
    """根据配置决定某条事件是否进入数字人队列。"""

    def __init__(self, settings):
        """保存事件配置和短期去重缓存。"""
        self.settings = settings
        self._recent: dict[str, float] = {}

    def accept(self, event: LiveEvent, warmup=False, automation=None) -> bool:
        """检查开关、长度、敏感词和重复内容。"""
        switches = {"comment": self.settings.comments, "gift": self.settings.gifts, "like": self.settings.likes, "enter": self.settings.enters, "follow": self.settings.follows}
        if automation is not None:  # 三个互动开关独立，礼物使用专属配置。
            switches.update(automation)
        else:  # 兼容旧调用方。
            for kind in ('gift', 'like', 'enter'):
                switches[kind] = warmup
        if not switches[event.event_type] or len(event.content) > self.settings.max_message_length:
            return False
        lowered = event.content.casefold()
        if any(word.casefold() in lowered for word in self.settings.sensitive_words):
            return False
        dedupe_key = ('gift:'+event.room_id+':'+event.event_id) if event.event_type == 'gift' else f"{event.event_type}:{event.user_id or event.nickname}:{event.content}"
        now = time.monotonic()
        self._recent = {key:stamp for key,stamp in self._recent.items() if now-stamp < 8}
        if dedupe_key in self._recent:
            return False
        self._recent[dedupe_key] = now
        return True
