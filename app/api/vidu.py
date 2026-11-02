"""本地 Studio 登录、会话和指令接口；敏感状态只存内存。"""

import asyncio
import secrets
from urllib.parse import urlparse
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.adapters.vidu_api import ViduError
from app.adapters.vidu_browser import ViduBrowserApi
from app.services.call_recovery import CallRecovery
from app.services.live_bridge import LiveBridge
from app.storage.saved_accounts import SavedAccounts
from app.storage import obs_access

router = APIRouter(prefix='/api/vidu')  # Studio 同源接口。
sessions = {}  # 随机 HttpOnly 会话 ID 映射到专属上游客户端。
saved_accounts = SavedAccounts()  # 加密存储仅限当前 Windows 用户。


class PhoneBody(BaseModel):
    """手机号及显式协议同意状态。"""
    phone: str = Field(pattern=r'^1[3-9][0-9]{9}$', repr=False)
    consent: bool = False


class LoginBody(PhoneBody):
    """验证码仅用于一次请求，禁止记录此模型。"""
    code: str = Field(pattern=r'^[0-9]{6}$', repr=False)


class ClaimBody(BaseModel):
    """用户选定的角色和通话个人信息授权确认。"""
    avatar_id: str = Field(pattern=r'^[0-9]+$')
    consent: bool = False
    auto_restart: bool = True  # 默认启用有上限的超时恢复。


class MessageBody(BaseModel):
    """待发送的自定义指令。"""
    text: str = Field(min_length=1, max_length=500)


class SavedAccountBody(BaseModel):
    """选择要恢复或移除的手机号，不在日志中回显。"""
    phone: str = Field(pattern=r'^1[3-9][0-9]{9}$', repr=False)


def session(request: Request):
    """只接受本机同源请求和 Studio 自定义请求头。"""
    host = request.url.hostname
    origin = request.headers.get('origin')
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        raise HTTPException(403, '仅允许本机 Studio 访问')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, '拒绝跨站请求')
    if request.headers.get('x-studio-request') != '1':
        raise HTTPException(403, '请通过 Studio 操作')
    state = sessions.get(request.cookies.get('studio_session'))
    if not state:
        raise HTTPException(401, '请刷新 Studio 初始化本地会话')
    return state


@router.get('/status')
async def status(request: Request, response: Response):
    """初始化隔离会话，返回布尔状态而不返回 Cookie 或媒体令牌。"""
    if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'):
        raise HTTPException(403, '仅允许本机访问')
    key = request.cookies.get('studio_session')
    if key not in sessions:
        if len(sessions) >= 16:
            raise HTTPException(503, '本地会话数量已满，请重启服务')
        key = secrets.token_urlsafe(32)
        api = ViduBrowserApi()
        call = CallRecovery(api)  # 当前账号专属的通话控制器。
        bridge = LiveBridge(call)  # 审核恢复期间暂停本会话的自动调度。
        call.on_policy_pause = bridge.pause_for_policy
        call.on_policy_resume = bridge.resume_after_policy
        sessions[key] = {'api': api, 'call': call, 'bridge': bridge, 'lock': asyncio.Lock(), 'relay_percent': 100}
        response.set_cookie('studio_session', key, httponly=True, samesite='strict')
    api = sessions[key]['api']
    browser_ready = api.browser_ready()  # 窗口关闭时不能继续沿用失效的登录标识。
    if not browser_ready:
        api.authenticated = False
    response.headers['Cache-Control'] = 'no-store'
    return {'browser_ready': browser_ready, 'authenticated': api.authenticated, 'relay_percent': sessions[key]['relay_percent'], **sessions[key]['call'].snapshot()}


async def perform(state, operation):
    """同一会话串行执行上游操作，并转为不含凭据的错误。"""
    async with state['lock']:
        try:
            return await operation()
        except ViduError as error:
            raise HTTPException(502, str(error)) from None


@router.post('/browser/start')
async def start_browser(request: Request):
    """显式启动独立有头浏览器，后续操作复用该窗口。"""
    state = session(request)
    async def operation():
        """等待浏览器页面准备完成再返回结果。"""
        await state['api'].ensure_browser()
        return {'browser_ready': state['api'].browser_ready()}
    return await perform(state, operation)


@router.post('/sms')
async def sms(body: PhoneBody, request: Request):
    """由用户明确点击后发送短信，不自动重复请求。"""
    state = session(request)
    if not body.consent:
        raise HTTPException(400, '请先阅读并同意 Vidu 登录协议')
    return await perform(state, lambda: state['api'].send_code(body.phone))


@router.post('/login')
async def login(body: LoginBody, request: Request):
    """登录成功后将上游 Cookie 保留在本地进程内。"""
    state = session(request)
    if not body.consent:
        raise HTTPException(400, '请先阅读并同意 Vidu 登录协议')
    async def operation():
        """停止旧通话后切换登录，整个操作受会话锁保护。"""
        await state['call'].stop()
        result = await state['api'].login(body.phone, body.code)
        try:
            cookies = await state['api'].context.cookies(['https://www.vidu.cn', 'https://service.vidu.cn'])
            if not cookies:
                raise ValueError('登录后没有可保存的 Cookie')
            saved_accounts.save(body.phone, cookies)
            result['saved'] = True
        except Exception:
            result['saved'] = False  # 登录成功不因本地存储失败被误报为失败。
        return result
    return await perform(state, operation)


@router.get('/accounts')
async def accounts(request: Request):
    """仅列出本机未超过保存期限的手机号，不返回 Cookie。"""
    session(request)
    try:
        return {'accounts': list(saved_accounts.read())}
    except Exception:
        raise HTTPException(500, '无法读取本机保存的账号') from None


@router.post('/accounts/restore')
async def restore_account(body: SavedAccountBody, request: Request):
    """在当前窗口恢复 Cookie，并向 Vidu 验证登录状态。"""
    state = session(request)
    async def operation():
        """验证后才将会话标记为已登录。"""
        api = state['api']
        if not api.browser_ready():
            raise ViduError('请先启动浏览器窗口')
        try:
            record = saved_accounts.read().get(body.phone)
        except Exception:
            raise ViduError('无法读取本机保存的账号') from None
        if not record:
            raise ViduError('保存的登录态已过期，请重新验证码登录')
        await state['call'].stop()
        api.authenticated = False
        await api.context.clear_cookies()
        try:
            await api.context.add_cookies(record['cookies'])
            user = await api.request('GET', '/iam/v1/users/me')
            if not (user.get('id') or user.get('user', {}).get('id')):
                raise ViduError('无法验证保存的账号')
            api.authenticated = True
            return {'authenticated': True}
        except Exception:
            await api.context.clear_cookies()
            api.authenticated = False
            raise ViduError('登录态验证失败，请检查网络或重新验证码登录') from None
    return await perform(state, operation)


@router.post('/accounts/forget')
async def forget_account(body: SavedAccountBody, request: Request):
    """删除选择的持久登录态，不影响当前正在使用的会话。"""
    session(request)
    try:
        saved_accounts.delete(body.phone)
    except Exception:
        raise HTTPException(500, '无法清除保存的账号') from None
    return {'removed': True}


@router.post('/claim')
async def claim(body: ClaimBody, request: Request):
    """创建业务会话；创建成功不等于媒体已经连接。"""
    state = session(request)
    if not state['api'].authenticated:
        raise HTTPException(401, '请先登录 Vidu')
    if not body.consent:
        raise HTTPException(400, '请确认已完成通话个人信息授权')
    return await perform(state, lambda: state['call'].start(body.avatar_id, body.auto_restart))


@router.post('/command')
async def command(body: MessageBody, request: Request):
    """通过业务 WebSocket 发送，始终不调用浏览器输入框。"""
    state = session(request)
    if not state['api'].authenticated:
        raise HTTPException(401, '请先登录 Vidu')
    return await perform(state, lambda: state['call'].send(body.text))


@router.post('/stop')
async def stop(request: Request):
    """用户停止后取消全部自动重启。"""
    state = session(request)
    await state['call'].stop()
    return state['call'].snapshot()


@router.post('/logout')
async def logout(request: Request, response: Response):
    """退出本地会话并清除内存中的所有凭据。"""
    state = session(request)
    async with state['lock']:
        obs_access.revoke(request.cookies.get('studio_session'))  # 退出时撤销 OBS 播放令牌。
        await state['bridge'].stop()
        state['bridge'].archive.close()  # 会话销毁后清理临时直播归档。
        await state['call'].stop()
        await state['api'].close()
        sessions.pop(request.cookies.get('studio_session'), None)
    response.delete_cookie('studio_session')
    return {'logged_out': True}


class MediaOffer(BaseModel):
    """仅接受本地接收端 SDP offer，不允许任意页面执行。"""
    type: str = Field(pattern='^offer$')
    sdp: str = Field(min_length=1, max_length=50000)


class ObsLinkBody(BaseModel):
    """默认复用已有链接；显式要求时轮换。"""
    rotate: bool = False


class RelayQualityBody(BaseModel):
    """仅允许支持的转发比例。"""
    percent: Literal[100, 80, 50]


@router.post('/obs/link')
async def obs_link(body: ObsLinkBody, request: Request):
    """生成或复用播放令牌，轮换时旧播放器立即断开。"""
    state = session(request)
    async with state['lock']:
        session_id = request.cookies.get('studio_session')
        token = obs_access.current(session_id)
        if body.rotate or not token:
            await state['api'].close_media_target('obs')
            token = obs_access.issue(session_id)
    return {'token': token}


@router.post('/obs/revoke')
async def obs_revoke(request: Request):
    """撤销本会话 OBS 链接并关闭相应媒体连接。"""
    state = session(request)
    async with state['lock']:
        obs_access.revoke(request.cookies.get('studio_session'))
        await state['api'].close_media_target('obs')
    return {'revoked': True}


@router.post('/media/answer')
async def media_answer(body: MediaOffer, request: Request):
    """以当前会话的官方 SDK 音视频轨道回答本地播放器。"""
    state = session(request)
    return await perform(state, lambda: state['api'].media_answer(body.model_dump(), percent=state['relay_percent']))


@router.post('/media/quality/settings')
async def set_media_quality(body: RelayQualityBody, request: Request):
    """更新当前会话的目标比例，并尝试应用到所有现有接收端。"""
    state = session(request)
    async with state['lock']:
        state['relay_percent'] = body.percent  # 后续通话和新接收端使用同一目标。
        results = await state['api'].set_media_quality(body.percent)
        return {'percent': body.percent, 'results': results}


@router.get('/media/quality')
async def media_quality(request: Request):
    """只允许本机会话查询自身的媒体质量统计。"""
    state = session(request)
    return await state['api'].media_quality()
