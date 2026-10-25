async (page) => {
  // 第二轮改动截图：吸顶组头、选择栏、拖动时的日期标签、迷你密度、文件夹左滑、深色模式
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', ignoreDefaultArgs: ['--hide-scrollbars'] });
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  const R = {};
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    const errors = [];
    p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
    await p.goto('http://127.0.0.1:8766/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 30000 });
    await p.evaluate(() => { const b = document.querySelector('#density-toggle [data-density="comfortable"]'); if (!b.classList.contains('active')) b.click(); });
    await p.waitForTimeout(800);
    await p.screenshot({ path: dir + 'r2_top.png', clip: { x: 220, y: 0, width: 1180, height: 260 } });
    // 往下滚一段：组头吸住
    await p.evaluate(() => { document.querySelector('#content').scrollTop = 1500; });
    await p.waitForTimeout(700);
    R.stuck = await p.evaluate(() => {
      const h = document.querySelector('.group-header.is-stuck');
      const c = document.querySelector('#content').getBoundingClientRect();
      return h ? { top: Math.round(h.getBoundingClientRect().top - c.top), n: document.querySelectorAll('.group-header.is-stuck').length } : null;
    });
    await p.screenshot({ path: dir + 'r2_stuck.png', clip: { x: 220, y: 0, width: 1180, height: 260 } });
    // 选中 3 张：底部深色选择栏
    for (const i of [0, 1, 2]) {
      const c = await p.evaluate(k => { const cards = [...document.querySelectorAll('.grid .photo-card[data-id]:not(.stack-cell)')].filter(e => { const r = e.getBoundingClientRect(); return r.top > 150 && r.bottom < 800; }); const r = cards[k].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, i);
      await p.mouse.click(c.x, c.y); await p.waitForTimeout(120);
    }
    await p.waitForTimeout(600);
    await p.screenshot({ path: dir + 'r2_selbar.png', clip: { x: 220, y: 560, width: 1180, height: 340 } });
    await p.keyboard.press('Escape');
    // 拖滚动条：日期标签
    const g = await p.evaluate(() => { const c = document.querySelector('#content'); const r = c.getBoundingClientRect(); const th = Math.max(44, c.clientHeight * c.clientHeight / c.scrollHeight); return { x: r.right - 7, y: r.top + c.scrollTop / (c.scrollHeight - c.clientHeight) * (c.clientHeight - th) + th / 2 }; });
    await p.mouse.move(g.x, g.y); await p.mouse.down();
    for (let i = 1; i <= 20; i++) { await p.mouse.move(g.x, g.y + i * 12); await p.waitForTimeout(20); }
    await p.waitForTimeout(250);
    R.scrub = await p.evaluate(() => { const s = document.querySelector('.sg-scrub'); return { show: s.classList.contains('show'), text: s.textContent }; });
    await p.screenshot({ path: dir + 'r2_scrub.png', clip: { x: 900, y: 60, width: 500, height: 840 } });
    await p.mouse.up();
    await p.waitForTimeout(900);
    R.scrubHidden = await p.evaluate(() => !document.querySelector('.sg-scrub').classList.contains('show'));
    // 迷你密度(Ctrl+滚轮缩小两级)
    await p.mouse.move(700, 500);
    await p.keyboard.down('Control');
    await p.mouse.wheel(0, 120); await p.waitForTimeout(700);
    await p.mouse.wheel(0, 120); await p.waitForTimeout(700);
    await p.keyboard.up('Control');
    R.densityAfterZoomOut = await p.evaluate(() => document.documentElement.getAttribute('data-density'));
    await p.waitForTimeout(1500);
    R.miniThumbs = await p.evaluate(() => { const t = [...document.querySelectorAll('.photo-thumb.is-loaded')].slice(0, 3).map(n => n._painted); return t; });
    await p.screenshot({ path: dir + 'r2_mini.png' });
    await p.keyboard.press('Control+='); await p.waitForTimeout(500);
    await p.keyboard.press('Control+='); await p.waitForTimeout(500);
    R.densityAfterZoomIn = await p.evaluate(() => document.documentElement.getAttribute('data-density'));
    // 文件夹左滑：按住拖到一半截图
    const f = await p.evaluate(() => { const r = document.querySelector('.folder-swipe .folder-row'); if (!r) return null; const b = r.getBoundingClientRect(); return { x: b.right - 20, y: b.top + b.height / 2, w: b.width }; });
    if (f) {
      await p.mouse.move(f.x, f.y); await p.mouse.down();
      for (let i = 1; i <= 10; i++) { await p.mouse.move(f.x - i * 9, f.y); await p.waitForTimeout(16); }
      await p.waitForTimeout(100);
      R.swipe = await p.evaluate(() => { const r = document.querySelector('.folder-swipe .folder-row'); return getComputedStyle(r).transform; });
      await p.screenshot({ path: dir + 'r2_swipe.png', clip: { x: 0, y: 200, width: 240, height: 160 } });
      await p.mouse.move(f.x - 10, f.y); await p.mouse.up();   // 没过 50%：弹回
      await p.waitForTimeout(500);
    }
    // 深色模式下的选择栏
    await p.click('#btn-theme'); await p.waitForTimeout(600);
    const c2 = await p.evaluate(() => { const card = [...document.querySelectorAll('.grid .photo-card[data-id]')].find(e => { const r = e.getBoundingClientRect(); return r.top > 150 && r.bottom < 800; }); const r = card.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await p.mouse.click(c2.x, c2.y); await p.waitForTimeout(700);
    await p.screenshot({ path: dir + 'r2_dark.png' });
    await p.keyboard.press('Escape');
    await p.click('#btn-theme'); await p.waitForTimeout(300);
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
