async (page) => {
  // 用户报的加载问题：冷缓存 + 慢卡，拖滚动条一下跳到还没加载的地方，停住不动——眼前这一屏应该最先、
  // 持续地加载出来，而不是停滞(以前要拖回"加载边缘"才继续)。量：停住后每 250ms 眼前已出图张数。
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', ignoreDefaultArgs: ['--hide-scrollbars'] });
  const base = 'http://127.0.0.1:8766/';
  const out = {};
  try {
    for (const density of ['comfortable', 'mini']) {
      await fetch(base + '__cold', { method: 'POST' }).catch(() => {});
      await new Promise(r => setTimeout(r, 300));
      const ctx = await hb.newContext({ viewport: { width: 1400, height: 900 } });
      const p = await ctx.newPage();
      await p.goto(base);
      await p.evaluate(d => { const b = document.querySelector(`#density-toggle [data-density="${d}"]`); if (b && !b.classList.contains('active')) b.click(); }, density);
      await p.waitForFunction(() => document.querySelectorAll('#content .photo-card').length > 50, null, { timeout: 30000 });
      await p.waitForTimeout(2500);   // 第一屏加载一会儿
      const g = await p.evaluate(() => { const c = document.querySelector('#content'); const r = c.getBoundingClientRect(); const th = Math.max(44, c.clientHeight * c.clientHeight / c.scrollHeight); return { x: r.right - 7, y: r.top + th / 2, track: c.clientHeight - th }; });
      await p.mouse.move(g.x, g.y); await p.mouse.down();
      const steps = 12;
      for (let i = 1; i <= steps; i++) { await p.mouse.move(g.x, g.y + g.track * 0.7 * i / steps); await p.waitForTimeout(16); }
      await p.mouse.up();
      const samples = [];
      const t0 = Date.now();
      while (Date.now() - t0 < 12000) {
        samples.push(await p.evaluate(() => {
          const c = document.querySelector('#content'); const cr = c.getBoundingClientRect();
          let n = 0, ok = 0;
          c.querySelectorAll('.photo-thumb').forEach(t => { if (t.closest('.sg-ghost')) return; const r = t.getBoundingClientRect(); if (r.bottom < cr.top || r.top > cr.bottom) return; n++; if (t.classList.contains('is-loaded')) ok++; });
          return [ok, n];
        }));
        await p.waitForTimeout(250);
      }
      const at = k => { const s = samples[Math.min(samples.length - 1, Math.round(k * 4))]; return s ? `${s[0]}/${s[1]}` : '-'; };
      const full = samples.findIndex(s => s[1] && s[0] === s[1]);
      out[density] = { after1s: at(1), after2s: at(2), after4s: at(4), after8s: at(8), after12s: at(11.9), fullAtMs: full < 0 ? null : full * 250 };
      await ctx.close();
    }
  } finally { await hb.close(); }
  return out;
}
