async (page) => {
  // 用无头 Chromium(真GPU，不受窗口遮挡节流)测：展开/收起堆叠时的帧间隔、可见区空白缩略图、滚动位置是否被挪动
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({
    headless: true,
    executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe',
    args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'],
  });
  try {
  const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
  // 目标测试台：沿用 MCP 主页面当前打开的测试台地址(切到 8766 就测大图库)
  const url = /^http:\/\/127\.0\.0\.1:\d+\/$/.test(page.url()) ? page.url() : 'http://127.0.0.1:8765/';
  await p.goto(url);
  await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });
  await p.evaluate(() => { document.querySelector('#content').scrollTop = 700; });
  await p.waitForTimeout(1200);
  await p.evaluate(() => {
    window.__rec = { on: false, frames: [] };
    window.__recStart = () => {
      window.__rec = { on: true, frames: [] };
      const c = document.querySelector('#content');
      const tick = () => {
        const cr = c.getBoundingClientRect();
        let blank = 0;
        document.querySelectorAll('#content .photo-thumb').forEach(t => {
          if (t.closest('.sg-ghost')) return;
          const r = t.getBoundingClientRect();
          if (r.bottom < cr.top || r.top > cr.bottom) return;
          if (!t.classList.contains('is-loaded')) blank++;
        });
        window.__rec.frames.push([performance.now(), c.scrollTop, blank]);
        if (window.__rec.on) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };
    window.__recStop = () => {
      window.__rec.on = false;
      const f = window.__rec.frames;
      const gaps = f.slice(1).map((x, i) => x[0] - f[i][0]).sort((a, b) => a - b);
      return {
        frames: f.length,
        p95gap: Math.round(gaps[Math.floor(gaps.length * 0.95)] || 0),
        maxGap: Math.round(gaps[gaps.length - 1] || 0),
        over25ms: gaps.filter(g => g > 25).length,
        maxBlank: Math.max(...f.map(x => x[2])),
        scrollValues: [...new Set(f.map(x => Math.round(x[1])))],
      };
    };
  });
  const target = await p.evaluate(() => {
    const c = document.querySelector('#content'); const cr = c.getBoundingClientRect();
    const cands = [...document.querySelectorAll('.stack-card')].filter(s => { const r = s.getBoundingClientRect(); return r.top > cr.top + 60 && r.bottom < cr.bottom - 60; });
    cands.sort((a, b) => b.querySelectorAll('.stack-layer').length - a.querySelectorAll('.stack-layer').length);
    const s = cands[0];
    const r = s.getBoundingClientRect();
    return { skey: s.dataset.skey, x: r.left + r.width / 2, y: r.top + r.height / 2, n: s.querySelector('.stack-count-badge').textContent.trim() };
  });
  await p.evaluate(() => window.__recStart());
  await p.mouse.click(target.x, target.y);
  await p.waitForTimeout(900);
  const expand = await p.evaluate(() => window.__recStop());
  expand.cellsAfter = await p.evaluate(() => document.querySelectorAll('.stack-cell').length);
  expand.stuckZ = await p.evaluate(() => [...document.querySelectorAll('.stack-cell')].filter(c => c.style.zIndex).length);
  const star = await p.evaluate(() => { const b = document.querySelector('.stack-keep-star').getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
  await p.evaluate(() => window.__recStart());
  await p.mouse.click(star.x, star.y);
  await p.waitForTimeout(900);
  const collapse = await p.evaluate(() => window.__recStop());
  collapse.cellsAfter = await p.evaluate(() => document.querySelectorAll('.stack-cell').length);
  collapse.ghostsLeft = await p.evaluate(() => document.querySelectorAll('.sg-ghost').length);
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.close();
  return { target, expand, collapse, errors };
  } finally { await hb.close(); }
}
