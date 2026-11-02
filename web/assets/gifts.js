// 礼物目录、聚合记录和发送结果独立展示，所有外部字段按文本渲染。
const giftPanel = document.createElement('section'); // 独立功能区。
giftPanel.className = 'glass rounded-3xl p-8 mt-6';
giftPanel.innerHTML = '<h2 class="text-xl">礼物采集与目录</h2><p id="gift-metrics" class="mt-4 text-cyan-200"></p><p class="mt-2 text-sm text-slate-400">原始消息、连击组和本次新增数量分别统计。Vidu 接受不等于已经播报完成。</p><div id="gift-records" class="mt-4 space-y-2" style="max-height:300px;overflow:auto"></div><div class="flex flex-wrap gap-3 mt-6"><input id="gift-search" class="control" placeholder="按礼物 ID 或名称查询" aria-label="礼物查询"><button id="gift-query" class="button">查询礼物</button><button id="gift-refresh" class="button">刷新当前房间目录</button></div><p id="gift-catalog-status" class="mt-3 text-sm"></p><div class="overflow-auto mt-3"><table class="w-full text-left text-sm"><thead><tr><th>图片</th><th>ID</th><th>名称</th><th>单价（钻）</th><th>来源</th><th>更新时间</th></tr></thead><tbody id="gift-catalog"></tbody></table></div><div class="flex gap-3 mt-3"><button id="gift-prev" class="button">上一页</button><button id="gift-next" class="button">下一页</button></div>';
document.querySelector('main').append(giftPanel);
const giftElement = name => document.querySelector('#gift-'+name); // 局部元素入口。
const giftLabels = {rule_skipped:'未达门槛或本组已触发',collecting:'连击中',ended:'连击结束',single:'单次赠送',timeout:'超时暂结',late_delta:'迟到增量',unverified:'待核实',stopped_unsettled:'停止时未结算',capacity_rejected:'聚合容量不足',queued:'已入队',sending:'等待回执',accepted:'Vidu 已接受',unknown:'发送结果未知',expired:'过期未播报',dropped:'队列淘汰',stopped_unsent:'停止时未播报',filtered:'规则过滤'};
const giftSources = {historical_snapshot:'历史快照',room_catalog:'当前房间目录',event:'消息元数据',mixed_reference:'消息与目录补全'};
let giftOffset = 0; // 每页五十条，搜索时重置。
let giftQuerySequence = 0; // 丢弃过时搜索结果。

async function queryGiftCatalog() {
  // 按 ID 或名称查询；分页不假设名称唯一。
  const sequence = ++giftQuerySequence;
  try {
    await window.studioReady;
    const data = await bridgeRequest('/api/gifts/catalog?search='+encodeURIComponent(giftElement('search').value)+'&offset='+giftOffset);
    if(sequence !== giftQuerySequence) return;
    giftElement('catalog-status').textContent = '匹配 '+data.total+' 条 · 当前房间 '+(data.room_id||'未选择')+' · '+(data.cache_fresh?'房间目录缓存有效':'历史快照仅供参考')+(data.error?' · '+data.error:'');
    giftElement('catalog').replaceChildren();
    for(const row of data.items) {
      const tr = document.createElement('tr');
      const imageCell = document.createElement('td'); imageCell.append(window.giftThumbnail(row)); tr.append(imageCell); // 目录图片独立展示。
      for(const value of [row.id,row.name||'名称未知',row.diamond_count??'未知',giftSources[row.source]||row.source,row.updated_at]) {
        const td = document.createElement('td'); td.className='py-2 pr-3'; td.textContent=value; tr.append(td);
      }
      giftElement('catalog').append(tr);
    }
    giftElement('prev').disabled = giftOffset===0;
    giftElement('next').disabled = giftOffset+50>=data.total;
  } catch(error) {giftElement('catalog-status').textContent=error.message;}
}

async function refreshGiftStatus() {
  // 聚合记录与回执记录保留独立状态，未确认数量不显示总价。
  try {
    await window.studioReady;
    const data = await bridgeRequest('/api/gifts/status');
    const count = data.counts;
    giftElement('metrics').textContent='原始包 '+(count.raw_messages||0)+' · 重复包 '+(count.duplicates||0)+' · 赠送组 '+(count.groups||0)+' · 已结算数量 '+(count.quantity||0)+' · 已知钻石小计 '+(count.known_diamonds||0)+' · 缺实时单价数量 '+(count.unpriced_quantity||0)+' · 入队 '+(data.dispatch?.gift_queued||0)+' · 已发 '+(data.dispatch?.gift_sent||0)+' · Vidu 接受 '+(data.dispatch?.gift_accepted||0);
    giftElement('records').replaceChildren();
    const rows = [...data.records.slice(-15).map(row=>({text:(row.nickname||'赠送者信息缺失')+' → '+(row.recipient_name||row.recipient_id||'接收者未知')+' · '+(row.name||'未知礼物')+'（ID '+(row.gift_id||'未知')+'） · 累计 '+(row.quantity??'待核实')+' · 单价 '+(row.diamond_count??'未知')+' 钻'+(row.price_source==='catalog_reference'?'（参考）':'')+' · '+(giftLabels[row.status]||row.status)+(row.issues.length?' · '+row.issues.join(' / '):'')})),...data.deliveries.slice(-15).map(row=>({text:'播报记录 · '+(row.gift_name||'未知礼物')+'（ID '+row.gift_id+'）新增 '+row.gift_count+' · '+(giftLabels[row.settlement]||row.settlement)+' · '+(giftLabels[row.delivery]||row.delivery)}))];
    for(const row of rows) {const p=document.createElement('p');p.className='rounded-xl bg-white/5 p-3 text-sm';p.textContent=row.text;giftElement('records').append(p);}
  } catch(error) {giftElement('metrics').textContent=error.message;}
  finally {setTimeout(refreshGiftStatus,2000);}
}
giftElement('query').onclick=()=>{giftOffset=0;queryGiftCatalog();};
giftElement('search').onkeydown=event=>{if(event.key==='Enter'){giftOffset=0;queryGiftCatalog();}};
giftElement('prev').onclick=()=>{giftOffset=Math.max(0,giftOffset-50);queryGiftCatalog();};
giftElement('next').onclick=()=>{giftOffset+=50;queryGiftCatalog();};
giftElement('refresh').onclick=async()=>{
  giftElement('refresh').disabled=true;giftElement('catalog-status').textContent='正在用访客浏览器读取当前房间目录…';
  try {await bridgeRequest('/api/gifts/refresh',{});giftOffset=0;await queryGiftCatalog();}
  catch(error){giftElement('catalog-status').textContent=error.message;}
  finally{giftElement('refresh').disabled=false;}
};
queryGiftCatalog();refreshGiftStatus();
