"""真实联调入口：一次性内存迁移用户已授权的会话，不属于生产 API。"""
import os
from fastapi import Request, HTTPException
from app.main import app
from app.api.vidu import sessions


@app.post('/test/bootstrap')
async def bootstrap(request: Request):
    """需要进程随机密钥和现有 Studio Cookie，成功后销毁密钥。"""
    expected = os.environ.get('VIDU_PROBE_KEY')
    if not expected or request.headers.get('x-probe-key') != expected:
        raise HTTPException(403)
    state = sessions.get(request.cookies.get('studio_session'))
    if not state:
        raise HTTPException(401)
    data = await request.json()  # 凭据只在请求内存中短暂存在。
    api = state['api']
    await api.ensure_browser()
    await api.context.add_cookies(data['cookies'])
    await api.request('GET','/iam/v1/users/me')
    api.authenticated = True
    os.environ.pop('VIDU_PROBE_KEY',None)
    return {'authenticated':True}
