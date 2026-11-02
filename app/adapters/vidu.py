"""通过浏览器自动化连接用户已经登录的 Vidu 页面。"""


class ViduBrowserAdapter:
    """封装 Vidu 页面输入框定位，避免把页面细节散落在业务层。"""

    def __init__(self, page):
        """保存 Playwright Page 实例。"""
        self.page = page

    async def inspect(self) -> dict:
        """返回页面标题、地址和可见聊天入口，供联调和状态页使用。"""
        return {"title": await self.page.title(), "url": self.page.url, "chat_buttons": await self.page.get_by_role("button", name="聊天").count(), "editable_count": await self.page.locator("textarea, input").count()}

    async def send_message(self, message: str) -> None:
        """定位当前聊天输入框并发送消息。"""
        editor = self.page.get_by_role("textbox", name="输入自定义指令")
        await editor.fill(message)
        await self.page.get_by_role("button", name="发送").click()
