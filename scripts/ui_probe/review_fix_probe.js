async (page) => {
  // 验证对抗审查修复：#2 标档后离开视图的照片自动取消选中(删除不会删到看不见的)；#4 快速双击牌堆打开最清晰那张
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    const errors = [];
    p.on('pageerror', e => errors.push(String(e).slice(0, 200)));
    await p.goto('http://127.0.0.1:8765/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });
    const pos = (sel, i) => p.evaluate(([s, k]) => { const e = document.querySelectorAll(s)[k || 0]; const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, [sel, i]);
    const R = {};
    // #2：废片视图里选 2 张 → 按 3 标精选 → 应自动取消选中；再选 1 张按 Delete → 只删 1 张
    let c = await pos('#tier-nav [data-filter="bad"]'); await p.mouse.click(c.x, c.y);
    await p.waitForTimeout(500);
    for (const i of [0, 1]) { c = await pos('.grid .photo-card[data-id]:not(.stack-cell)', i); await p.mouse.click(c.x, c.y); await p.waitForTimeout(80); }
    R.selectedBefore = await p.evaluate(() => Number(document.getElementById('sel-num').textContent));
    await p.keyboard.press('3');
    await p.waitForTimeout(600);
    R.afterMark = await p.evaluate(() => ({ selected: document.getElementById('sel-bar').classList.contains('show') ? Number(document.getElementById('sel-num').textContent) : 0 }));
    c = await pos('.grid .photo-card[data-id]:not(.stack-cell)', 0); await p.mouse.click(c.x, c.y);
    await p.waitForTimeout(150);
    await p.keyboard.press('Delete');
    await p.waitForTimeout(300);
    R.deleteToast = await p.evaluate(() => document.querySelector('#toast span') && document.querySelector('#toast span').textContent);
    await p.evaluate(() => document.querySelector('.toast-undo') && document.querySelector('.toast-undo').click());   // 撤销删除
    await p.waitForTimeout(300);
    // 撤销刚才的标精选(把 2 张标回废片)：去精选视图全选标废片
    c = await pos('#tier-nav [data-filter="good"]'); await p.mouse.click(c.x, c.y);
    await p.waitForTimeout(500);
    await p.keyboard.press('Control+a'); await p.waitForTimeout(150); await p.keyboard.press('1'); await p.waitForTimeout(500);
    // #4：快速双击折叠堆 12 次，统计打开的是否都是封面
    c = await pos('#tier-nav [data-filter="all"]'); await p.mouse.click(c.x, c.y);
    await p.waitForTimeout(600);
    let ok = 0, wrong = 0;
    for (let k = 0; k < 12; k++) {
      const st = await p.evaluate((k) => {
        const vis = [...document.querySelectorAll('.stack-card')].filter(e => { const r = e.getBoundingClientRect(); return r.top > 150 && r.bottom < innerHeight - 20; });
        const s = vis[k % Math.min(6, vis.length)];   // 只挑完整在屏幕里的牌堆(屏幕外的点不到)
        const r = s.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, cover: s.querySelector('.photo-meta .fname').textContent };
      }, k);
      await p.mouse.dblclick(st.x, st.y, { delay: 60 });
      await p.waitForTimeout(500);
      const opened = await p.evaluate(() => document.getElementById('dp-fname').textContent);
      opened === st.cover ? ok++ : wrong++;
      await p.keyboard.press('Escape');
      await p.waitForTimeout(450);
      // 收起刚展开的那堆，下一轮还是折叠态
      await p.evaluate(() => { const b = document.querySelector('.stack-keep-star'); if (b) b.click(); });
      await p.waitForTimeout(500);
    }
    R.dblclickStack = { ok, wrong };
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
