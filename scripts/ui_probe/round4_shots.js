async (page) => {
  // 第四轮：按住滚动条的时间刻度尺；切换密度时滚动条不动(只动照片)；文件夹左滑 50% 阈值；存储卡空间块(测试台无卡→应隐藏)
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
    await p.evaluate(() => { const b = document.querySelector('#density-toggle [data-density="compact"]'); if (!b.classList.contains('active')) b.click(); });
    await p.waitForTimeout(1200);
    // 刻度尺：按住拇指拖一段
    const g = await p.evaluate(() => { const c = document.querySelector('#content'); const r = c.getBoundingClientRect(); const th = Math.max(44, c.clientHeight * c.clientHeight / c.scrollHeight); return { x: r.right - 7, y: r.top + c.scrollTop / (c.scrollHeight - c.clientHeight) * (c.clientHeight - th) + th / 2 }; });
    await p.mouse.move(g.x, g.y); await p.mouse.down();
    for (let i = 1; i <= 10; i++) { await p.mouse.move(g.x, g.y + i * 25); await p.waitForTimeout(25); }
    await p.waitForTimeout(450);
    R.ruler = await p.evaluate(() => { const r = document.querySelector('.sg-ruler'); return { show: r.classList.contains('show'), marks: r.querySelectorAll('.sg-ruler-mark').length, current: (r.querySelector('.sg-ruler-mark.current') || {}).textContent, stuck: (document.querySelector('.group-header.is-stuck h3') || {}).textContent }; });
    await p.screenshot({ path: dir + 'r4_ruler.png', clip: { x: 1100, y: 80, width: 300, height: 820 } });
    await p.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await p.waitForTimeout(300);
    await p.screenshot({ path: dir + 'r4_ruler_dark.png', clip: { x: 1100, y: 80, width: 300, height: 820 } });
    await p.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
    await p.mouse.up(); await p.waitForTimeout(700);
    R.rulerHidden = await p.evaluate(() => !document.querySelector('.sg-ruler').classList.contains('show'));
    // 切换密度：过渡中途滚动区位置/滚动条不动；内容在动
    const before = await p.evaluate(() => { const c = document.querySelector('#content'); return { left: c.getBoundingClientRect().left, transform: getComputedStyle(c).transform }; });
    const big = await p.evaluate(() => { const r = document.querySelector('#density-toggle [data-density="large"]').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await p.mouse.click(big.x, big.y);
    await p.waitForTimeout(90);
    R.midOut = await p.evaluate(() => { const c = document.querySelector('#content'); const s = c.querySelector('.day-group'); return { contentTransform: getComputedStyle(c).transform, contentAnims: c.getAnimations().length, secAnims: [...c.querySelectorAll(':scope > .day-group')].filter(x => x.getAnimations().length).length }; });
    await p.screenshot({ path: dir + 'r4_mid.png' });
    await p.waitForTimeout(800);
    R.after = await p.evaluate(() => ({ density: document.documentElement.getAttribute('data-density'), leftover: [...document.querySelectorAll('#content > .day-group')].filter(x => x.getAnimations().length || getComputedStyle(x).opacity !== '1').length }));
    // 连点三次
    for (const d of ['compact', 'mini', 'comfortable']) {
      const b = await p.evaluate(d => { const r = document.querySelector(`#density-toggle [data-density="${d}"]`).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, d);
      await p.mouse.click(b.x, b.y); await p.waitForTimeout(60);
    }
    await p.waitForTimeout(1200);
    R.afterRapid = await p.evaluate(() => ({ density: document.documentElement.getAttribute('data-density'), invisible: [...document.querySelectorAll('#content > .day-group')].filter(x => getComputedStyle(x).opacity !== '1').length }));
    // 左滑 55%：应已就绪(armed)
    const f = await p.evaluate(() => { const r = document.querySelector('.folder-swipe .folder-row'); const b = r.getBoundingClientRect(); return { x: b.right - 12, y: b.top + b.height / 2, w: b.width }; });
    await p.mouse.move(f.x, f.y); await p.mouse.down();
    for (let i = 1; i <= 8; i++) { await p.mouse.move(f.x - f.w * 0.55 * i / 8, f.y); await p.waitForTimeout(16); }
    await p.waitForTimeout(300);
    R.armedAt55 = await p.evaluate(() => document.querySelector('.folder-swipe').classList.contains('armed'));
    await p.mouse.move(f.x - 10, f.y); await p.mouse.up(); await p.waitForTimeout(600);
    R.cardSpace = await p.evaluate(() => { const c = document.getElementById('card-space'); return c ? { display: getComputedStyle(c).display, text: c.textContent.trim() } : null; });
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
