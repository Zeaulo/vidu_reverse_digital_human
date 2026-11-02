"""本机 OBS 浏览器源的受限状态与媒体协商接口。"""
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.api.vidu import sessions
from app.adapters.vidu_api import ViduError
from app.storage import obs_access


router = APIRouter(prefix='/api/obs')  # OBS 不使用 Studio 登录 Cookie。


def source_session(request):
    """仅接受本机同源请求及有效播放令牌。"""
    origin = request.headers.get('origin')
    if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'):
        raise HTTPException(403, '仅允许本机访问')
    if origin and urlparse(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, '拒绝跨站请求')
    token = request.headers.get('x-obs-token', '')  # 令牌放在请求头中，不写入访问日志。
    owner = obs_access.tokens.get(token)
    state = sessions.get(owner) if owner else None
    if not state:
        raise HTTPException(401, 'OBS 链接无效，请在控制台重新生成')
    return state


class ObsOffer(BaseModel):
    """OBS 接收端 SDP 和期望连接的通话 ID。"""
    type: str = Field(pattern='^offer$')
    sdp: str = Field(min_length=1, max_length=50000)
    live_id: str = Field(min_length=1, max_length=256)


@router.get('/status')
async def status(request: Request, response: Response):
    """不暴露登录信息或 Vidu 媒体令牌。"""
    state = source_session(request)
    response.headers['Cache-Control'] = 'no-store'
    call = state['call'].snapshot()
    return {'state':call['state'], 'media_connected':call['media_connected'], 'live_id':str(call['live_id']) if call['live_id'] is not None else None}


@router.post('/answer')
async def answer(body: ObsOffer, request: Request):
    """向 OBS 的独立接收端提供当前通话的媒体。"""
    state = source_session(request)
    async with state['lock']:
        if source_session(request) is not state:  # 排队期间可能发生令牌撤销。
            raise HTTPException(401, 'OBS 链接无效，请在控制台重新生成')
        call = state['call'].snapshot()
        if not call['media_connected'] or str(call['live_id']) != body.live_id:
            raise HTTPException(409, '通话已变化，请等待重新连接')
        try:
            return await state['api'].media_answer({'type':body.type, 'sdp':body.sdp}, target='obs', percent=state['relay_percent'])
        except ViduError as error:
            raise HTTPException(502, str(error)) from None
