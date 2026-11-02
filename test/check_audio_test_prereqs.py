"""检查本机音频测试条件，不展示账号或登录凭据。"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 从项目根目录导入本地模块。
from app.storage.saved_accounts import SavedAccounts


def main():
    """仅输出参考音频格式和可用加密账号数量。"""
    parser = argparse.ArgumentParser(description='检查指定本地音频及保存账号状态')
    parser.add_argument('audio', type=Path, help='参考音频文件路径')
    source = parser.parse_args().audio  # 用户自行指定参考音频路径。
    metadata = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size:stream=codec_name,sample_rate,channels', '-of', 'json', str(source)],
        capture_output=True, text=True, encoding='utf-8', check=True)  # 不读取或打印歌词。
    try:
        count = len(SavedAccounts().read())  # 不输出手机号或 Cookie。
        account_error = None
    except Exception:
        count = 0
        account_error = '本机保存账号不可读'
    print(json.dumps({'audio': json.loads(metadata.stdout), 'saved_account_count': count,
                      'account_error': account_error}, ensure_ascii=False))


if __name__ == '__main__':
    main()
