"""验证本机加密账号保存、到期和删除。"""
from app.storage.saved_accounts import SavedAccounts
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import app
import app.api.vidu as vidu


def test_accounts_encrypted_expire_and_delete():
    """Cookie 不能明文写入，超过一天不能恢复，删除立即生效。"""
    now = [1000.0]  # 可控时间，避免等待一天。
    artifacts = Path(__file__).parent / 'artifacts'  # 测试临时文件统一放在项目 test 目录内。
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=artifacts) as temporary:
        path = Path(temporary) / 'accounts.bin'
        store = SavedAccounts(path, clock=lambda: now[0])
        cookies = [{'name': 'JWT', 'value': 'private-cookie'}]
        store.save('13800000000', cookies)
        assert b'private-cookie' not in path.read_bytes()
        assert store.read()['13800000000']['cookies'] == cookies
        now[0] += 86401
        assert store.read() == {}
        store.save('13900000000', cookies)
        store.delete('13900000000')
        assert not store.read()


def test_restore_checks_upstream_and_does_not_return_cookie(monkeypatch):
    """恢复账号须校验上游，接口响应不能包含 Cookie。"""
    artifacts = Path(__file__).parent / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=artifacts) as temporary:
        store = SavedAccounts(Path(temporary) / 'accounts.bin')
        store.save('13800000000', [{'name': 'JWT', 'value': 'private-cookie', 'domain': '.vidu.cn', 'path': '/'}])
        monkeypatch.setattr(vidu, 'saved_accounts', store)
        with TestClient(app) as client:
            client.get('/api/vidu/status')
            api = vidu.sessions[client.cookies.get('studio_session')]['api']
            monkeypatch.setattr(api, 'browser_ready', lambda: True)
            api.context = type('Context', (), {'clear_cookies': AsyncMock(), 'add_cookies': AsyncMock()})()
            monkeypatch.setattr(api, 'request', AsyncMock(return_value={'id': 'user'}))
            headers = {'X-Studio-Request': '1'}
            response = client.post('/api/vidu/accounts/restore', headers=headers, json={'phone': '13800000000'})
            assert response.status_code == 200 and api.authenticated
            assert 'private-cookie' not in response.text
            api.request.assert_awaited_once_with('GET', '/iam/v1/users/me')
            api.request = AsyncMock(side_effect=RuntimeError('上游拒绝'))
            failed = client.post('/api/vidu/accounts/restore', headers=headers, json={'phone': '13800000000'})
            assert failed.status_code == 502 and not api.authenticated
            assert 'private-cookie' not in failed.text
            assert client.post('/api/vidu/accounts/forget', headers=headers, json={'phone': '13800000000'}).status_code == 200
            assert store.read() == {}
