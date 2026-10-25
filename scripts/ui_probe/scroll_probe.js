async (page) => {
  // 快速滑动测试(冷缓存 + 模拟读卡慢)。"已出图" = 该缩略图 URL 的下载真正完成(Resource Timing)且已贴到卡上，
  // 新旧两版用同一口径。滚动用真实滚轮事件(合成器滚动)，采样每 100ms 一次，尽量不干扰被测页面。
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  const base = 'http://127.0.0.1:8766/';
  const results = {};
  const sampler = () => {
    const c = document.querySelector('#content');
    const cr = c.getBoundingClientRect();
    const done = new Set(performance.getEntriesByType('resource').filter(e => e.responseEnd > 0).map(e => e.name));
    let n = 0, tot = 0;
    c.querySelectorAll('.photo-thumb').forEach(t => {
      if (t.closest('.sg-ghost')) return;
      const q = t.getBoundingClientRect();
      if (q.bottom < cr.top || q.top > cr.bottom) return;
      tot++;
      let url = t.dataset.thumb || '';
      const m = /url\("?([^")]+)"?\)/.exec(t.style.getPropertyValue('--img') || t.style.backgroundImage || '');
      if (m) url = m[1];
      const painted = t.classList.contains('is-loaded') || (!!t.style.backgroundImage && t.style.backgroundImage !== 'none');
      if (!(painted && done.has(url))) n++;
    });
    return [n, tot, Math.round(c.scrollTop)];
  };
  try {
    for (const variant of ['comfortable', 'mini']) {   // 两种密度(对照旧前端时可加回 'baseline')
      await fetch(base + '__cold', { method: 'POST' }).catch(() => {});
      await new Promise(r => setTimeout(r, 300));
      const ctx = await hb.newContext({ viewport: { width: 1400, height: 900 } });
      const p = await ctx.newPage();
      await p.goto(base + (variant === 'baseline' ? '?v=baseline' : ''));
      if (variant !== 'baseline') await p.evaluate(d => { const b = document.querySelector(`#density-toggle [data-density="${d}"]`); if (b && !b.classList.contains('active')) b.click(); }, variant);
      await p.waitForFunction(() => document.querySelectorAll('#content .photo-card').length > 50, null, { timeout: 30000 });
      await p.evaluate(() => performance.setResourceTimingBufferSize(20000));
      await p.waitForTimeout(3000);   // 用户先看 3 秒第一屏
      await p.mouse.move(800, 500);
      const during = [];
      const t0 = Date.now();
      while (Date.now() - t0 < 2400) {   // 用力甩滚轮 2.4 秒
        await p.mouse.wheel(0, 300);
        await p.waitForTimeout(40);
        if (during.length * 100 < Date.now() - t0) during.push(await p.evaluate(sampler));
      }
      const stopAt = Date.now();
      let settle = null, last;
      while (Date.now() - stopAt < 9000) {
        last = await p.evaluate(sampler);
        if (last[0] === 0) { settle = Date.now() - stopAt; break; }
        await p.waitForTimeout(80);
      }
      const ratio = during.reduce((a, s) => a + (s[1] ? s[0] / s[1] : 0), 0) / Math.max(1, during.length);
      // 往回滚一半(看过的地方)：是否秒出
      const mid = Math.round(last[2] / 2);
      await p.evaluate(y => { document.querySelector('#content').scrollTop = y; }, mid);
      await p.waitForTimeout(150);
      const back = await p.evaluate(sampler);
      results[variant] = {
        blankWhileScrolling: Math.round(ratio * 100) + '%',
        settleAfterStopMs: settle,
        stillBlankAtGiveUp: settle == null ? last[0] + '/' + last[1] : 0,
        scrolledPx: last[2],
        revisitBlank150ms: back[0] + '/' + back[1],
      };
      await ctx.close();
    }
  } finally { await hb.close(); }
  return results;
}
