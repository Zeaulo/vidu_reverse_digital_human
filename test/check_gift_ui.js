async (page) => {
  // 有头浏览器验证配置流程；不创建通话、不向外部发送指令。
  const errors = []; page.on('pageerror',error => errors.push(error.message));
  await page.getByLabel('礼物 ID 或名称',{exact:true}).fill('2001');
  await page.getByRole('button',{name:'查找礼物',exact:true}).click();
  await page.locator('.gift-choice').filter({hasText:'2001'}).click();
  await page.getByLabel('礼物自定义指令',{exact:true}).fill('向{昵称}比心，再说收到{数量}个{礼物名称}');
  if (!await page.getByLabel('礼物答谢',{exact:true}).isChecked()) throw new Error('答谢未默认勾选');
  await page.getByRole('button',{name:'保存规则',exact:true}).click();
  await page.locator('#rule-status').filter({hasText:'已保存 1 条规则'}).waitFor();
  await page.getByRole('button',{name:'预览指令',exact:true}).click();
  if (!(await page.locator('#rule-preview-text').innerText()).includes('请先说“谢谢示例观众送来的1个所选礼物”，然后：向示例观众比心')) throw new Error('预览答谢模板不正确');
  await page.getByLabel('欢迎进入直播间',{exact:true}).check();
  await page.waitForFunction(() => !document.querySelector('#auto-enter').disabled);
  await page.getByLabel('回复弹幕',{exact:true}).uncheck();
  await page.waitForFunction(() => !document.querySelector('#auto-comment').disabled);
  await page.reload();
  await page.getByLabel('礼物自定义指令',{exact:true}).waitFor();
  if (!(await page.getByLabel('礼物自定义指令',{exact:true}).inputValue()).includes('比心')) throw new Error('刷新未恢复规则');
  if (!await page.getByLabel('欢迎进入直播间',{exact:true}).isChecked()) throw new Error('欢迎状态丢失');
  if (await page.getByLabel('回复弹幕',{exact:true}).isChecked()) throw new Error('回复状态丢失');
  await page.locator('.rule-selected img').waitFor();
  await page.waitForFunction(() => document.querySelector('.rule-selected img')?.naturalWidth > 0); // 验证图片确实解码成功。
  await page.locator('.gift-rules').screenshot({path:'D:/Project/abow_nstomeouu/vidu_reverse_digital_human/test/artifacts/gift-rules-v015.png'});
  if (errors.length) throw new Error(errors.join(';'));
  // 恢复测试开关默认值，并清理测试规则，防止之后接通真实通话时误触发。
  await page.evaluate(async () => {
    await bridgeRequest('/api/session/automation',{enter:false,like:false,comment:true});
    await bridgeRequest('/api/gifts/rules',{rules:[]}); localStorage.removeItem('studio.gift-rules.v1');
  });
  console.log('UI：保存、预览、图片、刷新恢复、独立开关均通过，测试规则已清理。');
}
