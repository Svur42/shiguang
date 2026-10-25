async (page) => {
  // 展开/收起过程截几帧(只截堆叠附近区域)，肉眼检查动画观感
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  try {
  const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
  await p.goto('http://127.0.0.1:8765/');
  await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });
  await p.evaluate(() => { document.querySelector('#content').scrollTop = 700; });
  await p.waitForTimeout(1500);
  const t = await p.evaluate(() => {
    const c = document.querySelector('#content'); const cr = c.getBoundingClientRect();
    const cands = [...document.querySelectorAll('.stack-card')].filter(s => { const r = s.getBoundingClientRect(); return r.top > cr.top + 60 && r.bottom < cr.bottom - 260; });
    cands.sort((a, b) => b.querySelectorAll('.stack-layer').length - a.querySelectorAll('.stack-layer').length);
    const r = cands[0].getBoundingClientRect();
    // 预先把成员图都解码好，专看动画本身
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, top: r.top };
  });
  const clip = { x: 220, y: Math.max(32, t.top - 190), width: 1180, height: 560 };
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  await p.mouse.click(t.x, t.y);
  for (const ms of [40, 110, 200, 420]) {
    await p.waitForTimeout(ms === 40 ? 40 : ms - [40, 110, 200, 420][[40, 110, 200, 420].indexOf(ms) - 1]);
    await p.screenshot({ path: dir + `expand_${ms}.png`, clip });
  }
  await p.waitForTimeout(800);
  await p.screenshot({ path: dir + 'expand_done.png', clip });
  const star = await p.evaluate(() => { const b = document.querySelector('.stack-keep-star').getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
  await p.mouse.click(star.x, star.y);
  for (const ms of [60, 160, 300]) {
    await p.waitForTimeout(ms === 60 ? 60 : ms - [60, 160, 300][[60, 160, 300].indexOf(ms) - 1]);
    await p.screenshot({ path: dir + `collapse_${ms}.png`, clip });
  }
  await p.waitForTimeout(700);
  await p.screenshot({ path: dir + 'collapse_done.png', clip });
  await p.close();
  return 'ok';
  } finally { await hb.close(); }
}
