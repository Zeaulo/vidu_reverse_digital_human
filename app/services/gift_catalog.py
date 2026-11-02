"""礼物目录：事件优先，当前房间缓存其次，历史快照仅作补缺。"""
import asyncio
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from app.config.settings import ROOT_DIR
from app.adapters.douyin_gifts import identity, number, value
from app.services.gift_images import safe_gift_image


class GiftCatalog:
    """每个会话独立缓存，浏览器只读刷新不依赖 Vidu 登录。"""
    def __init__(self, baseline=None, clock=time.monotonic):
        self.clock = clock  # 控制刷新冷却和缓存有效期。
        self.baseline = {}  # 历史目录按礼物 ID 索引。
        self.rooms = {}  # 房间 -> 目录、时间及来源。
        self.observed = {}  # 房间 -> 消息直接观察到的字段。
        self.lock = asyncio.Lock()  # 防止并发启动多个浏览器。
        self.retry_after = 0.0
        self.last_error = None
        self.refreshing = False
        path = baseline or ROOT_DIR/'data/gifts/baseline-2026-11-02.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            self.baseline = {str(row['id']):{**row,'source':'historical_snapshot',
                'updated_at':data['captured_date']} for row in data['gifts']}
        except (OSError,ValueError,KeyError,TypeError):
            self.last_error = '历史目录读取失败，事件采集仍可继续'

    def entries(self, room_id):
        """按来源优先级合并，过期房间目录不再参与补缺。"""
        result = {key:dict(row) for key,row in self.baseline.items()}
        cache = self.rooms.get(room_id)
        if cache and self.clock()-cache['stamp'] < 3600:
            result.update(cache['rows'])
        for key,row in self.observed.get(room_id,{}).items():
            previous = result.get(key,{})
            result[key] = {**previous,**row}
            if ('name' not in row and previous.get('name') is not None) or ('diamond_count' not in row and previous.get('diamond_count') is not None):
                result[key]['source'] = 'mixed_reference'
        return result

    def enrich(self, gift):
        """事件中的非空字段优先，快照价格不伪装成实时单价。"""
        if not gift.gift_id:
            return gift
        fallback = self.entries(gift.room_id).get(gift.gift_id,{})
        observed = {'id':gift.gift_id,'source':'event',
                    'updated_at':datetime.now(timezone.utc).isoformat()}
        for key,field in (('name',gift.name),('diamond_count',gift.diamond_count),('image',gift.image)):
            if field is not None:
                observed[key] = safe_gift_image(field) if key == 'image' else field
        rows = self.observed.setdefault(gift.room_id,{})
        while len(self.observed)>8:
            self.observed.pop(next(iter(self.observed)))
        # 同 ID 的新包若缺字段，不清除此前已观察的有效字段。
        if gift.name is not None or gift.diamond_count is not None or gift.image is not None:
            rows[gift.gift_id] = {**rows.get(gift.gift_id,{}),**observed}
        if len(rows) > 5000:
            rows.pop(next(iter(rows)))
        if not gift.name:
            gift.name = fallback.get('name')
            gift.metadata_source = fallback.get('source','unknown') if gift.name else 'unknown'
        if gift.diamond_count is None and fallback.get('diamond_count') is not None:
            gift.diamond_count = fallback['diamond_count']
            gift.price_source = 'catalog_reference'
        return gift

    def query(self, room_id, search='', offset=0, limit=50):
        """按 ID 或名称查询并分页，保留同名不同 ID。"""
        rows = self.entries(room_id).values()
        needle = search.casefold().strip()
        matched = [row for row in rows if needle in str(row['id']).casefold() or needle in str(row.get('name','')).casefold()]
        matched.sort(key=lambda row:(row.get('name') or '',row['id']))
        cache = self.rooms.get(room_id)
        return {'items':matched[offset:offset+limit],'total':len(matched),
                'offset':offset,'limit':limit,'room_id':room_id,'refreshing':self.refreshing,
                'cache_fresh':bool(cache and self.clock()-cache['stamp'] < 3600),
                'error':self.last_error,'retry_in':max(0,round(self.retry_after-self.clock()))}

    def import_response(self, room_id, payload):
        """兼容顶层及分栏目录，只接受成功且确实有礼物的响应。"""
        if payload.get('status_code') != 0 or not isinstance(payload.get('data'),dict):
            raise ValueError('礼物目录请求未成功')
        data = payload['data']
        gifts = list(data.get('gifts') or [])
        for page in data.get('pages') or []:
            gifts.extend(page.get('gifts') or [])
        rows = {}
        stamp = datetime.now(timezone.utc).isoformat()
        for gift in gifts:
            key = identity(gift.get('id_str') or gift.get('id'))
            if not key:
                continue
            rows[key] = {'id':key,'name':gift.get('name'),
                'diamond_count':number(value(gift,'diamondCount','diamond_count')),
                'type':gift.get('type'),'combo':gift.get('combo'),
                'image':safe_gift_image(gift.get('image')),
                'source':'room_catalog','updated_at':stamp}
        if not rows:
            raise ValueError('当前响应未包含礼物，保留已有目录')
        self.rooms[room_id] = {'rows':rows,'stamp':self.clock()}
        while len(self.rooms) > 8:
            self.rooms.pop(next(iter(self.rooms)))
        self.last_error = None
        return len(rows)

    async def refresh(self, room_id):
        """正常访客浏览器读取网页自动请求的目录，验证失败不循环重试。"""
        if not room_id.isascii() or not room_id.isdigit() or len(room_id)>30:
            raise ValueError('请先连接有效直播间')
        if self.lock.locked() or self.clock() < self.retry_after:
            raise ValueError('目录刷新正在进行或冷却中，请稍后再试')
        async with self.lock:
            self.refreshing = True
            self.retry_after = self.clock()+60
            from playwright.async_api import async_playwright
            try:
                async with async_playwright() as driver:
                    browser = await driver.chromium.launch(channel='chrome',headless=False)
                    try:
                        context = await browser.new_context()  # 不导入任何账号 Cookie。
                        page = await context.new_page()
                        async with page.expect_response(lambda response: urlparse(response.url).hostname == 'live.douyin.com' and urlparse(response.url).path == '/webcast/gift/list/',timeout=35000) as future:
                            await page.goto('https://live.douyin.com/'+room_id,wait_until='domcontentloaded',timeout=30000)
                        response = await future.value
                        if response.status != 200:
                            raise ValueError('目录接口未成功，请在官方页面检查状态')
                        count = self.import_response(room_id,await response.json())
                        return {'count':count,'room_id':room_id}
                    finally:
                        await browser.close()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = str(error) if isinstance(error,ValueError) else '未取得目录，房间可能下播或需要官方验证；已有目录继续可用'
                raise ValueError(self.last_error) from None
            finally:
                self.refreshing = False
