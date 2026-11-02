"""有界匿名采集测试，只输出消息类型和字段名称。"""
import asyncio
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 直接运行时加载项目模块。
from app.adapters.douyin import DouyinAdapter


async def main(room_id):
    """观察最多三十秒，遇到验证或未知状态立即结束。"""
    counts = Counter()
    adapter = DouyinAdapter('ws://127.0.0.1:1088', room_id)  # 房间由测试者显式指定。
    try:
        async with asyncio.timeout(30):
            async for frame in adapter.frames():
                if frame.get('type') == 'system':
                    print({key:frame.get(key) for key in ('code','status','message')},flush=True)
                    if frame.get('code') in ('ROOM_STATUS_UNKNOWN','ROOM_NOT_FOUND'):
                        break
                else:
                    method = frame.get('method','unknown')
                    counts[method] += 1
                    if counts[method] == 1:
                        print({'method':method,'keys':list(frame),'normalized':bool(adapter.normalize(frame))},flush=True)
    except TimeoutError:
        pass
    print(dict(counts),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='观察指定直播间的匿名事件')
    parser.add_argument('room_id', help='需要观察的直播间 ID')
    asyncio.run(main(parser.parse_args().room_id))
