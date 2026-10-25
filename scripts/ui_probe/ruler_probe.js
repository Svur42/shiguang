async (page) => {
  // 时间刻度：鼠标靠近滚动条出现；日期全部显示；点日期平滑滚过去、顶上日期随之切换
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
    const cr = await p.evaluate(() => { const r = document.querySelector('#content').getBoundingClientRect(); return { right: r.right, top: r.top, bottom: r.bottom }; });
    await p.mouse.move(cr.right - 60, 500);
    await p.mouse.move(cr.right - 8, 500, { steps: 4 });
    await p.waitForTimeout(450);
    R.ruler = await p.evaluate(() => { const r = document.querySelector('.sg-ruler'); return { show: r.classList.contains('show'), labels: [...r.querySelectorAll('.sg-ruler-mark')].map(b => b.textContent), current: (r.querySelector('.sg-ruler-mark.current') || {}).textContent }; });
    await p.screenshot({ path: dir + 'ruler_hover.png', clip: { x: 1180, y: 80, width: 220, height: 820 } });
    // 点最后一个日期：记录滚动过程(平滑 vs 跳)
    const target = await p.evaluate(() => { const m = [...document.querySelectorAll('.sg-ruler-mark')].pop(); const r = m.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: m.textContent }; });
    await p.mouse.move(target.x, target.y, { steps: 6 });
    await p.evaluate(() => { window.__st = []; const c = document.querySelector('#content'); const t0 = performance.now(); const f = () => { window.__st.push([Math.round(performance.now() - t0), Math.round(c.scrollTop)]); if (performance.now() - t0 < 1000) requestAnimationFrame(f); }; requestAnimationFrame(f); });
    await p.mouse.click(target.x, target.y);
    await p.waitForTimeout(1100);
    const st = await p.evaluate(() => window.__st);
    const vals = [...new Set(st.map(x => x[1]))];
    R.scroll = { distinctPositions: vals.length, from: st[0][1], to: st[st.length - 1][1], durationMs: (st.find(x => x[1] === st[st.length - 1][1]) || [0])[0] };
    R.after = await p.evaluate(() => ({ stuck: (document.querySelector('.group-header.is-stuck h3') || {}).textContent, current: (document.querySelector('.sg-ruler-mark.current') || {}).textContent }));
    R.target = target.label;
    await p.screenshot({ path: dir + 'ruler_after.png', clip: { x: 220, y: 30, width: 1180, height: 300 } });
    // 移开鼠标：淡出
    await p.mouse.move(600, 500, { steps: 4 });
    await p.waitForTimeout(800);
    R.hidden = await p.evaluate(() => !document.querySelector('.sg-ruler').classList.contains('show'));
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
