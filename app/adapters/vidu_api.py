"""Vidu 官方网页使用的 HTTP 接口客户端；凭据仅保存在进程内存。"""

from uuid import uuid4

import httpx


class ViduError(Exception):
    """只向控制台暴露固定错误说明，不携带响应体或登录凭据。"""


class ViduModerationError(ViduError):
    """官网明确提示该条消息未通过审核。"""


class ViduApi:
    """一个 Studio 会话对应一个独立 Cookie 容器。"""

    def __init__(self, transport=None):
        """创建 HTTP 客户端与设备标识。"""
        self.device_id = 'DEVICE_' + str(uuid4())  # 同一会话保持稳定的设备标识。
        self.authenticated = False  # 已通过登录及用户接口验证的状态。
        self.live = None  # 保存 claim 返回的会话和媒体参数。
        self.client = httpx.AsyncClient(
            base_url='https://service.vidu.cn', timeout=25, transport=transport,
            headers={'Origin': 'https://www.vidu.cn', 'Referer': 'https://www.vidu.cn/',
                     'X-Platform': 'web', 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
        )

    async def request(self, method, path, **kwargs):
        """限制上游异常输出，保留登录失效、限流和校验失败的区分。"""
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise ViduError('Vidu 网络连接失败') from None
        if response.status_code == 401:
            self.authenticated = False
            self.live = None
            raise ViduError('Vidu 登录已失效，请重新登录')
        if response.status_code == 429:
            raise ViduError('Vidu 请求过于频繁，请稍后重试')
        if response.status_code == 403:
            raise ViduError('Vidu 要求额外验证，请在官方页面完成验证')
        if not response.is_success:
            raise ViduError('Vidu 拒绝了请求，请检查验证码或会话状态')
        try:
            data = response.json()
        except ValueError:
            raise ViduError('Vidu 返回了非 JSON 响应') from None
        if not isinstance(data, dict) or data.get('error') or data.get('is_success') is False:
            raise ViduError('Vidu 未接受本次操作')
        return data

    async def send_code(self, phone):
        """按实测请求结构发送短信，频率限制由上游响应决定。"""
        await self.request('POST', '/iam/v1/users/send-auth-code', json={
            'channel': 'sms', 'receiver': '+86' + phone, 'purpose': 'login', 'locale': 'en'})
        return {'sent': True}

    async def login(self, phone, code):
        """提交一次性验证码；httpx 自动接收 HttpOnly JWT Cookie。"""
        self.authenticated = False
        self.live = None
        self.client.cookies.clear()
        await self.request('POST', '/iam/v1/users/login', json={
            'id_type': 'phone', 'identity': '+86' + phone, 'auth_type': 'authcode',
            'credential': code, 'device_id': self.device_id, 'invite_code': '',
            'team_invite_code': '', 'receive_marketing_msg': False})
        await self.request('GET', '/iam/v1/users/me')
        self.authenticated = True
        return {'authenticated': True}

    async def claim(self, avatar_id):
        """创建会话并验证两个业务字段；媒体令牌留在内存。"""
        data = await self.request('POST', '/live/v1/live/claim', json={
            'avatar_id': avatar_id, 'call_mode': 'video', 'live_mode': 'avatar',
            'rtc_provider': 'volcengine'})
        if not data.get('live', {}).get('id') or not data.get('rtc', {}).get('user_id'):
            raise ViduError('会话尚未就绪，未取得 live.id 或 rtc.user_id')
        self.live = data
        return {'live_id': data['live']['id'], 'rtc_user_id': data['rtc']['user_id'],
                'media_connected': False}

    def cookie_header(self):
        """只将属于 service.vidu.cn 的 Cookie 发送到固定信令服务。"""
        return '; '.join(f'{c.name}={c.value}' for c in self.client.cookies.jar
                         if c.domain.lstrip('.') == 'service.vidu.cn')

    async def close(self):
        """清空登录态并关闭连接池。"""
        self.client.cookies.clear()
        self.authenticated = False
        self.live = None
        await self.client.aclose()
