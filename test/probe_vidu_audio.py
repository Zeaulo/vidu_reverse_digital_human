"""在独立 Vidu 实时通话中测试音频输入，不触碰正在直播的会话。"""
import argparse
import asyncio
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录。
sys.path.insert(0, str(ROOT))
from app.adapters.vidu_browser import ViduBrowserApi
from app.services.call_recovery import CallRecovery
from app.storage.saved_accounts import SavedAccounts

ARTIFACTS = ROOT / 'test' / 'artifacts'  # 测试材料与结果只放在 test 下。


def prepare_sample(source):
    """从原文件第 60 秒截取十秒，转成测试用 PCM，不修改原文件。"""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    sample = ARTIFACTS / 'vidu_audio_probe_sample.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', '60', '-i', str(source),
                    '-t', '10', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(sample)],
                   check=True, capture_output=True)
    return sample


async def collect(source, avatar):
    """建立一次独立会话，最多发送十秒音频，退出时清理本次资源。"""
    accounts = SavedAccounts().read()  # 加密账号仅在内存中使用。
    if len(accounts) != 1:
        return {'status': 'blocked', 'detail': '需要恰好一个未过期的本机保存账号', 'account_count': len(accounts)}
    sample = prepare_sample(source)
    sample_data = base64.b64encode(sample.read_bytes()).decode('ascii')  # 仅注入本次隔离浏览器内存。
    script = (ROOT / 'test' / 'vidu_audio_probe_init.js').read_text(encoding='utf-8')
    api = ViduBrowserApi()  # 测试独享浏览器，不复用用户当前的通话。
    call = CallRecovery(api)
    result = {'status': 'started', 'transport': '当前 Vidu 网页 RTC 麦克风输入', 'reference_seconds': 10,
              'reference_offset_seconds': 60, 'websocket_audio_sent': False}
    try:
        await api.ensure_browser()
        cookies = next(iter(accounts.values()))['cookies']  # 不输出或持久化账号信息。
        await api.context.add_cookies(cookies)
        await api.request('GET', '/iam/v1/users/me')
        api.authenticated = True
        await api.context.add_init_script(script='window.__audioProbeSample = ' + json.dumps(sample_data) + ';')
        await api.context.add_init_script(script=script)
        print('已验证本机登录态，正在创建独立测试通话。', flush=True)
        await call.start(avatar, auto_restart=False)
        for _ in range(40):  # 等待通话就绪，最多约八十秒。
            if call.status in ('connected', 'attention', 'exhausted'):
                break
            await asyncio.sleep(2)
        result['call_state'] = call.status
        if call.status != 'connected':
            result.update(status='not_ready', reason=call.reason)
            return result
        page = api.page
        # 用户已授权测试；仅匹配明确表示开启的单一按钮，不触碰其他控件。
        buttons = page.get_by_role('button', name=re.compile(r'^(开启麦克风|打开麦克风|启用麦克风|开启语音)$'))
        if await buttons.count() == 1 and await buttons.first.is_visible():
            await buttons.first.click()
            result['microphone_enable_clicked'] = True
        else:
            result['microphone_enable_clicked'] = False
        for _ in range(10):  # 等待官网申请本次测试音轨。
            if await page.evaluate('() => window.__audioProbe?.audioRequests || 0'):
                break
            await asyncio.sleep(1)
        result['audio_requests'] = await page.evaluate('() => window.__audioProbe?.audioRequests || 0')
        if not result['audio_requests']:
            result.update(status='no_audio_capture', detail='隔离会话没有调用可观察的麦克风音轨')
            return result
        result['baseline'] = await page.evaluate('() => window.__audioProbe.audioStats()')
        result['recording_started'] = await page.evaluate('() => window.__audioProbe.startRecording()')
        result['playback_started'] = await page.evaluate('() => window.__audioProbe.play()')
        peak = 0.0  # 本地音频能量峰值，不记录波形或歌词。
        for _ in range(12):
            await asyncio.sleep(1)
            peak = max(peak, await page.evaluate('() => window.__audioProbe.inputLevel()'))
        result['input_rms_peak'] = round(peak, 5)
        result['after_playback'] = await page.evaluate('() => window.__audioProbe.audioStats()')
        print('音频片段已播放，正在观察数字人的远端响应。', flush=True)
        await asyncio.sleep(12)  # 留出模型响应时间。
        result['final_stats'] = await page.evaluate('() => window.__audioProbe.audioStats()')
        result['signals'] = await page.evaluate('() => window.__audioProbe.signals')
        result['final_call_state'] = call.status
        encoded = await page.evaluate('() => window.__audioProbe.stopRecording()')
        if encoded:
            output = ARTIFACTS / 'vidu_audio_probe_response.webm'  # 仅记录远端 RTC 音轨。
            output.write_bytes(base64.b64decode(encoded))
            result['response_audio_bytes'] = output.stat().st_size
            validation = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                                         '-of','default=noprint_wrappers=1:nokey=1',str(output)],
                                        capture_output=True, text=True)
            if validation.returncode == 0:
                result['response_audio_file'] = str(output)
                result['response_audio_duration'] = validation.stdout.strip()
            else:
                output.unlink(missing_ok=True)  # 不保留损坏的录音文件。
                result['recording_warning'] = '远端录音无法解码，不能判断数字人声音内容'
        result['status'] = 'completed'
        return result
    except Exception as error:
        result.update(status='error', error_type=type(error).__name__, detail='测试未完成，请查看脱敏结果及本地服务状态')
        return result
    finally:
        try:
            await call.stop()  # 只挂断测试会话，不影响其他会话。
        except Exception:
            result['cleanup_warning'] = '测试通话停止时发生异常'
        try:
            await api.close()
        except Exception:
            result['cleanup_warning'] = '测试浏览器清理时发生异常'


def main():
    """仅在明确传入 --execute 时向 Vidu 发送音频。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--audio', type=Path, help='已获授权的本地参考音频')
    parser.add_argument('--avatar', help='本次独立测试使用的角色 ID')
    args = parser.parse_args()
    if not args.execute:
        print('未执行远端测试。使用 --execute 将创建一次独立通话并发送十秒音频。')
        return
    if not args.audio or not args.avatar:
        parser.error('--execute 需要同时提供 --audio 和 --avatar')
    result = asyncio.run(collect(args.audio, args.avatar))
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / 'vidu_audio_probe_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
