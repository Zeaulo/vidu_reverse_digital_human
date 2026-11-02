"""模拟媒体中断与重连，验证视频区的最后一帧。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """使用画布合成视频和本地媒体替身，不创建真实 Vidu 通话。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.set_content('<main><section><div id="events"></div></section></main>')
        page.evaluate('''() => {
          window.testStatus = {state:'connected',media_connected:true,live_id:'one'};
          const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
          const ctx = canvas.getContext('2d'); let n = 0;
          setInterval(() => { ctx.fillStyle = ++n % 2 ? '#229966' : '#aa6633'; ctx.fillRect(0,0,320,180); }, 100);
          window.testStream = canvas.captureStream(15);
          window.viduRequest = async path => path === 'status' ? window.testStatus : path === 'media/answer' ? {type:'answer',sdp:'fake'} : {};
          window.RTCPeerConnection = class { // 仅模拟页面接收端信令。
            constructor() { this.iceGatheringState = 'complete'; this.connectionState = 'connected'; }
            addTransceiver() {} async createOffer() { return {type:'offer',sdp:'fake'}; }
            async setLocalDescription(value) { this.localDescription = value; }
            async setRemoteDescription() { this.ontrack({streams:[window.testStream]}); }
            async getStats() { return new Map(); }
            close() { this.connectionState = 'closed'; }
          };
        }''')
        page.add_script_tag(path=str(Path(__file__).resolve().parent.parent / 'web/assets/media.js'))
        page.wait_for_function('document.querySelector("#avatar-video").videoWidth === 320')
        page.wait_for_function('document.querySelector("#avatar-freeze").width === 320')
        page.evaluate('window.testStatus = {state:"retry_wait",media_connected:false,live_id:"one"}')
        page.wait_for_function('!document.querySelector("#avatar-freeze").hidden')
        assert '正在后台恢复' in page.locator('#media-state').inner_text()
        page.evaluate('window.testStatus = {state:"connected",media_connected:true,live_id:"two"}')
        page.wait_for_function('document.querySelector("#avatar-freeze").hidden && document.querySelector("#avatar-video").videoWidth === 320')
        page.evaluate('window.testStatus = {state:"stopped",media_connected:false}')
        page.wait_for_function('document.querySelector("#avatar-freeze").hidden && document.querySelector("#avatar-freeze").width === 0')
        browser.close()
        print('视频静态帧恢复测试通过')


if __name__ == '__main__':
    main()
