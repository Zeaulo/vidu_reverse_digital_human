"""用本地模拟对话框验证审核提示的精确处理。"""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    """只关闭匹配的审核提示，不点击其他确认按钮。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.set_content('<main></main>')
        page.evaluate('window.rejected = 0; window.__studioVidu = {moderationRejected() { window.rejected++; }}')
        page.add_script_tag(path=str(Path(__file__).resolve().parent.parent / 'app/adapters/moderation_dialog.js'))
        page.evaluate('''() => {
          document.querySelector('main').innerHTML = '<div id="other"><h2>其他提示</h2><p>请确认继续操作</p><button onclick="window.otherClicked=true">确认</button></div>' +
            '<div id="audit" role="dialog"><h2>审核未通过</h2><p>您输入的内容（文字或图片）可能违反了我们的内容政策，请修改后重试。</p><button onclick="window.auditClicked=true;this.parentElement.remove()">确认</button></div>';
        }''')
        page.wait_for_function('window.auditClicked === true')
        assert page.evaluate('window.rejected') == 1
        assert not page.evaluate('Boolean(window.otherClicked)')
        assert page.locator('#other').count() == 1
        browser.close()
        print('审核提示处理测试通过')


if __name__ == '__main__':
    main()
