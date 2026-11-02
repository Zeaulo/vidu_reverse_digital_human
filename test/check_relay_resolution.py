"""用合成竖屏视频观察本机 WebRTC 的实际编码尺寸。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """分别采样三档参数的回读值、编码尺寸与限制原因。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.set_content('<video id="source" autoplay muted playsinline></video>')
        page.add_script_tag(path=str(Path(__file__).resolve().parent.parent / 'app/adapters/media_relay.js'))
        samples = page.evaluate('''async () => {
          const canvas=document.createElement('canvas'); canvas.width=768; canvas.height=1364;
          const context=canvas.getContext('2d'); let tick=0;
          const interval=setInterval(()=>{context.fillStyle=++tick%2?'#3a7':'#783';context.fillRect(0,0,768,1364);},100);
          const stream=canvas.captureStream(20); document.querySelector('#source').srcObject=stream;
          const receiver=new RTCPeerConnection({iceServers:[]}); receiver.addTransceiver('video',{direction:'recvonly'});
          await receiver.setLocalDescription(await receiver.createOffer());
          await new Promise(resolve=>{if(receiver.iceGatheringState==='complete')return resolve(); receiver.onicegatheringstatechange=()=>{if(receiver.iceGatheringState==='complete')resolve();};});
          await receiver.setRemoteDescription(await window.__studioMedia.answer(receiver.localDescription,'studio',100));
          const results=[];
          for(const percent of [100,80,50]) {
            const applied=await window.__studioMedia.setQuality(percent);
            await new Promise(resolve=>setTimeout(resolve,4000));
            const quality=await window.__studioMedia.quality();
            results.push({percent,applied:applied.studio,source_width:quality.source_width,source_height:quality.source_height,
              sent_width:quality.sent_width,sent_height:quality.sent_height,scale:quality.applied_scale,limitation:quality.limitation,preference:quality.degradation_preference});
          }
          clearInterval(interval); receiver.close(); window.__studioMedia.stop(); stream.getTracks().forEach(track=>track.stop());
          return results;
        }''')
        for sample in samples:
            assert sample['applied']['applied']
            assert abs(sample['scale'] - 100 / sample['percent']) < 0.01
            print(sample, flush=True)
        assert any(sample['sent_width'] for sample in samples)  # 需要确实观察到编码视频帧。
        browser.close()


if __name__ == '__main__':
    main()
