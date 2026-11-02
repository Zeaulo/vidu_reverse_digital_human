"""用合成媒体验证控制台与 OBS 可并行接收。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """独立替换 OBS 接收端不能中断控制台接收端。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.set_content('<video id="source" autoplay muted playsinline></video>')
        page.add_script_tag(path=str(Path(__file__).resolve().parent.parent / 'app/adapters/media_relay.js'))
        result = page.evaluate('''async () => {
          const canvas = document.createElement('canvas'); canvas.width=320; canvas.height=180;
          const ctx=canvas.getContext('2d'); ctx.fillStyle='#44aa77'; ctx.fillRect(0,0,320,180);
          const stream=canvas.captureStream(15); // 合成音频也进入中转轨道。
          const audio=new AudioContext(); const oscillator=audio.createOscillator(); const destination=audio.createMediaStreamDestination(); oscillator.connect(destination); oscillator.start();
          stream.addTrack(destination.stream.getAudioTracks()[0]); document.querySelector('#source').srcObject=stream;
          const timer=setInterval(() => ctx.fillRect(0,0,320,180),100);
          async function receiver(target) {
            const peer=new RTCPeerConnection({iceServers:[]}); peer.kinds=[];
            peer.ontrack=event => peer.kinds.push(event.track.kind);
            peer.addTransceiver('video',{direction:'recvonly'});
            peer.addTransceiver('audio',{direction:'recvonly'});
            await peer.setLocalDescription(await peer.createOffer());
            await new Promise(resolve => { if(peer.iceGatheringState==='complete') return resolve(); peer.onicegatheringstatechange=()=>{if(peer.iceGatheringState==='complete')resolve();}; });
            const answer=await window.__studioMedia.answer(peer.localDescription,target);
            await peer.setRemoteDescription(answer);
            return peer;
          }
          const studio=await receiver('studio'); const obs=await receiver('obs');
          await new Promise((resolve,reject)=>{const end=Date.now()+10000; const timer=setInterval(()=>{if(studio.connectionState==='connected' && obs.connectionState==='connected'){clearInterval(timer);resolve();}else if(Date.now()>end){clearInterval(timer);reject(new Error('媒体连接失败'));}},100);});
          const replacement=await receiver('obs');
          await new Promise((resolve,reject)=>{const end=Date.now()+10000;const timer=setInterval(()=>{if(replacement.connectionState==='connected'){clearInterval(timer);resolve();}else if(Date.now()>end){clearInterval(timer);reject(new Error('OBS 重连失败'));}},100);});
          const configured=[]; // 三档比例必须同时写入两个发送端。
          for (const percent of [50,80,100]) {
            const applied=await window.__studioMedia.setQuality(percent);
            const info=await window.__studioMedia.quality();
            configured.push({percent, studio:applied.studio?.applied, obs:applied.obs?.applied, studioScale:info.applied_scale, obsScale:info.obs_scale});
          }
          const states={studio:studio.connectionState, obs:replacement.connectionState, studioTracks:studio.kinds.sort().join(','), obsTracks:replacement.kinds.sort().join(',')};
          clearInterval(timer); studio.close(); obs.close(); replacement.close(); window.__studioMedia.stop(); stream.getTracks().forEach(track=>track.stop()); oscillator.stop(); await audio.close();
          return {states,configured};
        }''')
        assert result['states'] == {'studio':'connected', 'obs':'connected', 'studioTracks':'audio,video', 'obsTracks':'audio,video'}
        for item in result['configured']:
            assert item['studio'] and item['obs']
            assert abs(item['studioScale'] - 100/item['percent']) < 0.01
            assert abs(item['obsScale'] - 100/item['percent']) < 0.01
        browser.close()
        print('OBS 与控制台并行媒体测试通过')


if __name__ == '__main__':
    main()
