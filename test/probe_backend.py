"""仅用于已登录浏览器与 Python 直连联调，不保存输入凭据。"""

import os

from fastapi import FastAPI, HTTPException, Request
from app.adapters.vidu_api import ViduApi, ViduError
from app.adapters.vidu_ws import ViduSignalClient

app = FastAPI()  # 仅绑定 127.0.0.1 的临时验证服务。


@app.post('/probe')
async def probe(request: Request):
    """接收测试进程内转交的会话，只返回脱敏的验证结果。"""
    if request.headers.get('x-probe-key') != os.environ.get('VIDU_PROBE_KEY'):
        raise HTTPException(403)
    data = await request.json()  # 测试数据不落盘也不记录日志。
    api = ViduApi()
    signal = ViduSignalClient(api)
    try:
        for cookie in data['cookies']:  # 只复制指定服务域的 Cookie。
            if cookie['domain'].lstrip('.') == 'service.vidu.cn':
                api.client.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])
        api.live = data['claim']
        response = await api.client.get('/iam/v1/users/me')
        metadata = {'status': response.status_code, 'content_type': response.headers.get('content-type'),
                    'html_challenge': 'captcha' in response.text.lower() or 'challenge' in response.text.lower()}
        try:
            result = await signal.send_message('Python 接口联调，请简短回复收到。')
        except ViduError as error:
            result = {'error': str(error)}
        return {'http': metadata, 'websocket_ack': result}
    except ViduError as error:
        return {'error': str(error)}
    finally:
        await signal.close()
        await api.close()
