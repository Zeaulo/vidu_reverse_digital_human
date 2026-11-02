"""以浏览器网络栈执行官方 HTTP 和 WebSocket，指令不经过页面输入框。"""

from pathlib import Path
import asyncio

from app.adapters.vidu_api import ViduApi, ViduError, ViduModerationError


class ViduBrowserApi(ViduApi):
    """每个 Studio 会话独享临时浏览器上下文，重启后不保留凭据。"""

    def __init__(self):
        """浏览器按需启动，避免打开 Studio 就创建多个浏览器。"""
        super().__init__()
        self.driver = None  # Playwright 生命周期。
        self.browser = None  # 可见 Chrome，便于用户完成官方验证和观察通话。
        self.page = None  # 官网运行环境，负责媒体和信令。
        self.context = None  # 隔离 Cookie 容器。
        self.avatar_id = None  # 重连时沿用用户选择的角色。
        self.start_lock = asyncio.Lock()  # 防止并发重复初始化。

    async def ensure_browser(self):
        """使用 Chrome 正常运行网页；不自行计算或伪造浏览器校验参数。"""
        async with self.start_lock:
            if self.page and not self.page.is_closed():
                return
            self.authenticated = False  # 旧窗口失效后，新上下文不能继承旧登录状态。
            if self.driver:
                await self.close_browser()  # 回收失效上下文，再启动新的窗口。
            from playwright.async_api import async_playwright
            try:
                self.driver = await async_playwright().start()
                self.browser = await self.driver.chromium.launch(channel='chrome', headless=False,
                    args=['--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
                self.context = await self.browser.new_context(permissions=['microphone'])
                await self.context.add_init_script(path=str(Path(__file__).with_name('vidu_runtime.js')))
                await self.context.add_init_script(path=str(Path(__file__).with_name('moderation_dialog.js')))
                await self.context.add_init_script(path=str(Path(__file__).with_name('media_relay.js')))
                self.page = await self.context.new_page()
                await self.page.goto('https://www.vidu.cn/vidu-stream/avatar', wait_until='domcontentloaded')
            except Exception:
                await self.close_browser()
                raise ViduError('浏览器运行环境启动失败，请检查 Chrome 安装和网络') from None

    async def request(self, method, path, **kwargs):
        """同一浏览器内 fetch 携带 HttpOnly Cookie，不导出凭据。"""
        if not self.browser_ready():
            self.authenticated = False
            raise ViduError('请先启动浏览器窗口')
        try:
            result = await self.page.evaluate('''async ({method,path,body}) => {
                const response = await fetch('https://service.vidu.cn'+path,{method,credentials:'include',
                    headers:body===undefined?{'X-Platform':'web'}:{'Content-Type':'application/json','X-Platform':'web'},
                    body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(25000)});
                const type=response.headers.get('content-type')||'';
                return {status:response.status, data:type.includes('json')?await response.json():null};
            }''', {'method': method, 'path': path, **({'body': kwargs['json']} if 'json' in kwargs else {})})
        except Exception:
            raise ViduError('浏览器接口请求失败，请检查网络或在官方页面完成额外验证') from None
        if result['status'] == 401:
            self.authenticated = False
            self.live = None
            raise ViduError('Vidu 登录已失效，请重新登录')
        if result['status'] == 403 or result['data'] is None:
            raise ViduError('Vidu 要求浏览器验证，自动操作已停止')
        if result['status'] == 429:
            raise ViduError('Vidu 请求过于频繁，请稍后重试')
        if result['status'] >= 400 or not isinstance(result['data'], dict) or result['data'].get('error'):
            raise ViduError('Vidu 拒绝了接口请求')
        return result['data']

    async def login(self, phone, code):
        """在浏览器 Cookie 容器中完成验证码登录。"""
        if not self.browser_ready():
            self.authenticated = False
            raise ViduError('请先启动浏览器窗口')
        await self.context.clear_cookies(name='JWT')
        return await super().login(phone, code)

    async def start_call(self, avatar_id):
        """打开角色媒体运行页，由官方 SDK 建立 RTC；不点击输入框。"""
        if not self.browser_ready():
            self.authenticated = False
            raise ViduError('请先启动浏览器窗口')
        # API 层已要求用户明确同意，复现官网的本地授权标记，避免首次会话悬停。
        user = await self.request('GET', '/iam/v1/users/me')
        identity = user.get('id') or user.get('user', {}).get('id')
        if not identity:
            raise ViduError('未取得登录用户标识，无法初始化通话授权状态')
        await self.page.evaluate('''id => {
            localStorage.setItem('live_video_call_consent_v2_'+id,'true');
            localStorage.setItem('live_face_consent_v1_'+id,'true');
        }''', str(identity))
        self.avatar_id = avatar_id
        self.live = None
        try:
            async with self.page.expect_response(lambda r: '/live/v1/live/claim' in r.url and r.request.method == 'POST', timeout=45000) as future:
                await self.page.goto('https://www.vidu.cn/vidu-stream/live-pro?avatar_id=' + avatar_id + '&from=vidu-stream', wait_until='domcontentloaded')
            response = await future.value
            data = await response.json()
            if response.status == 401:
                self.authenticated = False
            if not data.get('is_success') or not data.get('live', {}).get('id') or not data.get('rtc', {}).get('user_id'):
                raise ViduError('Vidu 未成功创建通话')
            self.live = data
            return {'live_id': data['live']['id'], 'rtc_user_id': data['rtc']['user_id']}
        except ViduError:
            raise
        except Exception:
            raise ViduError('通话初始化未完成，请检查登录、授权和网络') from None

    def browser_ready(self):
        """仅当浏览器及页面仍可用时认为第一步已完成。"""
        return bool(self.browser and self.browser.is_connected() and self.page and not self.page.is_closed())

    async def runtime_status(self):
        """读取脱敏信令和视频状态，并识别官网明确的结束文案。"""
        if not self.page or self.page.is_closed():
            return {'ready': False, 'media': False, 'reason': 'browser_closed'}
        return await self.page.evaluate('''() => {
            const state=window.__studioVidu?.status()||{ready:false,media:false,reason:null};
            // 只采样官网真实视频轨道和累计解码帧，不返回画面或身份信息。
            const videos=[...document.querySelectorAll('video')].filter(video => video.srcObject?.getVideoTracks?.().some(track => track.readyState === 'live'));
            state.source_live=videos.some(video => !video.paused && video.videoWidth > 0 && video.videoHeight > 0);
            state.source_frames=videos.reduce((sum,video) => sum + (video.getVideoPlaybackQuality?.().totalVideoFrames || 0), 0);
            // 必须同时出现完整结束提示，避免单条内容审核拒绝被误判为通话结束。
            const bodyText=document.body?.innerText || '';
            if (bodyText.includes('通话已结束') && bodyText.includes('当前内容不符合规范') && bodyText.includes('直播已结束'))
                state.reason='content_policy_ended';
            else if (!state.reason && bodyText.includes('通话已结束') && bodyText.includes('直播连接超时'))
                state.reason='client_reconnect_timeout';
            return state;
        }''')

    async def send_message(self, text):
        """发送 type 12，等待运行时匹配 type 14；不使用 DOM 控件。"""
        if not self.page:
            raise ViduError('请先开始通话')
        try:
            result = await self.page.evaluate('(text) => window.__studioVidu.send(text)', text)
        except Exception:
            raise ViduError('连接中断，指令状态未知，未自动重发') from None
        if result.get('error'):
            if result.get('code') == 'moderation_rejected':
                raise ViduModerationError('内容审核未通过，请修改后重试')
            raise ViduError(result['error'])
        return result

    async def stop_call(self):
        """发送用户挂断并离开媒体页面，停止 SDK 计时和连接。"""
        if self.page and not self.page.is_closed():
            try:
                await self.page.evaluate('() => window.__studioVidu?.stop()')
                await self.page.evaluate('() => window.__studioMedia?.stop()')
                await self.page.goto('https://www.vidu.cn/vidu-stream/avatar', wait_until='domcontentloaded')
            except Exception:
                await self.close_browser()
                self.authenticated = False
        self.live = None

    async def media_answer(self, offer, target='studio', percent=100):
        """协商本机 WebRTC 播放器，返回 SDP，不返回 Vidu RTC 令牌。"""
        if not self.page or not self.live:
            raise ViduError('通话媒体尚未就绪')
        try:
            return await self.page.evaluate('({offer, target, percent}) => window.__studioMedia.answer(offer, target, percent)', {'offer':offer, 'target':target, 'percent':percent})
        except Exception:
            raise ViduError('本机媒体协商失败，请等待视频出现后重新连接') from None

    async def media_quality(self):
        """只读取脱敏的源轨道与本机发送统计。"""
        if not self.page or self.page.is_closed() or not self.live:
            return {}
        try:
            return await self.page.evaluate('() => window.__studioMedia?.quality() || {}')
        except Exception:
            return {}  # 页面或统计暂时不可用时，保留播放器功能。

    async def set_media_quality(self, percent):
        """在现有接收端上应用比例；通话尚未启动时由后续协商使用。"""
        if not self.page or self.page.is_closed() or not self.live:
            return {}
        try:
            return await self.page.evaluate('(percent) => window.__studioMedia?.setQuality(percent) || {}', percent)
        except Exception:
            return {'browser': {'applied': False, 'detail': '浏览器暂时无法调整转发参数'}}

    async def close_media_target(self, target):
        """撤销指定接收端，不影响官方轨道或其他播放器。"""
        if self.page and not self.page.is_closed():
            try:
                await self.page.evaluate('(target) => window.__studioMedia?.closeTarget(target)', target)
            except Exception:
                pass  # 页面已经销毁时无需额外清理。

    async def close_browser(self):
        """销毁临时浏览器和 Cookie 上下文。"""
        if self.browser:
            await self.browser.close()
        if self.driver:
            await self.driver.stop()
        self.browser = self.context = self.page = self.driver = None

    async def close(self):
        """退出时同时释放 HTTP 和浏览器资源。"""
        await self.close_browser()
        await super().close()
