"""通过隔离的模拟接口检查控制台按钮反馈，不触发真实账号或通话操作。"""
from playwright.sync_api import sync_playwright
from pathlib import Path


def main():
    """使用已安装的 Chrome 检查输入错误、采集停止和播放器提示。"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)  # 使用本机 Chrome。
        page = browser.new_page()
        state = {"browser_ready": False, "authenticated": False, "state": "idle", "attempts": 0, "max_attempts": 3, "media_connected": False}  # 模拟分步状态。
        sent = []  # 捕获模拟消息，确认回车不会重复发送。

        def reply(route):
            """拦截本地 API，以固定状态避免影响用户当前会话。"""
            path = route.request.url.split("/api/")[-1]  # 路由名称。
            if path == "vidu/status":
                data = state
            elif path == "vidu/browser/start":
                state["browser_ready"] = True
                data = state
            elif path == "vidu/login":
                state["authenticated"] = True
                data = {**state, "saved": True}
            elif path == "vidu/accounts":
                data = {"accounts": ["13800000000"]}
            elif path == "vidu/command":
                sent.append(route.request.post_data_json["text"])
                data = {"accepted": True}
            elif path == "vidu/media/quality/settings":
                state['relay_percent'] = route.request.post_data_json['percent']
                data = {'percent':state['relay_percent'], 'results':{}}
            elif path == "vidu/obs/link":
                data = {"token": "test-obs-token"}
            elif path == "vidu/claim":
                state.update(state="connected", media_connected=True, live_id="test")
                data = state
            elif path == "vidu/stop":
                state.update(state="stopped", media_connected=False)
                data = state
            elif path == "events":
                data = {"state": "online", "room_id": "1", "queue_size": 0, "counts": {"like": 1, "likes": 3, "enter": 1, "comment": 1}, "events": [
                    {"event_type": "comment", "nickname": "甲", "content": "较早评论", "timestamp":"2026-10-30T10:00:00Z", "delivery": "observed"},
                    {"event_type": "comment", "nickname": "甲", "content": "测试评论", "timestamp":"2026-10-30T10:01:00Z", "delivery": "observed"},
                    {"event_type": "like", "nickname": "乙", "like_count": 3, "timestamp":"2026-10-30T10:00:00Z", "delivery": "observed"},
                    {"event_type": "enter", "nickname": "丙", "timestamp":"2026-10-30T10:00:00Z", "delivery": "observed"}], "detail": ""}
            elif path == "events/export":
                data = {"room_id":"1", "events":[{"content":"测试评论"}], "counts":{"comment":1}}
            elif path == "session/room":
                route.fulfill(status=400, json={"detail": "直播间 ID 必须是数字"})
                return
            elif path == "vidu/sms":
                route.fulfill(status=400, json={"detail": "请先阅读并同意 Vidu 登录协议"})
                return
            else:
                data = {}
            route.fulfill(json=data)

        page.route("**/api/**", reply)
        page.goto("http://127.0.0.1:8795/", wait_until="domcontentloaded")
        page.locator('#events').get_by_text('测试评论').wait_for()
        assert page.locator('#history-room option').first.get_attribute('value') == '1'  # 已连接房间应保留候选。
        assert page.locator('#events .event-item').first.inner_text().find('测试评论') >= 0
        assert '2026' in page.locator('#events .event-item').first.inner_text()
        assert '乙' in page.locator('#like-events').inner_text()
        assert '丙' in page.locator('#enter-events').inner_text()
        screenshot = Path(__file__).parent / 'artifacts' / 'studio-layout.png'  # 保存模拟数据界面供视觉检查。
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)
        assert page.locator('#events').evaluate("element => element.compareDocumentPosition(document.querySelector('#enter-events')) & Node.DOCUMENT_POSITION_FOLLOWING")
        with page.expect_download() as download_info:
            page.locator('#export-events').click()
        assert download_info.value.suggested_filename.endswith('.json')
        page.locator("#save-room").click()
        page.get_by_text("操作失败：直播间 ID 必须是数字").wait_for()
        page.get_by_role("button", name="停止采集").click()
        page.get_by_text("采集已停止，待处理队列已清空；Vidu 通话不受影响。").wait_for()
        assert page.locator("#vidu-sms").is_disabled()
        page.locator("#vidu-browser").click()
        page.locator("#vidu-sms").wait_for(state="visible")
        assert not page.locator("#step-browser").evaluate("element => element.open")
        assert page.locator("#vidu-consent").is_checked()
        page.locator("#vidu-sms").click()
        page.get_by_text("操作失败：请先阅读并同意 Vidu 登录协议").wait_for()
        page.locator('#vidu-phone').fill('13800000000')
        page.locator("#vidu-login").click()
        page.locator("#vidu-claim").wait_for(state="visible")
        assert page.locator('#history-phone option').first.get_attribute('value') == '13800000000'
        page.locator('#vidu-avatar').fill('1234567890123456')
        page.locator("#vidu-claim").click()
        page.locator("#vidu-send").wait_for(state="visible")
        assert page.locator('#history-avatar option').first.get_attribute('value') == '1234567890123456'
        assert not page.locator("#step-call").evaluate("element => element.open")
        assert not page.locator("#vidu-send").is_disabled()
        page.locator('#vidu-message').fill('测试指令')
        page.locator('#vidu-message').press('Enter')
        page.get_by_text('服务端已接收指令（accepted=true），不代表语音或动作已完成。').wait_for()
        assert sent == ['测试指令']
        assert page.locator('#history-message option').first.get_attribute('value') == '测试指令'
        page.locator("#step-call summary").click()
        page.locator("#vidu-stop").click()
        page.get_by_text("连接已断开，可以输入新角色 ID；自动恢复已取消。").wait_for()
        page.locator('#clear-avatar-history').click()
        assert page.locator('#history-avatar option').count() == 0
        page.locator("#media-sound").click()
        page.get_by_text("已开启声音，等待通话媒体连接。").wait_for()
        page.locator("#media-retry").click()
        page.get_by_text("已请求重新连接；有可用通话媒体后开始协商。").wait_for()
        page.locator('#relay-percent').select_option('80')
        page.get_by_text('转发目标已保存，连接视频后生效。').wait_for()
        assert state['relay_percent'] == 80
        page.locator('#obs-regenerate').click()
        page.get_by_text('新链接已生成，旧链接已失效。').wait_for()
        assert page.locator('#obs-url').input_value().endswith('/obs#test-obs-token')
        page.locator('#obs-revoke').click()
        page.get_by_text('OBS 链接已撤销。').wait_for()
        assert page.locator('#obs-url').is_hidden()
        assert page.locator("#vidu-send").is_disabled()  # 断开后应重新禁用发送。
        assert "发送不可用" in page.locator("#vidu-send-hint").text_content()
        page.reload(wait_until='domcontentloaded')
        assert page.locator('#history-phone option').first.get_attribute('value') == '13800000000'  # 刷新后手机号保留。
        assert page.locator('#history-avatar option').count() == 0  # 已清除的角色历史不会恢复。
        assert page.locator('#history-room option').first.get_attribute('value') == '1'
        page.locator('#clear-room-history').click()
        assert page.locator('#history-room option').count() == 0
        browser.close()
        print("界面反馈检查通过")


if __name__ == "__main__":
    main()
