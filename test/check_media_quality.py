"""使用本地合成视频验证 WebRTC 转发，不连接真实 Vidu。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """连接本地合成轨道，核对播放尺寸与脱敏质量统计。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.set_content('<video id="source" autoplay muted playsinline></video>')
        page.add_script_tag(path=str(Path(__file__).resolve().parent.parent / 'app/adapters/media_relay.js'))
        result = page.evaluate('''async () => {
          const canvas = document.createElement('canvas'); // 模拟固定尺寸视频源。
          canvas.width = 640; canvas.height = 360;
          const context = canvas.getContext('2d'); context.fillStyle = '#34aa77'; context.fillRect(0,0,640,360);
          const stream = canvas.captureStream(15); document.querySelector('#source').srcObject = stream;
          const receiver = new RTCPeerConnection({iceServers:[]}); // 本地接收端。
          receiver.addTransceiver('video', {direction:'recvonly'});
          let receivedTrack;
          receiver.ontrack = event => { receivedTrack = event.track; };
          await receiver.setLocalDescription(await receiver.createOffer());
          await new Promise(resolve => { if (receiver.iceGatheringState === 'complete') return resolve(); receiver.onicegatheringstatechange = () => { if (receiver.iceGatheringState === 'complete') resolve(); }; });
          const answer = await window.__studioMedia.answer(receiver.localDescription);
          await receiver.setRemoteDescription(answer);
          await new Promise((resolve, reject) => { const end = Date.now()+8000; const timer = setInterval(() => { context.fillRect(0,0,640,360); if (receivedTrack && receiver.connectionState === 'connected') { clearInterval(timer); resolve(); } else if (Date.now() > end) { clearInterval(timer); reject(new Error('本机媒体未连接')); } }, 100); });
          const quality = await window.__studioMedia.quality();
          receiver.close(); window.__studioMedia.stop(); stream.getTracks().forEach(track => track.stop());
          return quality;
        }''')
        assert result['source_width'] == 640 and result['source_height'] == 360
        assert result['tuning']
        print('本地媒体转发测试通过：', result['source_width'], 'x', result['source_height'], result['tuning'])
        browser.close()


if __name__ == '__main__':
    main()
