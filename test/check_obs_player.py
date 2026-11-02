"""隔离模拟 OBS 浏览器源播放、重连与令牌失效。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """用合成视频和本地路由模拟服务，不连接真实直播。"""
    root = Path(__file__).resolve().parent.parent
    state = {'state':'connected', 'media_connected':True, 'live_id':'one'}
    tokens = []  # 记录请求头，核对凭证没有放入请求 URL。
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        page = browser.new_page()
        page.add_init_script('''(() => {
          const canvas=document.createElement('canvas'); canvas.width=320; canvas.height=180;
          const ctx=canvas.getContext('2d'); let frame=0;
          setInterval(()=>{ctx.fillStyle=++frame%2?'#229966':'#aa6633';ctx.fillRect(0,0,320,180);},100);
          const stream=canvas.captureStream(15);
          window.RTCPeerConnection=class {
            constructor(){this.iceGatheringState='complete';this.connectionState='connected';}
            addTransceiver(){} async createOffer(){return {type:'offer',sdp:'fake'};}
            async setLocalDescription(value){this.localDescription=value;}
            async setRemoteDescription(){this.ontrack({streams:[stream]});}
            close(){this.connectionState='closed';}
          };
        })()''')
        def handle(route):
            """提供本地页面与模拟状态，检查令牌不会出现在 URL 中。"""
            url = route.request.url
            if '/api/obs/' in url:
                assert 'fake-secret' not in url
                tokens.append(route.request.headers.get('x-obs-token'))
                if state.get('revoked'):
                    route.fulfill(status=401, json={'detail':'OBS 链接无效'})
                elif '/status' in url:
                    route.fulfill(json=state)
                else:
                    route.fulfill(json={'type':'answer','sdp':'fake'})
            elif url.endswith('/obs'):
                route.fulfill(content_type='text/html', body=(root / 'web/obs.html').read_text(encoding='utf-8'))
            elif url.endswith('/assets/obs_player.js'):
                route.fulfill(content_type='application/javascript', body=(root / 'web/assets/obs_player.js').read_text(encoding='utf-8'))
            else:
                route.fulfill(content_type='text/css', body='')
        page.route('**/*', handle)
        page.goto('http://obs.test/obs#fake-secret')
        page.wait_for_function('document.querySelector("#freeze").width === 320')
        state.update(state='retry_wait', media_connected=False)
        page.wait_for_function('!document.querySelector("#freeze").hidden')
        state.update(state='connected', media_connected=True, live_id='two')
        page.wait_for_function('document.querySelector("#freeze").hidden && document.querySelector("#video").videoWidth === 320')
        state['revoked'] = True
        page.get_by_text('OBS 链接无效').wait_for()
        assert tokens and all(token == 'fake-secret' for token in tokens)
        browser.close()
        print('OBS 播放页重连与令牌测试通过')


if __name__ == '__main__':
    main()
