"""当前会话的礼物目录及采集统计，不接受任意外部 URL。"""
import asyncio
from fastapi import APIRouter, Request, Query, HTTPException
from app.api.vidu import session
from app.services.gift_rules import GiftRulesBody

router = APIRouter(prefix='/api/gifts')


@router.get('/rules')
async def rules(request: Request):
    """读取当前会话规则，其他会话无法访问。"""
    return {'rules': [rule.model_dump() for rule in session(request)['bridge'].gift_rules.rules.values()]}


@router.post('/rules')
async def save_rules(body: GiftRulesBody, request: Request):
    """原子保存规则并取消变更规则对应的排队指令。"""
    session(request)['bridge'].set_gift_rules(body.rules)
    return {'rules': [rule.model_dump() for rule in body.rules]}


@router.get('/catalog')
async def catalog(request: Request, search: str = Query('',max_length=100),
                  offset: int = Query(0,ge=0),limit: int = Query(50,ge=1,le=100),
                  include_hidden: bool = Query(False)):
    """目录仅在当前会话房间内合并，查询结果有分页上限。"""
    bridge = session(request)['bridge']
    return bridge.catalog.query(bridge.room_id,search,offset,limit,include_hidden)


@router.get('/status')
async def status(request: Request):
    """礼物采集和发送分别展示，保留未播报的证据。"""
    bridge = session(request)['bridge']
    return {**bridge.gifts.snapshot(),'dispatch':{key:bridge.counts[key] for key in ('gift_queued','gift_sent','gift_accepted')},
            'deliveries':list(bridge.gift_deliveries)}


@router.post('/refresh')
async def refresh(request: Request):
    """用户主动刷新；停止采集或退出会话可取消访客浏览器。"""
    bridge = session(request)['bridge']
    if bridge.catalog_task and not bridge.catalog_task.done():
        raise HTTPException(409,'礼物目录刷新正在进行')
    bridge.catalog_task = asyncio.create_task(bridge.catalog.refresh(bridge.room_id))
    try:
        return await bridge.catalog_task
    except ValueError as error:
        raise HTTPException(502,str(error)) from None
    except asyncio.CancelledError:
        raise HTTPException(409,'目录刷新已取消') from None
