// 仅在内存中转交用户已授权的 Vidu 会话，输出只包含联调结果。
async (page) => {
  const fs = require('fs'); // 读取仅供本机临时测试的随机密钥。
  const target = page.context().pages()[0]; // 已登录的官方页面。
  const cookies = (await page.context().cookies()).filter(c => c.domain.endsWith('vidu.cn'));
  const consents = await target.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([key]) => key.startsWith('live_'))));
  const avatarId = process.env.VIDU_TEST_AVATAR; // 测试者通过环境变量提供自己的角色 ID。
  if (!avatarId) throw new Error('请设置 VIDU_TEST_AVATAR');
  const response = await page.request.post('http://127.0.0.1:8796/probe', {
    headers:{'x-probe-key':fs.readFileSync('test/tools/probe-key.local','utf8')},
    data:{cookies,consents,avatar_id:avatarId},timeout:120000
  });
  return await response.json();
}
