"""定义直播事件与事件优先级。"""

from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EventPriority(IntEnum):
    """定义事件进入数字人队列时的处理优先级。"""

    ENTER = 10
    LIKE = 20
    COMMENT = 50
    KEYWORD = 70
    GIFT = 100


class LiveEvent(BaseModel):
    """表示从直播平台标准化后的统一事件。"""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    platform: Literal["douyin"] = "douyin"
    event_type: Literal["comment", "gift", "like", "enter", "follow"]
    user_id: str = ""
    nickname: str = "匿名观众"
    content: str = ""
    gift_name: str | None = None
    gift_count: int = 0
    room_id: str = ''  # 礼物来源房间。
    gift_id: str = ''  # 不用名称作为礼物身份。
    diamond_count: int | None = None  # 单价未知时保留空值。
    recipient_id: str = ''
    recipient_name: str = ''
    group_id: str = ''
    gift_total: int | None = None  # 连击累计量，与本次增量分开。
    settlement: str = ''  # ended / timeout / late_delta / single。
    quantity_certain: bool = True
    metadata_source: str = ''
    price_source: str = ''
    source_method: str = ''
    source_message_id: str = ''
    quantity_fields: dict = Field(default_factory=dict)
    like_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def priority(self) -> EventPriority:
        """根据事件类型返回调度优先级。"""
        mapping = {"gift": EventPriority.GIFT, "comment": EventPriority.COMMENT, "follow": EventPriority.COMMENT, "like": EventPriority.LIKE, "enter": EventPriority.ENTER}
        return mapping[self.event_type]

    def to_prompt(self) -> str:
        """将事件转为发送给数字人的自然语言提示。"""
        if self.event_type == "gift":
            recipient = f'给“{self.recipient_name or self.recipient_id}”' if self.recipient_id or self.recipient_name else ''
            return f"观众“{self.nickname}”{recipient}送出了 {self.gift_count} 个{self.gift_name or ('未知礼物（ID：'+self.gift_id+'）')}，请简短感谢这位观众，不要声称礼物赠送给你。"
        if self.event_type == "like":
            return f"请念出用户名，感谢“{self.nickname}”为直播点赞。"
        if self.event_type == "enter":
            return f"请念出用户名，欢迎“{self.nickname}”进入直播间。"
        if self.event_type == "follow":
            return f"观众“{self.nickname}”关注了直播间，请感谢关注。"
        return f"观众“{self.nickname}”说：{self.content}"
