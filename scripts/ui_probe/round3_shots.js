async (page) => {
  // 第三轮截图：液态玻璃选择栏、文件夹左滑胶囊(未过/已过 50%)、切换密度的滑动过渡(中途)、一键全选下拉在吸顶组头之上
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', ignoreDefaultArgs: ['--hide-scrollbars'] });
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  const R = {};
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    const errors = [];
    p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
    await p.goto('http://127.0.0.1:8765/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 30000 });
    await p.evaluate(() => { const b = document.querySelector('#density-toggle [data-density="comfortable"]'); if (!b.classList.contains('active')) b.click(); });
    await p.waitForTimeout(900);
    // 选中 3 张 → 液态玻璃选择栏
    for (const i of [0, 1, 2]) {
      const c = await p.evaluate(k => { const cards = [...document.querySelectorAll('.grid .photo-card[data-id]:not(.stack-cell)')].filter(e => { const r = e.getBoundingClientRect(); return r.top > 150 && r.bottom < 700; }); const r = cards[k].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, i);
      await p.mouse.click(c.x, c.y); await p.waitForTimeout(150);
    }
    await p.waitForTimeout(700);
    await p.screenshot({ path: dir + 'r3_selbar.png', clip: { x: 420, y: 760, width: 800, height: 140 } });
    await p.keyboard.press('Escape');
    // 一键全选下拉：滚动让组头吸住，再打开下拉
    await p.evaluate(() => { document.querySelector('#content').scrollTop = 600; });
    await p.waitForTimeout(400);
    await p.click('#btn-select-all-caret'); await p.waitForTimeout(500);
    R.menuOnTop = await p.evaluate(() => { const m = document.querySelector('#select-all-menu'); const r = m.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.bottom - 8); return !!(e && e.closest('#select-all-menu')); });
    await p.screenshot({ path: dir + 'r3_menu.png', clip: { x: 900, y: 30, width: 500, height: 200 } });
    await p.keyboard.press('Escape'); await p.mouse.click(700, 15); await p.waitForTimeout(300);
    // 文件夹左滑：30%(小胶囊) 与 70%(涨满+桶盖开)
    const f = await p.evaluate(() => { const r = document.querySelector('.folder-swipe .folder-row'); const b = r.getBoundingClientRect(); return { x: b.right - 12, y: b.top + b.height / 2, w: b.width }; });
    await p.mouse.move(f.x, f.y); await p.mouse.down();
    for (let i = 1; i <= 8; i++) { await p.mouse.move(f.x - f.w * 0.3 * i / 8, f.y); await p.waitForTimeout(16); }
    await p.waitForTimeout(500);
    R.pillSmall = await p.evaluate(() => { const pl = document.querySelector('.folder-swipe-pill'); return { w: Math.round(pl.getBoundingClientRect().width), armed: pl.parentElement.classList.contains('armed') }; });
    await p.screenshot({ path: dir + 'r3_pill_small.png', clip: { x: 0, y: 220, width: 230, height: 120 } });
    for (let i = 1; i <= 8; i++) { await p.mouse.move(f.x - f.w * (0.3 + 0.4 * i / 8), f.y); await p.waitForTimeout(16); }
    await p.waitForTimeout(600);
    R.pillArmed = await p.evaluate(() => { const pl = document.querySelector('.folder-swipe-pill'); return { w: Math.round(pl.getBoundingClientRect().width), armed: pl.parentElement.classList.contains('armed') }; });
    await p.screenshot({ path: dir + 'r3_pill_armed.png', clip: { x: 0, y: 220, width: 230, height: 120 } });
    // 退回 20% 再松手：弹回，不删除
    for (let i = 1; i <= 8; i++) { await p.mouse.move(f.x - f.w * (0.7 - 0.5 * i / 8), f.y); await p.waitForTimeout(16); }
    await p.mouse.up(); await p.waitForTimeout(900);
    R.afterRelease = await p.evaluate(() => ({ folders: document.querySelectorAll('.folder-swipe').length, x: getComputedStyle(document.querySelector('.folder-swipe .folder-row')).transform, pillW: Math.round(document.querySelector('.folder-swipe-pill').getBoundingClientRect().width) }));
    // 切换密度：标准 → 大图，过渡中途截图
    await p.evaluate(() => { document.querySelector('#content').scrollTop = 0; });
    await p.waitForTimeout(300);
    const big = await p.evaluate(() => { const r = document.querySelector('#density-toggle [data-density="large"]').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await p.mouse.click(big.x, big.y);
    await p.waitForTimeout(120);
    R.vt = await p.evaluate(() => document.documentElement.dataset.vt || null);
    await p.screenshot({ path: dir + 'r3_vt_mid.png' });
    await p.waitForTimeout(900);
    R.afterVt = await p.evaluate(() => ({ density: document.documentElement.getAttribute('data-density'), vt: document.documentElement.dataset.vt || null }));
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
