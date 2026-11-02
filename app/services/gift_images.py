"""礼物图片仅接受抖音使用的公开 HTTPS CDN，不代理任意地址。"""
from urllib.parse import urlparse


def safe_gift_image(value):
    """提取合法图片地址；空值和非可信域名使用界面占位图。"""
    if isinstance(value, dict):
        urls = value.get('url_list') or value.get('urlList') or []
        value = urls[0] if urls else None
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    allowed = ('douyinpic.com', 'byteimg.com', 'douyincdn.com', 'pstatp.com', 'bytedance.com')
    if parsed.scheme == 'https' and not parsed.username and not parsed.password and any(
            parsed.hostname == host or (parsed.hostname or '').endswith('.'+host) for host in allowed):
        return value
    return None
