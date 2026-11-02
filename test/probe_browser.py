"""浏览器运行环境联调：只在内存转交已授权会话，不输出凭据。"""
import asyncio
import os
from fastapi import FastAPI, Request, HTTPException
from app.adapters.vidu_browser import ViduBrowserApi
from app.adapters.vidu_api import ViduError
from app.services.call_recovery import CallRecovery

app = FastAPI()  # 临时测试服务，仅绑定本机地址。


@app.post('/probe')
async def probe(request: Request):
    """创建一通媒体测试会话，测试结束必定挂断。"""
    if not os.environ.get('VIDU_PROBE_KEY') or request.headers.get('x-probe-key') != os.environ['VIDU_PROBE_KEY']:
        raise HTTPException(403)
    data = await request.json()
    api = ViduBrowserApi()
    call = CallRecovery(api)
    failures = []  # 仅收集网络错误代码和域名，不记录 URL 查询或凭据。
    try:
        await api.ensure_browser()
        api.page.on('requestfailed', lambda r: failures.append({'host':r.url.split('/')[2], 'failure':r.failure}))
        await api.context.add_cookies(data['cookies'])
        await api.page.wait_for_load_state('networkidle', timeout=15000)
        await api.page.evaluate('items => {for(const [key,value] of Object.entries(items)){localStorage.setItem(key,value)}}', data['consents'])
        await api.request('GET', '/iam/v1/users/me')
        api.authenticated = True
        result = await call.start(data['avatar_id'])
        for _ in range(30):  # 最多等待一分钟，不无限创建通话。
            if call.status in ('connected', 'attention', 'exhausted'):
                break
            await asyncio.sleep(2)
        if call.status != 'connected':
            return {'http_authenticated': True, 'call':call.snapshot(), 'runtime':await api.runtime_status()}
        ack = await call.send('Studio 信令测试，请简短回复收到。')
        return {'http_authenticated': True, 'call':call.snapshot(), 'ack':ack}
    except Exception as error:
        return {'error_type':type(error).__name__, 'detail':str(error) if isinstance(error,ViduError) else '测试未完成', 'network':failures[-5:], 'call':call.snapshot()}
    finally:
        await call.stop()
        await api.close()
