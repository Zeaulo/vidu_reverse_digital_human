"""只读真实礼物采集验证：不登录 Vidu、不发送模拟礼物、不消费余额。"""
import asyncio
import json
from pathlib import Path
import httpx
import argparse


async def main(room_id, base_url):
    """有界观察真实消息并验证目录刷新，最终总会停止采集。"""
    async with httpx.AsyncClient(base_url=base_url,timeout=50,trust_env=False,
        headers={'X-Studio-Request':'1'}) as client:
        await client.get('/api/vidu/status')
        await client.post('/api/session/room',json={'room_id':room_id})
        evidence = {'mode':'real_guest_no_vidu'}
        try:
            response = await client.post('/api/gifts/refresh')
            evidence['catalog_refresh'] = {'status':response.status_code,'result':response.json()}
            for _ in range(6):  # 每十秒记录脱敏统计，最多观察一分钟。
                await asyncio.sleep(10)
                data = (await client.get('/api/events')).json()
                gifts = (await client.get('/api/gifts/status')).json()
                print(json.dumps({'state':data['state'],'counts':data['counts'],
                    'gifts':gifts['counts']},ensure_ascii=False),flush=True)
            gifts = (await client.get('/api/gifts/status')).json()
            evidence['gift_counts'] = gifts['counts']
            evidence['gift_samples'] = [{key:row.get(key) for key in ('method','gift_id','name',
                'diamond_count','quantities','quantity','settled_quantity','repeat_end','status','issues')}
                for row in gifts['records']]  # 不落盘昵称、用户 ID、消息 ID。
            evidence['events'] = data['counts']
            evidence['state'] = data['state']
            target = Path('test/artifacts/gift-live-v0.15.0.json')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            await client.post('/api/session/room/stop',json={})
            await client.post('/api/vidu/logout',json={})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)  # 测试房间由执行者指定。
    parser.add_argument('room_id')
    parser.add_argument('--base-url', default='http://localhost:8797')
    args = parser.parse_args()
    asyncio.run(main(args.room_id,args.base_url))
