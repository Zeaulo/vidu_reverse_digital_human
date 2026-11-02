"""使用当前前端与隔离演示接口生成公开截图，不读取真实会话。"""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录。
DESTINATION = ROOT / 'docs' / 'images'  # README 的公开图片目录。


class QuietHandler(SimpleHTTPRequestHandler):
    """本地静态文件服务，省略与截图无关的访问日志。"""

    def log_message(self, *_args):
        """截图过程只输出最终文件列表。"""


def main():
    """开启隔离页面，渲染示例事件并保存当前产品界面。"""
    DESTINATION.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'web')))
    threading.Thread(target=server.serve_forever, daemon=True).start()  # 静态服务不加载生产后台。
    state = {'browser_ready': True, 'authenticated': True, 'state': 'idle', 'attempts': 0,
             'max_attempts': 3, 'media_connected': False, 'relay_percent': 100}  # 仅在内存中的演示状态。
    events = [  # 使用虚构昵称与内容展示时间排序和调度反馈。
        {'event_type': 'comment', 'nickname': '观众小林', 'content': '晚上好，今天想听一个有趣的故事！', 'timestamp': '2026-11-02T12:06:32Z', 'delivery': 'accepted'},
        {'event_type': 'comment', 'nickname': '云朵同学', 'content': '第一次来，主播可以介绍一下自己吗？', 'timestamp': '2026-11-02T12:06:28Z', 'delivery': 'accepted'},
        {'event_type': 'comment', 'nickname': '星河', 'content': '这个互动好有意思，关注了。', 'timestamp': '2026-11-02T12:06:24Z', 'delivery': 'queued'},
        {'event_type': 'enter', 'nickname': '晚风', 'timestamp': '2026-11-02T12:06:30Z', 'delivery': 'accepted'},
        {'event_type': 'enter', 'nickname': '橘子', 'timestamp': '2026-11-02T12:06:22Z', 'delivery': 'accepted'},
        {'event_type': 'like', 'nickname': '青山', 'like_count': 8, 'timestamp': '2026-11-02T12:06:29Z', 'delivery': 'accepted'},
        {'event_type': 'like', 'nickname': '月亮船', 'like_count': 3, 'timestamp': '2026-11-02T12:06:20Z', 'delivery': 'observed'},
    ]
    baseline = json.loads((ROOT / 'data/gifts/baseline-2026-11-02.json').read_text(encoding='utf-8'))  # 公开目录快照。
    visible_gifts = [gift for gift in baseline['gifts'] if gift.get('is_displayed_on_panel') is True]  # 默认只展示面板可见项。
    rules = [{'gift_id': '2001', 'enabled': True, 'thanks': True, 'min_count': 3,
              'instruction': '向镜头比心，并对{昵称}说：谢谢你的{数量}个{礼物名称}，祝你今天开心！'}]  # 示例礼物规则。

    def reply(route):
        """所有 API 请求都返回演示数据，禁止请求真实上游。"""
        path = route.request.url.split('/api/')[-1]
        if path == 'vidu/status':
            data = state
        elif path == 'vidu/accounts':
            data = {'accounts': []}
        elif path == 'events':
            data = {'state': 'online', 'room_id': '100000000001', 'queue_size': 1,
                    'automation': {'enter': False, 'like': False, 'comment': True},
                    'counts': {'received': 7, 'comment': 3, 'enter': 2, 'like': 2, 'likes': 11,
                               'queued': 6, 'sent': 5, 'accepted': 5}, 'events': events, 'detail': ''}
        elif path == 'gifts/rules':
            data = {'rules': rules}
        elif path.startswith('gifts/catalog'):
            query = parse_qs(urlsplit(route.request.url).query)  # 按真实前端搜索参数筛选演示目录。
            search = query.get('search', [''])[0]
            items = [gift for gift in visible_gifts if search in gift['id'] or search in gift['name']]
            data = {'items': [{**gift, 'source': 'historical_snapshot', 'updated_at': '2026-11-02'} for gift in items[:5]],
                    'total': len(items), 'visible_count': len(visible_gifts), 'hidden_count': 788, 'unknown_count': 0,
                    'include_hidden': query.get('include_hidden', ['false'])[0] == 'true', 'cache_fresh': False, 'room_id': ''}
        elif path == 'gifts/status':
            data = {'counts': {}, 'records': [], 'deliveries': [], 'dispatch': {}}
        else:
            data = {}
        route.fulfill(content_type='application/json', body=json.dumps(data))

    try:
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel='chrome', headless=True)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1.5, timezone_id='Asia/Shanghai')
                page.route('**/api/**', reply)
                page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='networkidle')
                page.locator('#events').get_by_text('晚上好，今天想听一个有趣的故事！').wait_for()
                page.locator('.rule-selected').get_by_text('玫瑰', exact=False).wait_for()
                page.locator('#gift-catalog tr').first.wait_for()
                page.locator('img').evaluate_all("images => images.forEach(image => image.loading = 'eager')")  # 截图前主动加载目录缩略图。
                page.wait_for_function('Array.from(document.images).every(image => image.complete)', timeout=20000)
                page.evaluate('document.fonts.ready')
                page.evaluate("""() => {
                    // 演示水印在截图页内呈现，清楚区分示例界面和真实直播证据。
                    const badge = document.createElement('p');
                    badge.textContent = '界面演示 · 虚构账号状态与直播事件 · 视频未连接';
                    badge.style.cssText = 'color:#b9c6a2;font-size:13px;margin-top:18px';
                    document.querySelector('.studio-header').append(badge);
                }""")
                page.screenshot(path=str(DESTINATION / 'studio-overview.jpg'), type='jpeg', quality=88, full_page=True)
                page.locator('.gift-rules').evaluate('element => element.open = false')  # 连接截图聚焦四步操作。
                connection = page.locator('#step-call').locator('xpath=..')  # 账号与分步连接区域。
                connection.screenshot(path=str(DESTINATION / 'connection.jpg'), type='jpeg', quality=90)
                page.locator('.gift-rules').evaluate('element => element.open = true')
                page.locator('#rule-preview').click()
                page.locator('.gift-rules').screenshot(path=str(DESTINATION / 'gift-rules.jpg'), type='jpeg', quality=90)
                page.locator('#gift-catalog').locator('xpath=../../..').screenshot(path=str(DESTINATION / 'gift-catalog.jpg'), type='jpeg', quality=90)
                page.locator('#avatar-video').locator('xpath=../..').screenshot(path=str(DESTINATION / 'media-obs.jpg'), type='jpeg', quality=90)
                page.locator('#live-room').screenshot(path=str(DESTINATION / 'live-events.jpg'), type='jpeg', quality=90)
                print('已生成当前界面的演示截图：' + ', '.join(path.name for path in DESTINATION.glob('*.jpg')))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
