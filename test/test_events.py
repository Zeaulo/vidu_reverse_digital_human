"""事件模型和过滤规则测试。"""

from app.config.settings import EventSettings
from app.domain.events import LiveEvent
from app.services.event_filter import EventFilter


def test_comment_is_converted_to_prompt():
    """验证普通弹幕能转换为数字人提示词。"""
    event = LiveEvent(event_type="comment", nickname="小明", content="你好")
    assert event.to_prompt() == "观众“小明”说：你好"


def test_sensitive_comment_is_rejected():
    """验证敏感词弹幕不会进入队列。"""
    settings = EventSettings(sensitive_words=["禁止词"])
    event_filter = EventFilter(settings)
    event = LiveEvent(event_type="comment", content="这里有禁止词")
    assert event_filter.accept(event) is False
