async (page) => {
  // 全屏逐级换清：双击打开 → 缩略图 → 屏幕预览；立刻滚轮放大 → 原图；晚到的预览不能把原图盖回去
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe' });
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    const errors = [];
    p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
    await p.goto('http://127.0.0.1:8766/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 30000 });
    await fetch('http://127.0.0.1:8766/__cold', { method: 'POST' }).catch(() => {});   // 预览/原图都还没生成
    const bg = () => p.evaluate(() => { const m = /url\("?'?([^"')]+)/.exec(document.getElementById('fp-image').style.backgroundImage || ''); return m ? m[1].replace(/^https?:\/\/[^/]+\//, '') : ''; });
    const R = { timeline: [] };
    const pick = async (k) => { const c = await p.evaluate(k => { const cards = [...document.querySelectorAll('.grid .photo-card[data-id]')].filter(e => { const r = e.getBoundingClientRect(); return r.top > 150 && r.bottom < 800; }); const r = cards[k].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, k); return c; };
    // 场景1：双击打开，看换清时间线
    let c = await pick(0);
    const t0 = Date.now();
    await p.mouse.dblclick(c.x, c.y);
    for (let i = 0; i < 30; i++) { const b = await bg(); if (!R.timeline.length || R.timeline[R.timeline.length - 1][1] !== b) R.timeline.push([Date.now() - t0, b]); await p.waitForTimeout(50); }
    // 场景2：放大 → 原图
    await p.mouse.move(700, 450);
    await p.mouse.wheel(0, -300); await p.waitForTimeout(1500);
    R.afterZoom = await bg();
    await p.keyboard.press('Escape'); await p.waitForTimeout(600);
    // 场景3：冷缓存下打开另一张、立刻放大(预览还在生成)：最后必须停在原图，不能被晚到的预览盖回去
    c = await pick(3);
    await p.mouse.dblclick(c.x, c.y);
    await p.waitForTimeout(30);
    await p.mouse.move(700, 450);
    await p.mouse.wheel(0, -400);
    await p.waitForTimeout(2500);
    R.raceFinal = await bg();
    // 场景4：翻到下一张，相邻预览已预取 → 很快变清晰
    await p.mouse.wheel(0, 600); await p.waitForTimeout(400);
    const t1 = Date.now();
    await p.keyboard.press('ArrowRight');
    let sharpAt = null;
    for (let i = 0; i < 40; i++) { const b = await bg(); if (/preview_cache|orig_cache/.test(b)) { sharpAt = Date.now() - t1; break; } await p.waitForTimeout(25); }
    R.nextSharpMs = sharpAt;
    await p.keyboard.press('Escape');
    R.errors = errors;
    return R;
  } finally { await hb.close(); }
}
