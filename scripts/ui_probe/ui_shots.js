async (page) => {
  // 关键界面截图：选择栏 + 组头部分选中、机型下拉、分类视图、空状态
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  const dir = 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\';
  try {
    const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
    await p.goto('http://127.0.0.1:8765/');
    await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });
    await p.waitForTimeout(800);
    const pos = (sel, i) => p.evaluate(([s, k]) => { const e = document.querySelectorAll(s)[k || 0]; const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, [sel, i]);
    for (const i of [0, 2, 3]) { const c = await pos('.grid .photo-card[data-id]:not(.stack-cell)', i); await p.mouse.click(c.x, c.y); await p.waitForTimeout(80); }
    const sc = await pos('.stack-check', 1); await p.mouse.click(sc.x, sc.y);
    await p.waitForTimeout(700);
    await p.screenshot({ path: dir + 'sel_bar.png' });
    await p.evaluate(() => document.getElementById('sel-clear').click());
    await p.waitForTimeout(300);
    const f = await pos('#btn-filter'); await p.mouse.click(f.x, f.y);
    await p.waitForTimeout(500);
    await p.screenshot({ path: dir + 'camera_menu.png', clip: { x: 220, y: 32, width: 700, height: 300 } });
    await p.mouse.click(1300, 500);
    await p.waitForTimeout(300);
    const g = await pos('#tier-nav [data-filter="good"]'); await p.mouse.click(g.x, g.y);
    await p.waitForTimeout(700);
    await p.screenshot({ path: dir + 'empty_good.png', clip: { x: 220, y: 32, width: 1180, height: 500 } });
    return 'ok';
  } finally { await hb.close(); }
}
