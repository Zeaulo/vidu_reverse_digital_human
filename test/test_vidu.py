"""使用本地协议替身验证登录、Cookie、回执匹配和错误脱敏。"""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from app.adapters.vidu_api import ViduApi, ViduError
from app.adapters.vidu_ws import ViduSignalClient
from app.main import app


def test_sms_has_no_local_cooldown():
    """连续验证码请求交给上游判断，本地不预设六十秒冷却。"""
    async def run():
        requests = []  # 记录实际转发给模拟上游的次数。
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={})
        api = ViduApi(httpx.MockTransport(handler))
        try:
            assert await api.send_code('13800000000') == {'sent': True}
            assert await api.send_code('13800000000') == {'sent': True}
            assert len(requests) == 2
        finally:
            await api.close()
    asyncio.run(run())


def test_browser_must_start_before_sms():
    """未启动窗口时短信请求不能隐式启动浏览器。"""
    with TestClient(app) as client:
        state = client.get('/api/vidu/status').json()
        assert not state['browser_ready']
        response = client.post('/api/vidu/sms', headers={'X-Studio-Request': '1'},
                               json={'phone': '13800000000', 'consent': True})
        assert response.status_code == 502
        assert '请先启动浏览器窗口' in response.text


def test_login_cookie_and_claim():
    """登录响应中的 HttpOnly JWT 应用于后续请求，不返回给控制台。"""
    async def run():
        def handler(request):
            """只模拟实测结构，不调用短信服务。"""
            if request.url.path.endswith('/login'):
                assert json.loads(request.content)['auth_type'] == 'authcode'
                return httpx.Response(200, json={}, headers={'set-cookie': 'JWT=test-secret; Domain=service.vidu.cn; Path=/; HttpOnly; Secure'})
            assert 'JWT=test-secret' in request.headers['cookie']
            if request.url.path.endswith('/claim'):
                return httpx.Response(200, json={'is_success': True, 'live': {'id': '123'},
                    'rtc': {'user_id': 'rtc-user', 'token': 'media-secret'}})
            return httpx.Response(200, json={'id': 'user'})
        api = ViduApi(httpx.MockTransport(handler))
        try:
            assert await api.login('13800000000', '123456') == {'authenticated': True}
            result = await api.claim('123')
            assert result['rtc_user_id'] == 'rtc-user'
            assert 'secret' not in str(result)
            assert api.cookie_header() == 'JWT=test-secret'
        finally:
            await api.close()
        assert not api.client.cookies
    asyncio.run(run())


def test_signal_correlates_ack_and_preserves_sequence():
    """错误消息 ID 的回执不能使当前指令成功；消息序号严格递增。"""
    async def run():
        class Socket:
            """自动回复握手和两个不同 ID 的回执。"""
            def __init__(self):
                self.sent = []
                self.inbox = asyncio.Queue()
            async def send(self, raw):
                frame = json.loads(raw)
                self.sent.append(frame)
                if frame['type'] == 1:
                    await self.inbox.put({'type': 2, 'conn_id': 'connection', 'payload': {'conn_init_ack': {'success': True}}})
                else:
                    for identity in ['other-message', frame['payload']['text_input']['client_msg_id']]:
                        await self.inbox.put({'type': 14, 'payload': {'text_input_ack': {'client_msg_id': identity, 'accepted': True}}})
            async def recv(self):
                return json.dumps(await self.inbox.get())
            async def close(self):
                pass
        socket = Socket()
        async def connector(url, **kwargs):
            assert url.startswith('wss://service.vidu.cn/live/ws/live/connect?')
            return socket
        api = ViduApi()
        api.live = {'live': {'id': '123'}, 'rtc': {'user_id': 'rtc-user'}}
        signal = ViduSignalClient(api, connector)
        try:
            result = await signal.send_message('测试')
            assert result['accepted']
            assert result['client_msg_id'] != 'other-message'
            assert [frame['seq_id'] for frame in socket.sent] == [0, 1]
            assert socket.sent[1]['conn_id'] == 'connection'
            assert socket.sent[1]['user_id'] == 'rtc-user'
        finally:
            await signal.close()
            await api.close()
    asyncio.run(run())


def test_html_response_is_not_login_success():
    """HTTP 200 返回 HTML 时必须失败，不能误判登录成功。"""
    async def run():
        api = ViduApi(httpx.MockTransport(lambda _: httpx.Response(200, text='<html>page</html>')))
        try:
            try:
                await api.login('13800000000', '123456')
                assert False, '非 JSON 响应不应成功'
            except ViduError as error:
                assert str(error) == 'Vidu 返回了非 JSON 响应'
                assert not api.authenticated
        finally:
            await api.close()
    asyncio.run(run())


def test_studio_blocks_cross_origin_and_redacts_validation():
    """外站不能驱动短信发送，输入校验不能回显验证码。"""
    with TestClient(app) as client:
        client.get('/api/vidu/status')
        payload = {'phone': '13800000000', 'code': 'secret-invalid', 'consent': True}
        response = client.post('/api/vidu/login', json=payload, headers={'X-Studio-Request': '1'})
        assert response.status_code == 422
        assert 'secret-invalid' not in response.text
        response = client.post('/api/vidu/sms', json={'phone': '13800000000', 'consent': True},
            headers={'X-Studio-Request': '1', 'Origin': 'https://untrusted.example'})
        assert response.status_code == 403


def test_studio_accounts_are_isolated():
    """不同浏览器会话不能继承上一个用户的本地登录标识。"""
    with TestClient(app) as first, TestClient(app) as second:
        first.get('/api/vidu/status')
        second.get('/api/vidu/status')
        assert first.cookies.get('studio_session') != second.cookies.get('studio_session')
