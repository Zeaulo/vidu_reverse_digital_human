"""FastAPI 应用入口，提供状态、事件接收和数字人桥接接口。"""

from pathlib import Path
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.vidu import router as vidu_router, sessions, session, saved_accounts
from app.api.obs import router as obs_router
from app.storage import obs_access
from pydantic import BaseModel

from app.config.settings import ROOT_DIR
from app.domain.events import LiveEvent
@asynccontextmanager
async def lifespan(application):
    """服务退出时清理信令连接和内存凭据。"""
    async def purge_accounts():
        """服务运行时定期删除超过 24 小时的账号文件内容。"""
        while True:
            try:
                saved_accounts.read()
            except Exception:
                pass  # 读取失败不影响服务启动；账号列表会向用户显示错误。
            await asyncio.sleep(60)
    purge_task = asyncio.create_task(purge_accounts())
    yield
    purge_task.cancel()
    await asyncio.gather(purge_task, return_exceptions=True)
    for state in list(sessions.values()):  # 关闭每个隔离账号的连接池。
        await state['bridge'].stop()
        state['bridge'].archive.close()  # 服务退出时释放临时归档。
        await state['call'].stop()
        await state['api'].close()
    sessions.clear()
    obs_access.tokens.clear()  # 进程停止时所有 OBS 地址失效。


app = FastAPI(title="Vidu 数字人直播桥", version="0.14.2", lifespan=lifespan)
app.include_router(vidu_router)
app.include_router(obs_router)
app.mount("/assets", StaticFiles(directory=ROOT_DIR / "web" / "assets"), name="assets")


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    """避免默认校验错误回显手机号和验证码。"""
    return JSONResponse(status_code=422, content={'detail': '输入格式不正确，请检查字段'})


class RoomRequest(BaseModel):
    """接收控制台提交的抖音房间配置。"""
    room_id: str


class WarmupRequest(BaseModel):
    """当前会话暖场开关。"""
    enabled: bool


@app.get("/api/health")
async def health() -> dict:
    """返回服务和队列健康状态。"""
    return {"status": "ok", "version": "0.14.2"}


@app.post("/api/session/room")
async def set_room(body: RoomRequest, request: Request) -> dict:
    """设置当前抖音直播间 ID。"""
    room_id = body.room_id.strip()
    if not room_id.isdigit():
        raise HTTPException(status_code=400, detail="直播间 ID 必须是数字")
    bridge = session(request)['bridge']  # 当前浏览器专属采集器。
    await bridge.start(room_id)
    return bridge.snapshot()


@app.post("/api/danmaku")
async def receive_event(event: LiveEvent, request: Request) -> dict:
    """接收上游采集器事件，并将通过过滤的事件放入队列。"""
    bridge = session(request)['bridge']
    bridge.receive(event)
    return {'received': True, 'event_id':event.event_id}


@app.get("/api/events")
async def list_events(request: Request) -> dict:
    """返回当前队列中的事件，便于控制台展示。"""
    return session(request)['bridge'].snapshot()


@app.get('/api/events/export')
async def export_events(request: Request):
    """导出当前连接完整事件，保留统计和最新调度状态。"""
    bridge = session(request)['bridge']  # 导出仅限当前本地会话。
    events = bridge.archive.all()
    if not events:
        raise HTTPException(404, '本次连接没有可保存的直播记录')
    for event in events:  # 删除只用于归档更新的内部序号。
        event.pop('_archive_sequence', None)
    return {'room_id': bridge.room_id, 'state': bridge.state, 'counts': dict(bridge.counts), 'events': events}


@app.post('/api/session/room/stop')
async def stop_room(request: Request):
    """停止本会话的采集任务，不影响其他窗口。"""
    bridge = session(request)['bridge']
    await bridge.stop()
    return bridge.snapshot()


@app.post('/api/session/warmup')
async def set_warmup(body: WarmupRequest, request: Request):
    """控制当前会话的入场、点赞和礼物暖场。"""
    bridge = session(request)['bridge']
    bridge.set_warmup(body.enabled)
    return bridge.snapshot()


@app.get("/")
async def index() -> FileResponse:
    """返回本地控制台页面。"""
    return FileResponse(Path(ROOT_DIR / "web" / "index.html"))


@app.get('/obs')
async def obs_page():
    """OBS 专用页面；访问令牌只存在 URL 片段，不进入服务器访问日志。"""
    return FileResponse(Path(ROOT_DIR / 'web' / 'obs.html'), headers={'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'})
