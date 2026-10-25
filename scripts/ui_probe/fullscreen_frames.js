async (page) => {
  // 全屏"从缩略图飞出/飞回"过程截帧
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    await p.goto('http://127.0.0.1:8765/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });
    await p.waitForTimeout(800);
    const c = await p.evaluate(() => { const r = [...document.querySelectorAll('.grid .photo-card[data-id]:not(.stack-cell)')][7].getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    await p.mouse.dblclick(c.x, c.y);
    const shots = [60, 140, 260, 700];
    let t = 0;
    for (const ms of shots) { await p.waitForTimeout(ms - t); t = ms; await p.screenshot({ path: dir + `fs_open_${ms}.png` }); }
    await p.keyboard.press('Escape');
    t = 0;
    for (const ms of [80, 200, 700]) { await p.waitForTimeout(ms - t); t = ms; await p.screenshot({ path: dir + `fs_close_${ms}.png` }); }
    return 'ok';
  } finally { await hb.close(); }
}
