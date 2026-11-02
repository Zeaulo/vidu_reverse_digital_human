"""礼物观察模型：保留上游证据，数量不明确时不猜测。"""
from dataclasses import dataclass, field


@dataclass
class GiftObservation:
    """单条上游礼物消息，与聚合后的播报事件分离。"""
    room_id: str = ''  # 房间隔离键。
    method: str = ''  # 原始消息类型。
    message_id: str = ''  # 优先使用内层消息标识。
    user_id: str = ''  # 缺失时不拿昵称冒充稳定身份。
    nickname: str = ''
    recipient_id: str = ''
    recipient_name: str = ''
    gift_id: str = ''
    name: str | None = None
    diamond_count: int | None = None  # None 表示未知，零价仍有效。
    image: str | None = None
    group_id: str = ''
    combo: bool = False
    repeat_end: bool = False
    cumulative: int | None = None  # 已解释的累计量，未知时不播报数量。
    quantities: dict = field(default_factory=dict)  # 原始数量字段。
    issues: list[str] = field(default_factory=list)  # 数量或身份缺失原因。
    metadata_source: str = 'event'
    price_source: str = 'unknown'
