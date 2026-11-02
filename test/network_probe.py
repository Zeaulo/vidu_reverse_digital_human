"""比较环境代理与直连的公开接口响应，不读取账号凭据。"""
import asyncio
import re
import json
import httpx


async def main():
    """只输出响应类型、标题和无认证用户接口状态。"""
    for use_env in (True, False):  # 先复现当前代理路径，再检查直连。
        async with httpx.AsyncClient(trust_env=use_env, timeout=12) as client:
            for path in ('/vidu/v1/region', '/iam/v1/users/me'):
                try:
                    response = await client.get('https://service.vidu.cn' + path)
                    title = re.search(r'<title[^>]*>(.*?)</title>', response.text, re.S)
                    print(json.dumps({'environment_proxy': use_env, 'path': path,
                        'status': response.status_code, 'type': response.headers.get('content-type'),
                        'title': title.group(1)[:150] if title else None,
                        'bytes': len(response.content)}, ensure_ascii=False))
                except httpx.HTTPError as error:
                    print(json.dumps({'environment_proxy': use_env, 'error_type': type(error).__name__}))


if __name__ == '__main__':
    asyncio.run(main())
