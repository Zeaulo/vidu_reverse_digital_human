"""普通、包装及轻量礼物的独立解析，不借用名称推断 ID。"""
from app.domain.gifts import GiftObservation

GIFT_METHODS = {'WebcastGiftMessage', 'WebcastBindingGiftMessage', 'WebcastLightGiftMessage'}


def value(data, camel, snake=None):
    """兼容字段拼写，保留零值和 False。"""
    return data.get(camel, data.get(snake))


def object_field(raw):
    """畸形嵌套字段作为无效包，不让单包异常终止采集任务。"""
    if raw is None:
        return {}
    if not isinstance(raw,dict):
        raise ValueError('礼物嵌套字段不是对象')
    return raw


def number(raw):
    """只接受非负整数，不把布尔或小数误认为数量。"""
    if isinstance(raw, bool) or raw is None or not str(raw).isdigit():
        return None
    return int(raw)


def identity(raw):
    """零 ID 视为缺失，其他数字标识以字符串保存。"""
    return str(raw) if raw not in (None, '', 0, '0') else ''


def parse_gift(payload, room_id=''):
    """先保留字段，再保守解释数量；轻量包不推测赠送者。"""
    method = payload.get('method')
    if method not in GIFT_METHODS:
        return None
    message = payload.get('msg') if method == 'WebcastBindingGiftMessage' else payload
    if not isinstance(message, dict):
        raise ValueError('包装礼物缺少 msg')
    gift = object_field(message.get('gift') or value(message, 'giftStruct', 'gift_struct'))
    info = object_field(value(message, 'giftInfo', 'gift_info'))
    user = object_field(message.get('user'))
    recipient = object_field(value(message, 'toUser', 'to_user'))
    common = object_field(message.get('common') or payload.get('common'))
    amounts = {camel:number(value(message, camel, snake)) for camel,snake in (
        ('repeatCount','repeat_count'),('comboCount','combo_count'),
        ('groupCount','group_count'),('totalCount','total_count'),('count','count'))}
    combo = gift.get('combo') is True or number(gift.get('type')) == 1
    issues = []  # 缺失证据单独展示，不默默补一。
    cumulative = amounts['repeatCount']
    if not cumulative:
        cumulative = amounts['count'] if not combo else None
    if not cumulative:
        cumulative = None
        issues.append('quantity_unknown')
    # 多件成组和重复倍数的关系未验证时，不自动广播可能错误的数量。
    if amounts['groupCount'] and amounts['groupCount'] > 1:
        cumulative = None; issues.append('group_quantity_unverified')
    if method == 'WebcastLightGiftMessage':
        cumulative = None; issues.append('light_quantity_unverified')
    image = object_field(gift.get('image') or gift.get('icon') or value(info,'giftIcon','gift_icon'))
    urls = value(image,'urlList','url_list') or []
    price = number(value(gift,'diamondCount','diamond_count'))
    if price is None:
        price = number(value(info,'diamondCount','diamond_count'))
    result = GiftObservation(room_id=room_id, method=method,
        message_id=identity(value(common,'msgId','msg_id')),
        user_id=identity(user.get('id')), nickname=str(user.get('nickname') or ''),
        recipient_id=identity(recipient.get('id') or value(message,'toUserId','to_user_id')),
        recipient_name=str(recipient.get('nickname') or ''),
        gift_id=identity(value(message,'giftId','gift_id') or gift.get('id') or value(info,'giftId','gift_id')),
        name=gift.get('name') or None, diamond_count=price,
        image=urls[0] if urls else None, group_id=identity(value(message,'groupId','group_id')),
        combo=combo, repeat_end=number(value(message,'repeatEnd','repeat_end')) == 1,
        cumulative=cumulative, quantities=amounts, issues=issues,
        price_source='event' if price is not None else 'unknown')
    if not result.user_id:
        result.issues.append('sender_missing')
    if not result.gift_id:
        result.issues.append('gift_id_missing')
    if combo and not result.group_id:
        result.issues.append('group_id_missing')
    return result
