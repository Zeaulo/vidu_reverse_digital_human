"""使用本机已有语音识别模型检查远端测试录音，不上传音频。"""
from pathlib import Path
import json
import os
from tempfile import TemporaryDirectory
from faster_whisper import WhisperModel


def main():
    """显示带时间的识别片段，供判断数字人是否有语音回应。"""
    audio = Path(__file__).resolve().parent / 'artifacts' / 'vidu_audio_probe_response.mp3'  # 仅分析远端录音。
    cache = Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub' / 'models--Systran--faster-whisper-base'  # 仅读取现有模型缓存。
    tree = next((cache / 'trees').glob('*'))
    files = json.loads(tree.read_text(encoding='utf-8'))['files']
    with TemporaryDirectory(dir=audio.parent) as temporary:
        model_dir = Path(temporary)  # 模型快照缺少链接时，在测试目录建立临时硬链接。
        for name in ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'):
            info = files[name]
            os.link(cache / 'blobs' / info.get('lfs_sha256', info['blob_id']), model_dir / name)
        model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        segments, info = model.transcribe(str(audio), language='zh', beam_size=3, vad_filter=True)
        print('检测语言:', info.language)
        for segment in segments:  # 时间戳用于区分输入期间及结束后的回应。
            print(f'{segment.start:.1f}-{segment.end:.1f}: {segment.text.strip()}')


if __name__ == '__main__':
    main()
