// 仅关闭明确的 Vidu 审核拒绝提示，不干预审核或其他确认对话框。
(() => {
  if (window.__studioModerationObserver) return;
  const handled = new WeakSet(); // 避免同一个提示重复点击。
  function inspect() {
    // 先精确找到审核标题，再沿父节点寻找完整提示和唯一的确认按钮。
    for (const title of document.querySelectorAll('h1,h2,h3,h4,[role="heading"],div,span,p')) {
      if (title.children.length || title.textContent.trim() !== '审核未通过') continue;
      let box = title.parentElement; // 当前候选对话容器。
      for (let depth = 0; box && box !== document.body && depth < 8; depth++, box = box.parentElement) {
        const content = box.innerText || ''; // 确认是用户提供的完整内容政策提示。
        if (!content.includes('您输入的内容') || !content.includes('可能违反了我们的内容政策') || !content.includes('请修改后重试')) continue;
        const buttons = [...box.querySelectorAll('button,[role="button"]')].filter(button => button.textContent.trim() === '确认' && button.getClientRects().length);
        if (content.length > 2000 || buttons.length !== 1 || handled.has(box)) break;
        handled.add(box);
        window.__studioVidu?.moderationRejected(); // 先记录拒绝，再关闭提示。
        buttons[0].click();
        break;
      }
    }
  }
  const observer = new MutationObserver(inspect); // 监听动态生成的提示框。
  window.__studioModerationObserver = observer;
  function begin() { observer.observe(document.documentElement, {childList:true, subtree:true, characterData:true}); inspect(); }
  if (document.documentElement) begin(); else document.addEventListener('DOMContentLoaded', begin, {once:true});
})();
