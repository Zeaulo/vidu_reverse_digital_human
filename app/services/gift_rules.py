"""礼物指令规则与同连击去重；规则在当前 Studio 会话内隔离。"""
import time
from pydantic import BaseModel, Field, model_validator, field_validator


class GiftRule(BaseModel):
    """一个礼物 ID 对应一条可独立启停的指令。"""
    gift_id: str = Field(pattern=r'^[0-9]{1,30}$')  # 按 ID 精确匹配。
    enabled: bool = True  # 是否启用该规则。
    min_count: int = Field(default=1, ge=1, le=1000000)  # 连击累计触发门槛。
    instruction: str = Field(min_length=1, max_length=250)  # 留出答谢与变量空间。
    thanks: bool = True  # 默认先感谢赠送者，再执行指令。

    @field_validator('instruction')
    @classmethod
    def validate_instruction(cls, text):
        """拒绝空白指令；未知占位符按用户原文保留。"""
        if not text.strip():
            raise ValueError('自定义指令不能为空')
        return text.strip()


class GiftRulesBody(BaseModel):
    """一次保存完整规则集，避免半更新。"""
    rules: list[GiftRule] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_ids(self):
        """拒绝重复 ID，避免执行次序产生歧义。"""
        if len({rule.gift_id for rule in self.rules}) != len(self.rules):
            raise ValueError('同一礼物只能配置一条规则')
        return self


class GiftRules:
    """入队前冻结指令，回执不明、规则编辑和迟到终包均不重复触发。"""
    def __init__(self, clock=time.monotonic):
        self.clock = clock  # 与聚合器使用相同单调时钟。
        self.rules = {}  # 礼物 ID 到已验证规则。
        self.triggered = {}  # 连击身份到最近接收时间，窗口与聚合器一致。

    def replace(self, rules):
        """替换配置但保留已触发身份，编辑不能重放同组。"""
        self.rules = {rule.gift_id: rule for rule in rules}

    def plan(self, event):
        """返回指令与匹配标识；命中但未达门槛时不发送默认感谢。"""
        rule = self.rules.get(event.gift_id)
        if not rule or not rule.enabled:
            return event.to_prompt(), None
        # 聚合器的随机身份在超时暂结与迟到增量之间保持不变。
        identity = (event.room_id, event.event_id.split(':')[0], rule.gift_id)
        now = self.clock()
        self.triggered = {key: stamp for key, stamp in self.triggered.items() if now-stamp <= 600}
        if identity in self.triggered:
            self.triggered[identity] = now
            return None, rule.gift_id
        count = event.gift_total if event.gift_total is not None else event.gift_count
        if not event.quantity_certain or count < rule.min_count or len(self.triggered) >= 5000:
            return None, rule.gift_id
        self.triggered[identity] = now  # 先占用触发身份，丢弃或回执未知均不重试。
        nickname = event.nickname[:40]  # 限制变量展开，确保完整指令不被中途截断。
        name = (event.gift_name or ('礼物 ID ' + event.gift_id))[:40]
        text = rule.instruction
        for token, value in {'{昵称}': nickname, '{礼物名称}': name, '{数量}': str(count)}.items():
            text = text.replace(token, value)
        prefix = f'请先说“谢谢{nickname}送来的{count}个{name}”，然后：' if rule.thanks else ''
        if len(prefix + text) > 500:
            return None, rule.gift_id  # 不发送被截断而改变语义的指令。
        return prefix + text, rule.gift_id
