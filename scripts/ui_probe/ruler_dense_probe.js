async (page) => {
  // 时间刻度在"日期密集"图库(ui_harness --days 60 --port 8767)下：标签是否全部显示、互不重叠、点击能到位；
  // 并把视口压矮，逼出"按月份降级"分支。
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', ignoreDefaultArgs: ['--hide-scrollbars'] });
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  const R = {};
  const measure = () => {
    const r = document.querySelector('.sg-ruler');
    const marks = [...r.querySelectorAll('.sg-ruler-mark')];
    const rects = marks.map(b => b.getBoundingClientRect()).sort((a, b) => a.top - b.top);
    let overlaps = 0;
    for (let i = 1; i < rects.length; i++) if (rects[i].top < rects[i - 1].bottom - 0.5) overlaps++;
    const rr = r.getBoundingClientRect();
    return {
      show: r.classList.contains('show'), marks: marks.length, dots: r.querySelectorAll('.sg-ruler-dot').length,
      groups: document.querySelectorAll('#content > .day-group').length,
      labels: marks.slice(0, 4).map(b => b.textContent).concat(['…'], marks.slice(-2).map(b => b.textContent)),
      overlaps, outOfBounds: rects.filter(x => x.top < rr.top - 1 || x.bottom > rr.bottom + 1).length,
    };
  };
  try {
    for (const vh of [900, 520]) {
      const p = await hb.newPage({ viewport: { width: 1400, height: vh } });
      const errors = [];
      p.on('pageerror', e => errors.push(String(e).slice(0, 300)));
      await p.goto('http://127.0.0.1:8767/');
      await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 10, null, { timeout: 40000 });
      await p.evaluate(() => { const b = document.querySelector('#density-toggle [data-density="compact"]'); if (b && !b.classList.contains('active')) b.click(); });
      await p.waitForTimeout(1000);
      const cr = await p.evaluate(() => { const r = document.querySelector('#content').getBoundingClientRect(); return { right: r.right }; });
      await p.mouse.move(cr.right - 60, 300);
      await p.mouse.move(cr.right - 8, 300, { steps: 4 });
      await p.waitForTimeout(500);
      const k = 'vh' + vh;
      R[k] = await p.evaluate(measure);
      await p.screenshot({ path: dir + `ruler_dense_${vh}.png`, clip: { x: 1160, y: 60, width: 240, height: vh - 60 } });
      // 点一个中间的标签：应滚到该组附近
      const t = await p.evaluate(() => { const ms = [...document.querySelectorAll('.sg-ruler-mark')]; const m = ms[Math.floor(ms.length / 2)]; const r = m.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, label: m.textContent }; });
      await p.mouse.click(t.x, t.y);
      await p.waitForTimeout(1200);
      R[k].click = await p.evaluate((label) => ({ clicked: label, stuck: (document.querySelector('.group-header.is-stuck h3') || {}).textContent, current: (document.querySelector('.sg-ruler-mark.current') || {}).textContent }), t.label);
      R[k].errors = errors;
      await p.close();
    }
    return R;
  } finally { await hb.close(); }
}
