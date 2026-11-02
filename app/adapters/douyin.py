"""douyinLive v2 协议：系统状态和业务事件分离。"""
import json
from app.domain.events import LiveEvent


class DouyinAdapter:
    """连接本机采集器，只解析明确支持的业务消息。"""
    def __init__(self, ws_url, room_id):
        self.ws_url = ws_url  # 本地配置中的采集地址。
        self.room_id = room_id  # 已校验的数字房间号。

    async def frames(self):
        """持续返回 JSON，连接终止后由调用方显示真实状态。"""
        import websockets
        async with websockets.connect(f'{self.ws_url.rstrip("/")}/ws/{self.room_id}', ping_interval=20) as socket:
            async for message in socket:  # 单连接消息消费循环。
                if message == 'pong':
                    continue
                try:
                    payload = json.loads(message)
                    if isinstance(payload, dict):
                        yield payload
                except (ValueError, TypeError):
                    continue

    @staticmethod
    def normalize(payload):
        """识别评论、礼物、点赞和进入；连击礼物只取最终包。"""
        method = payload.get('method')
        kinds = {'WebcastChatMessage':'comment', 'WebcastGiftMessage':'gift',
                 'WebcastLikeMessage':'like', 'WebcastMemberMessage':'enter'}
        if method not in kinds:
            return None
        user = payload.get('user') or {}  # 嵌套观众信息。
        gift = payload.get('gift') or {}  # 嵌套礼物信息。
        if method == 'WebcastGiftMessage' and gift.get('type') == 1 and not payload.get('repeatEnd', payload.get('repeat_end')):
            return None
        common = payload.get('common') or {}
        identity = common.get('msgId') or common.get('msg_id')
        return LiveEvent(**({'event_id':str(identity)} if identity else {}),
            event_type=kinds[method], user_id=str(user.get('id', '')),
            nickname=str(user.get('nickname') or '匿名观众'), content=str(payload.get('content') or ''),
            gift_name=gift.get('name'), gift_count=int(payload.get('repeatCount', payload.get('repeat_count', 1)) or 1),
            like_count=int(payload.get('count') or 0))
