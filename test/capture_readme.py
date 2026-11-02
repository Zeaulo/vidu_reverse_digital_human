"""使用当前前端与隔离演示接口生成公开截图，不读取真实会话。"""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

    def reply(route):
        """所有 API 请求都返回演示数据，禁止请求真实上游。"""
        path = route.request.url.split('/api/')[-1]
        if path == 'vidu/status':
            data = state
        elif path == 'vidu/accounts':
            data = {'accounts': []}
        elif path == 'events':
            data = {'state': 'online', 'room_id': '100000000001', 'queue_size': 1, 'warmup': True,
                    'counts': {'received': 7, 'comment': 3, 'enter': 2, 'like': 2, 'likes': 11,
                               'queued': 6, 'sent': 5, 'accepted': 5}, 'events': events, 'detail': ''}
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
                page.evaluate('document.fonts.ready')
                page.evaluate("""() => {
                    // 演示水印在截图页内呈现，清楚区分示例界面和真实直播证据。
                    const badge = document.createElement('p');
                    badge.textContent = '界面演示 · 虚构账号状态与直播事件 · 视频未连接';
                    badge.style.cssText = 'color:#b9c6a2;font-size:13px;margin-top:18px';
                    document.querySelector('.studio-header').append(badge);
                }""")
                page.screenshot(path=str(DESTINATION / 'studio-overview.jpg'), type='jpeg', quality=88, full_page=True)
                connection = page.locator('#step-call').locator('xpath=..')  # 账号与分步连接区域。
                connection.screenshot(path=str(DESTINATION / 'connection.jpg'), type='jpeg', quality=90)
                page.locator('#avatar-video').locator('xpath=../..').screenshot(path=str(DESTINATION / 'media-obs.jpg'), type='jpeg', quality=90)
                page.locator('#live-room').screenshot(path=str(DESTINATION / 'live-events.jpg'), type='jpeg', quality=90)
                print('已生成四张演示截图：' + ', '.join(path.name for path in DESTINATION.glob('*.jpg')))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
