// 仅返回业务信令类型，不返回原始消息和凭据。
async (page) => {
  return await page.evaluate(() => ({
    signals: (window.__viduWsLog || []).map(item => {
      // 只提取经过允许的布尔状态和消息类型。
      try {
        const frame = JSON.parse(item.data);
        return {kind:item.kind, type:frame.type, accepted:frame.payload?.text_input_ack?.accepted};
      } catch { return {kind:item.kind}; }
    }).slice(-30)
  }));
}