"""将抖音目录的面板可见性字段写入公开礼物基线。"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]  # 当前项目根目录。
baseline_path = root/'data/gifts/baseline-2026-11-02.json'  # 已脱敏目录基线。
visibility_path = root/'test/artifacts/gift-visibility.json'  # 浏览器公开响应导出。
baseline = json.loads(baseline_path.read_text(encoding='utf-8-sig'))
visibility = json.loads(visibility_path.read_text(encoding='utf-8'))
missing = []  # 记录导出中缺失的 ID，避免静默默认可见。
for row in baseline['gifts']:
    item = visibility.get(row['id'])
    if item is None:
        missing.append(row['id'])
        row['is_displayed_on_panel'] = False
        row['visibility_source'] = 'not_in_current_catalog'
    else:
        row.update(item)
baseline['visibility_summary'] = {
    'field': 'is_displayed_on_panel',
    'visible': sum(1 for row in baseline['gifts'] if row['is_displayed_on_panel']),
    'hidden': sum(1 for row in baseline['gifts'] if not row['is_displayed_on_panel']),
    'missing_from_current_response': len(missing),
}
baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2)+chr(10), encoding='utf-8')
print(json.dumps(baseline['visibility_summary'], ensure_ascii=False))
