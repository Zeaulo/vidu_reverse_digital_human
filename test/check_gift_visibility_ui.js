async (page) => {
  // 用同名礼物检查默认过滤、双开关同步和规则搜索标识。
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.locator('#gift-search').fill('小心心');
  await page.locator('#gift-query').click();
  await page.locator('#gift-catalog').getByText('463', {exact:true}).waitFor();
  if (await page.locator('#gift-catalog').getByText('15012', {exact:true}).count()) throw new Error('默认显示了隐藏 ID');
  await page.locator('#gift-include-hidden').check();
  await page.locator('#gift-catalog').getByText('15012', {exact:true}).waitFor();
  if (!await page.locator('#rule-include-hidden').isChecked()) throw new Error('规则开关未同步');
  const hiddenRow = page.locator('#gift-catalog tr').filter({hasText:'15012'});
  if (!(await hiddenRow.innerText()).includes('系统隐藏')) throw new Error('隐藏标识缺失');
  await page.locator('#rule-include-hidden').uncheck();
  if (await page.locator('#gift-include-hidden').isChecked()) throw new Error('目录开关未同步');
  await page.locator('[data-key="gift_id"]').first().fill('小心心');
  await page.locator('.rule-search').first().click();
  await page.locator('.gift-choice').filter({hasText:'463'}).waitFor();
  if (await page.locator('.gift-choice').filter({hasText:'15012'}).count()) throw new Error('规则搜索默认显示隐藏 ID');
  await page.locator('#rule-include-hidden').check();
  await page.locator('.rule-search').first().click();
  await page.locator('.gift-choice').filter({hasText:'15012'}).waitFor();
  if (!(await page.locator('.gift-choice').filter({hasText:'15012'}).innerText()).includes('系统隐藏')) throw new Error('规则选项缺少隐藏标识');
  if (errors.length) throw new Error(errors.join(';'));
  await page.locator('#rule-include-hidden').uncheck();
  if (await page.locator('.gift-choice').count()) throw new Error('切换后旧查询结果未清除');
  console.log('可见性界面测试通过');
}
