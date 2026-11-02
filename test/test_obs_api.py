"""验证 OBS 令牌隔离、轮换与本地媒体协商。"""
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.api.vidu import sessions


def test_obs_link_access_rotation_and_session_isolation():
    """OBS 只允许访问授权会话，旧令牌轮换后失效。"""
    with TestClient(app) as client:
        headers = {'X-Studio-Request': '1'}
        client.get('/api/vidu/status')
        state = sessions[client.cookies.get('studio_session')]
        state['api'].close_media_target = AsyncMock()
        state['api'].media_answer = AsyncMock(return_value={'type':'answer', 'sdp':'fake'})
        state['api'].set_media_quality = AsyncMock(return_value={'obs': {'applied': True}})
        state['call'].status = 'connected'
        state['call'].media_connected = True
        state['call'].live_id = 'live-1'
        link = client.post('/api/vidu/obs/link', headers=headers, json={}).json()['token']
        assert client.post('/api/vidu/obs/link', headers=headers, json={}).json()['token'] == link
        obs_headers = {'X-Obs-Token':link}
        assert client.get('/api/obs/status').status_code == 401
        assert client.get('/api/obs/status', headers={**obs_headers, 'Origin':'https://example.com'}).status_code == 403
        assert client.get('/api/obs/status', headers=obs_headers).json()['live_id'] == 'live-1'
        offer = {'type':'offer', 'sdp':'fake', 'live_id':'live-1'}
        assert client.post('/api/obs/answer', headers=obs_headers, json=offer).status_code == 200
        state['api'].media_answer.assert_awaited_once_with({'type':'offer', 'sdp':'fake'}, target='obs', percent=100)
        assert client.post('/api/vidu/media/quality/settings', headers=headers, json={'percent':25}).status_code == 422
        assert client.post('/api/vidu/media/quality/settings', headers=headers, json={'percent':50}).json()['percent'] == 50
        assert client.get('/api/vidu/status').json()['relay_percent'] == 50
        assert client.post('/api/obs/answer', headers=obs_headers, json=offer).status_code == 200
        state['api'].media_answer.assert_awaited_with({'type':'offer', 'sdp':'fake'}, target='obs', percent=50)
        assert client.post('/api/obs/answer', headers=obs_headers, json={**offer, 'live_id':'old'}).status_code == 409
        first_cookie = client.cookies.get('studio_session')  # 第二个 Studio 会话不得管理第一个会话的链接。
        client.cookies.clear()
        client.get('/api/vidu/status')
        assert client.post('/api/vidu/obs/revoke', headers=headers).status_code == 200
        assert client.get('/api/obs/status', headers=obs_headers).status_code == 200
        client.cookies.clear()
        client.cookies.set('studio_session', first_cookie)
        new_token = client.post('/api/vidu/obs/link', headers=headers, json={'rotate':True}).json()['token']
        assert new_token != link and client.get('/api/obs/status', headers=obs_headers).status_code == 401
        assert client.post('/api/vidu/obs/revoke', headers=headers).status_code == 200
        assert client.get('/api/obs/status', headers={'X-Obs-Token':new_token}).status_code == 401
        state['call'].status = 'stopped'  # 模拟状态避免测试清理时访问真实浏览器。
