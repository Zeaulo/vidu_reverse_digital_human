"""Vidu 业务 WebSocket：发送自定义指令，无需操作页面输入框。"""

import asyncio
import json
import time
from urllib.parse import urlencode
from uuid import uuid4

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from app.adapters.vidu_api import ViduError


class ViduSignalClient:
    """同一连接内串行发送，回执不明时不自动重发以避免重复动作。"""

    def __init__(self, api, connector=connect):
        """注入会话及连接工厂，便于使用本地协议测试。"""
        self.api = api  # 持有当前 Cookie 和 claim 结果的 HTTP 客户端。
        self.connector = connector  # 可替换的连接工厂。
        self.socket = None  # 当前业务信令连接。
        self.conn_id = None  # 服务端握手分配的连接标识。
        self.seq = 0  # 每条发送信令递增。
        self.lock = asyncio.Lock()  # 保护接收回执的唯一消费者。

    async def emit(self, kind, payload=None):
        """构建官网前端同结构的业务消息。"""
        frame = {'seq_id': self.seq, 'type': kind, 'live_id': self.api.live['live']['id']}
        if payload is not None:
            frame.update(user_id=self.api.live['rtc']['user_id'], conn_id=self.conn_id, payload=payload)
        self.seq += 1
        await self.socket.send(json.dumps(frame, ensure_ascii=False))

    async def receive(self):
        """校验消息格式，遇到服务端挂断或错误立即停止。"""
        frame = json.loads(await self.socket.recv())
        if not isinstance(frame, dict):
            raise ViduError('Vidu 返回了无法识别的信令')
        if frame.get('type') in (6, 10, 15):
            raise ViduError('Vidu 会话结束或拒绝了指令')
        return frame

    async def ready(self):
        """完成 type 1/2 握手，NOT_READY 在超时范围内等待重试。"""
        if self.socket is not None:
            return
        if not self.api.live:
            raise ViduError('请先创建 Vidu 会话')
        url = 'wss://service.vidu.cn/live/ws/live/connect?' + urlencode({'live_id': self.api.live['live']['id']})
        self.seq = 0
        self.socket = await self.connector(url, additional_headers={'Cookie': self.api.cookie_header()},
                                           origin='https://www.vidu.cn', open_timeout=15)
        await self.emit(1)
        while True:  # 收到有效初始化回执才允许发送文本。
            frame = await self.receive()
            if frame.get('type') != 2:
                continue
            ack = frame.get('payload', {}).get('conn_init_ack', {})
            if ack.get('success') is True and frame.get('conn_id'):
                self.conn_id = frame['conn_id']
                return
            if ack.get('error_code') == 'NOT_READY':
                await asyncio.sleep(2)
                await self.emit(1)
                continue
            raise ViduError('Vidu 信令初始化失败')

    async def send_message(self, text):
        """等待匹配 client_msg_id 的 accepted 回执，区分接收与生成完成。"""
        async with self.lock:
            try:
                async with asyncio.timeout(25):
                    await self.ready()
                    message_id = str(uuid4())  # 每条业务指令具有独立 ID。
                    await self.emit(12, {'text_input': {'client_msg_id': message_id,
                                    'content': text, 'timestamp': int(time.time() * 1000)}})
                    while True:  # 忽略不属于本条指令的异步回执。
                        frame = await self.receive()
                        ack = frame.get('payload', {}).get('text_input_ack', {})
                        if frame.get('type') != 14 or ack.get('client_msg_id') != message_id:
                            continue
                        if ack.get('accepted') is not True:
                            raise ViduError('Vidu 未接受这条指令')
                        return {'accepted': True, 'client_msg_id': message_id}
            except (TimeoutError, OSError, WebSocketException, ValueError, ViduError) as error:
                await self.close()
                if isinstance(error, ViduError):
                    raise
                raise ViduError('信令连接失败或回执超时；未自动重发，请先确认接收状态') from None

    async def close(self):
        """关闭本客户端信令连接，不冒充媒体连接状态。"""
        if self.socket is not None:
            await self.socket.close()
        self.socket = None
        self.conn_id = None
