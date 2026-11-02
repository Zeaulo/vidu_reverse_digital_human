// 礼物绑定配置；仅保存规则文本，不保存账号或通话凭据。
(() => {
  const storageKey = 'studio.gift-rules.v1'; // 浏览器本地规则草稿。
  const section = document.createElement('details'); // 不参与四步连接状态门禁。
  section.className = 'gift-rules'; section.open = true;
  section.innerHTML = '<summary>礼物绑定触发自定义指令</summary><p class="gift-help">选择礼物后配置指令。同一连击达到数量门槛时触发一次；未绑定礼物沿用普通答谢。</p><label class="gift-hidden-toggle"><input id="rule-include-hidden" type="checkbox"> 显示系统隐藏礼物及状态未知礼物</label><div id="rule-list"></div><div class="rule-buttons"><button id="rule-add" class="button button-secondary">添加礼物规则</button><button id="rule-save" class="button">保存规则</button><button id="rule-preview" class="button button-secondary">预览指令</button></div><p id="rule-status" role="status"></p><pre id="rule-preview-text"></pre>';
  panel.append(section);
  const list = section.querySelector('#rule-list'); // 所有规则编辑行。
  const status = section.querySelector('#rule-status'); // 保存及错误反馈。
  let busy = false; // 防止并发保存覆盖。
  section.querySelector('#rule-include-hidden').onchange = event => {
    const toggle = document.querySelector('#gift-include-hidden'); // 两处开关始终保持一致。
    toggle.checked = event.currentTarget.checked;
    toggle.dispatchEvent(new Event('change'));
  };

  window.giftThumbnail = row => {
    // 目录图片失效时显示占位符；所有远程文字通过 textContent 输出。
    const box = document.createElement('span'); box.className = 'gift-thumbnail'; box.textContent = '🎁';
    if (row.image && row.image.startsWith('https://')) {
      const img = document.createElement('img'); img.alt = row.name || '礼物'; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer';
      img.onerror = () => { box.textContent = '🎁'; }; img.src = row.image; box.replaceChildren(img); // 懒加载图片必须先进入 DOM 才会请求。
    }
    return box;
  };

  function addRule(rule = {}) {
    // 每行独立维护目录查询，避免异步结果写入其他规则。
    const row = document.createElement('fieldset'); row.className = 'gift-rule-row';
    row.innerHTML = '<legend>礼物规则</legend><div class="rule-top"><label><input data-key="enabled" type="checkbox" checked>启用</label><label><input data-key="thanks" type="checkbox" checked>礼物答谢</label><button type="button" class="history-clear rule-remove">删除</button></div><div class="rule-picker"><input data-key="gift_id" class="control" placeholder="礼物 ID 或名称查询" aria-label="礼物 ID 或名称"><button type="button" class="button button-secondary rule-search">查找礼物</button><span class="rule-selected"></span></div><div class="rule-results"></div><label class="rule-threshold">累计数量达到 <input data-key="min_count" type="number" min="1" max="1000000" value="1" aria-label="触发数量"> 个时触发</label><textarea data-key="instruction" class="control" rows="3" maxlength="250" aria-label="礼物自定义指令" placeholder="例如：向镜头比心，然后说祝你今天开心！"></textarea><p class="gift-help">支持 {昵称}、{礼物名称}、{数量}。勾选礼物答谢会先谢谢送礼用户，再执行指令。保存后生效。</p>';
    for (const key of ['enabled','thanks','gift_id','min_count','instruction']) {
      const input = row.querySelector('[data-key="'+key+'"]');
      if (rule[key] !== undefined) { if (input.type === 'checkbox') input.checked = rule[key]; else input.value = rule[key]; }
    }
    const input = row.querySelector('[data-key="gift_id"]'); // 查询后写入精确 ID。
    const selected = row.querySelector('.rule-selected'); // 当前选择的图片和名称。
    let sequence = 0; // 丢弃旧搜索结果。
    const label = gift => gift.is_displayed_on_panel===true ? '面板可见' : gift.is_displayed_on_panel===false ? '系统隐藏' : '状态未知';
    const select = gift => { input.value = gift.id; selected.replaceChildren(window.giftThumbnail(gift),document.createTextNode((gift.name || '未知礼物')+' · ID '+gift.id+' · '+label(gift))); };
    row.querySelector('.rule-search').onclick = async () => {
      const current = ++sequence; const results = row.querySelector('.rule-results');
      try {
        await window.studioReady;
        const data = await bridgeRequest('/api/gifts/catalog?limit=20&search='+encodeURIComponent(input.value.trim())+'&include_hidden='+document.querySelector('#gift-include-hidden').checked);
        if (current !== sequence || data.include_hidden !== document.querySelector('#gift-include-hidden').checked) return; // 开关变化后忽略旧查询。
        results.replaceChildren();
        for (const gift of data.items) {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'gift-choice';
          button.append(window.giftThumbnail(gift),document.createTextNode((gift.name || '未知礼物')+' · '+gift.id+' · '+(gift.diamond_count ?? '?')+' 钻 · '+label(gift)));
          button.onclick = () => { select(gift); results.replaceChildren(); }; results.append(button);
        }
        if (!data.items.length) results.textContent = '未找到目录记录。可直接填写真实礼物 ID，名称与图片会在采集后补全。';
      } catch (error) { status.textContent = error.message; }
    };
    row.querySelector('.rule-remove').onclick = () => { row.remove(); status.textContent = '规则已从草稿删除，请保存生效。'; };
    list.append(row);
    if (rule.gift_id) window.studioReady.then(async () => {
      const data = await bridgeRequest('/api/gifts/catalog?include_hidden=true&search='+encodeURIComponent(rule.gift_id));
      const gift = data.items.find(item => item.id === rule.gift_id);
      if (gift && input.value === rule.gift_id) select(gift);
    }).catch(() => {});
  }

  function readRules() {
    // 保存时读取完整表单，后端再做重复 ID 与范围校验。
    return [...list.children].map(row => Object.fromEntries(['enabled','thanks','gift_id','min_count','instruction'].map(key => {
      const input = row.querySelector('[data-key="'+key+'"]');
      return [key,input.type === 'checkbox' ? input.checked : key === 'min_count' ? Number(input.value) : input.value.trim()];
    })));
  }
  section.querySelector('#rule-add').onclick = () => { if (list.children.length < 100) addRule(); };
  section.querySelector('#rule-save').onclick = async () => {
    if (busy) return; busy = true; section.querySelector('#rule-save').disabled = true;
    try {
      await window.studioReady;
      const data = await bridgeRequest('/api/gifts/rules', {rules:readRules()});
      status.textContent = '已保存 '+data.rules.length+' 条规则；已变更规则的旧排队指令已取消。';
      try { localStorage.setItem(storageKey,JSON.stringify(data.rules)); } catch { status.textContent += ' 浏览器存储不可用，刷新后需重新配置。'; }
    } catch (error) { status.textContent = '保存失败：'+error.message+'。礼物 ID 必须为数字且不能重复，数量至少 1，指令不能为空。'; }
    finally { busy = false; section.querySelector('#rule-save').disabled = false; }
  };
  section.querySelector('#rule-preview').onclick = () => {
    // 预览只展示文本，不调用 Vidu，不消耗通话额度。
    section.querySelector('#rule-preview-text').textContent = readRules().map(rule => {
      const text = rule.instruction.replaceAll('{昵称}','示例观众').replaceAll('{礼物名称}','所选礼物').replaceAll('{数量}',String(rule.min_count));
      return 'ID '+rule.gift_id+'：'+(rule.thanks ? '请先说“谢谢示例观众送来的'+rule.min_count+'个所选礼物”，然后执行以下指令：' : '')+text;
    }).join(String.fromCharCode(10,10));
  };
  window.studioReady.then(async () => {
    const data = await bridgeRequest('/api/gifts/rules');
    let rules = data.rules; // 服务端已有配置优先，避免多标签页覆盖。
    if (!rules.length) {
      try { const saved = JSON.parse(localStorage.getItem(storageKey) || '[]'); if (Array.isArray(saved) && saved.length) rules = (await bridgeRequest('/api/gifts/rules',{rules:saved})).rules; }
      catch { status.textContent = '本地规则未能恢复，请重新配置并保存。'; }
    }
    for (const rule of rules) addRule(rule);
    if (!rules.length) addRule();
  }).catch(error => { status.textContent = error.message; });
})();
