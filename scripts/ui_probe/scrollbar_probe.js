async (page) => {
  // 拖右侧滚动条快速滑动：量主线程帧间隔、滚动位置跟手程度，并用 CDP 抓 trace 按线程统计耗时大头。
  // 变体：current=现状；native=去掉 ::-webkit-scrollbar 自定义样式(系统滚动条，可走合成线程拖动)。
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'], ignoreDefaultArgs: ['--hide-scrollbars'] });
  const base = 'http://127.0.0.1:8766/';
  // 每个变体 = 额外注入的一段 CSS(用来定位是哪条样式让每帧变贵)
  // 变体：[注入的CSS, 设备像素比, 是否删 webkit 滚动条样式, 密度]
  const VARIANTS = {
    standard: ['', 1, false, 'comfortable'],
    standard15: ['', 1.5, false, 'comfortable'],
    mini: ['', 1, false, 'mini'],
  };
  const out = {};
  try {
    for (const variant of Object.keys(VARIANTS)) {
      const ctx = await hb.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: VARIANTS[variant][1] });
      const p = await ctx.newPage();
      await p.goto(base);
      try {
        await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 30000 });
      } catch (e) {
        out[variant] = { error: 'load timeout', state: await p.evaluate(() => [document.querySelectorAll('.photo-card').length, document.querySelectorAll('.photo-thumb.is-loaded').length, document.title]) };
        await ctx.close();
        continue;
      }
      if (VARIANTS[variant][0]) await p.addStyleTag({ content: VARIANTS[variant][0] });
      if (VARIANTS[variant][3]) { await p.evaluate(d => { const b = document.querySelector(`#density-toggle [data-density="${d}"]`); if (b && !b.classList.contains('active')) b.click(); }, VARIANTS[variant][3]); await p.waitForTimeout(800); }
      if (VARIANTS[variant][2]) await p.evaluate(() => { for (const sh of document.styleSheets) { for (let i = sh.cssRules.length - 1; i >= 0; i--) { const r = sh.cssRules[i]; if (r.selectorText && r.selectorText.includes('::-webkit-scrollbar')) sh.deleteRule(i); } } const c = document.querySelector('#content'); window.__arrowPad = c.offsetWidth - c.clientWidth; });
      await p.waitForTimeout(1500);
      const geo = await p.evaluate(() => {
        const c = document.querySelector('#content');
        const r = c.getBoundingClientRect();
        const thumbH = Math.max(18, c.clientHeight * c.clientHeight / c.scrollHeight);
        const thumbTop = r.top + c.scrollTop / c.scrollHeight * c.clientHeight;
        return { x: r.right - Math.max(3, (c.offsetWidth - c.clientWidth) / 2), sbw: c.offsetWidth - c.clientWidth, y: thumbTop + thumbH / 2 + (window.__arrowPad || 0), h: c.clientHeight, sh: c.scrollHeight, cards: c.querySelectorAll('.photo-card').length };
      });
      // 页面内记录：每个 rAF 的时间与 scrollTop、长任务
      await p.evaluate(() => {
        const c = document.querySelector('#content');
        window.__rec = { frames: [], long: [] };
        const loop = (t) => { window.__rec.frames.push([t, c.scrollTop]); window.__rafId = requestAnimationFrame(loop); };
        window.__rafId = requestAnimationFrame(loop);
        try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__rec.long.push(Math.round(e.duration)))).observe({ entryTypes: ['longtask'] }); } catch (e) {}
      });
      const cdp = await ctx.newCDPSession(p);
      await cdp.send('Tracing.start', { transferMode: 'ReturnAsStream', traceConfig: { includedCategories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'blink', 'cc', 'toplevel', 'disabled-by-default-devtools.timeline.frame'] } });
      // 按住滚动条拇指往下拖 ~700px(约 1.2 秒)，停一下，再拖回一半
      await p.mouse.move(geo.x, geo.y);
      await p.mouse.down();
      const t0 = Date.now();
      for (let i = 1; i <= 40; i++) { await p.mouse.move(geo.x, geo.y + i * 10); await p.waitForTimeout(16); }
      await p.waitForTimeout(400);
      for (let i = 1; i <= 20; i++) { await p.mouse.move(geo.x, geo.y + 400 - i * 10); await p.waitForTimeout(16); }
      await p.mouse.up();
      const dragMs = Date.now() - t0;
      await p.waitForTimeout(600);
      const traceDone = new Promise(res => cdp.once('Tracing.tracingComplete', res));
      await cdp.send('Tracing.end');
      const { stream } = await traceDone;
      let text = '';
      for (;;) { const r = await cdp.send('IO.read', { handle: stream, size: 1 << 20 }); text += r.base64Encoded ? Buffer.from(r.data, 'base64').toString('utf8') : r.data; if (r.eof) break; }
      await cdp.send('IO.close', { handle: stream });
      const rec = await p.evaluate(() => { cancelAnimationFrame(window.__rafId); return window.__rec; });
      // ── 帧统计(只看拖动期间) ──
      const f = rec.frames;
      const gaps = [];
      for (let i = 1; i < f.length; i++) gaps.push(f[i][0] - f[i - 1][0]);
      const fs = gaps.slice(0, Math.max(1, gaps.length - 36)).sort((a, b) => a - b);   // 去掉松手后的尾巴
      const q = k => Math.round(fs[Math.min(fs.length - 1, Math.floor(fs.length * k))]);
      let jumps = 0, maxJump = 0;
      for (let i = 1; i < f.length; i++) { const d = Math.abs(f[i][1] - f[i - 1][1]); maxJump = Math.max(maxJump, d); if (d > geo.h * 0.8) jumps++; }
      // ── trace 统计 ──
      const evs = JSON.parse(text).traceEvents || JSON.parse(text);
      const threadName = {};
      evs.forEach(e => { if (e.ph === 'M' && e.name === 'thread_name') threadName[e.pid + ':' + e.tid] = e.args.name; });
      const byThread = {}, byName = {};
      const NAMES = new Set(['RunTask', 'ThreadControllerImpl::RunTask', 'FunctionCall', 'TimerFire', 'FireAnimationFrame', 'EventDispatch', 'UpdateLayoutTree', 'Layout', 'PrePaint', 'Paint', 'PaintArtifactCompositor::Update', 'Layerize', 'Commit', 'HitTest', 'IntersectionObserverController::computeIntersections', 'ComputeIntersections', 'Decode Image', 'ImageDecodeTask', 'RasterTask', 'TileManager::FlushAndIssueSignals', 'ScrollbarController::HandlePointerMove', 'InputHandlerProxy::HandleInputEventWithLatencyInfo', 'GestureScrollUpdate', 'ParseHTML', 'MinorGC', 'MajorGC', 'V8.GC_SCAVENGER', 'BlinkGC.AtomicPhase']);
      evs.forEach(e => {
        if (e.ph !== 'X' || !e.dur) return;
        const th = threadName[e.pid + ':' + e.tid] || 'other';
        if (!/CrRendererMain|Compositor|TileWorker|VizCompositor|CrGpuMain/.test(th)) return;
        const tk = th.replace(/\d+$/, '');
        if (e.name === 'ThreadControllerImpl::RunTask' || e.name === 'RunTask') byThread[tk] = (byThread[tk] || 0) + e.dur / 1000;
        if (NAMES.has(e.name)) { const k = tk + ' · ' + e.name; byName[k] = (byName[k] || 0) + e.dur / 1000; byName[k + '#'] = (byName[k + '#'] || 0) + 1; }
      });
      const round = o => Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, 26).map(([k, v]) => [k, Math.round(v)]));
      out[variant] = {
        geo, dragMs,
        frames: gaps.length, p50: q(0.5), p90: q(0.9), p99: q(0.99), max: q(1 - 1e-9),
        over33ms: fs.filter(g => g > 33).length,
        bigJumps: jumps, maxJumpPx: Math.round(maxJump),
        longTasks: rec.long.length,
        busyMsByThread: round(byThread), layerize: Math.round(byName['CrRendererMain · Layerize'] || 0), layerizeN: byName['CrRendererMain · Layerize#'] || 0, paint: Math.round(byName['CrRendererMain · Paint'] || 0),
      };
      await ctx.close();
    }
  } finally { await hb.close(); }
  return out;
}
