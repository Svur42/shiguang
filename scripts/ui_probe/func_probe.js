async (page) => {
  // 功能冒烟：组头勾选 / Shift 连选 / 选择栏 / 批量标档+撤销 / 删除+撤销(按时间放回) / 筛选视图里的堆叠 /
  // 分类视图按天分组 / 机型下拉 / 全屏飞出+关闭飞回 / 滚轮按光标缩放 / 快捷键 / 一键全选范围 / 深色模式
  const bt = page.context().browser().browserType();
  const hb = await bt.launch({ headless: true, executablePath: 'D:\\数据\\Cache\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe', args: ['--enable-gpu-rasterization', '--ignore-gpu-blocklist'] });
  try {
  const p = await hb.newPage({ viewport: { width: 1400, height: 900 } });
  const bad = [];
  p.on('response', r => { if (r.status() >= 400 && !/favicon/.test(r.url())) bad.push(r.status() + ' ' + r.url()); });
  const errors = [];
  p.on('pageerror', e => errors.push(String(e).slice(0, 200)));
  p.on('console', m => { if (m.type() === 'error' && !/favicon/.test(m.text())) errors.push('console: ' + m.text().slice(0, 200)); });
  const R = {};
  const ev = (fn, arg) => p.evaluate(fn, arg);
  const center = async (sel) => ev((s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; }, sel);
  const click = async (sel, opts) => { const c = await center(sel); if (!c) throw new Error('no ' + sel); await p.mouse.click(c.x, c.y, opts); };
  await p.goto('http://127.0.0.1:8765/');
  await p.waitForFunction(() => document.querySelectorAll('.photo-thumb.is-loaded').length > 20, null, { timeout: 20000 });

  // 1) 组头勾选：整组选中 → 选择栏出现、数量=该组张数(含折叠成员)
  const g = await ev(() => { const b = document.querySelector('[data-group-check]'); return { key: b.dataset.groupCheck, count: Number(b.parentElement.querySelector('.group-count').textContent.replace(/\D/g, '')) }; });
  await click('[data-group-check]');
  await p.waitForTimeout(300);
  R.groupCheck = await ev(() => ({ selected: document.getElementById('sel-num').textContent, barShown: document.getElementById('sel-bar').classList.contains('show'), headerAll: document.querySelector('[data-group-check]').classList.contains('is-all') }));
  R.groupCheck.expected = g.count;
  await click('[data-group-check]');
  await p.waitForTimeout(250);
  R.groupUncheck = await ev(() => ({ selected: document.getElementById('sel-num').textContent, barShown: document.getElementById('sel-bar').classList.contains('show') }));

  // 2) Shift 连选：点第1张普通卡，Shift 点第4张普通卡
  const ids = await ev(() => [...document.querySelectorAll('.grid .photo-card[data-id]:not(.stack-cell)')].slice(0, 6).map(c => Number(c.dataset.id)));
  await click(`.photo-card[data-id="${ids[0]}"]`);
  await p.waitForTimeout(120);
  await p.keyboard.down('Shift');
  await click(`.photo-card[data-id="${ids[3]}"]`);
  await p.keyboard.up('Shift');
  await p.waitForTimeout(250);
  R.shiftRange = await ev(() => Number(document.getElementById('sel-num').textContent));

  // 3) 批量标档：标为精选 → 侧栏精选计数增加；撤销 → 恢复
  const before = await ev(() => Number(document.getElementById('cnt-good').textContent));
  await click('[data-set-tier="good"]');
  await p.waitForTimeout(400);
  const after = await ev(() => Number(document.getElementById('cnt-good').textContent));
  await click('.toast-undo');
  await p.waitForTimeout(400);
  const undone = await ev(() => Number(document.getElementById('cnt-good').textContent));
  R.markTier = { before, after, undone };

  // 4) 删除所选 + 撤销：删除后数量减少、撤销后按时间放回原位(第一张卡还是原来那张)
  const firstBefore = await ev(() => document.querySelector('.grid [data-key]').dataset.key);
  const totalBefore = await ev(() => Number(document.getElementById('cnt-all').textContent));
  await click('#sel-delete');
  await p.waitForTimeout(450);
  const totalAfterDel = await ev(() => Number(document.getElementById('cnt-all').textContent));
  await click('.toast-undo');
  await p.waitForTimeout(450);
  R.deleteUndo = { totalBefore, totalAfterDel, totalAfterUndo: await ev(() => Number(document.getElementById('cnt-all').textContent)), sameFirst: firstBefore === await ev(() => document.querySelector('.grid [data-key]').dataset.key), ghostsLeft: await ev(() => document.querySelectorAll('.sg-ghost').length) };
  await ev(() => document.getElementById('sel-clear').click());
  await p.waitForTimeout(200);

  // 5) 筛选"废片"：也能折叠，且堆里成员全是废片
  await click('#tier-nav [data-filter="bad"]');
  await p.waitForTimeout(500);
  R.badView = await ev(() => {
    const stacks = [...document.querySelectorAll('.stack-card')];
    const nonBadCards = [...document.querySelectorAll('.grid .photo-card[data-id]')].filter(c => !c.classList.contains('tier-bad')).length;
    const nonBadCovers = [...document.querySelectorAll('.stack-card-thumb')].filter(c => !c.classList.contains('tier-bad')).length;
    return { stacks: stacks.length, nonBadCards, nonBadCovers, headers: document.querySelectorAll('.group-header').length };
  });
  // 展开一个废片堆，成员也都应是废片
  if (R.badView.stacks) {
    await click('.stack-card');
    await p.waitForTimeout(700);
    R.badView.expandedNonBad = await ev(() => [...document.querySelectorAll('.stack-cell')].filter(c => !c.classList.contains('tier-bad')).length);
    R.badView.expandedCount = await ev(() => document.querySelectorAll('.stack-cell').length);
  }

  // 6) 分类视图已去掉(与左侧档位重复)：工具栏里不应再有视图切换
  await click('#tier-nav [data-filter="all"]');
  await p.waitForTimeout(400);
  R.noViewToggle = await ev(() => !document.getElementById('view-toggle'));

  // 7) 机型下拉：选一个机型 → 只剩该机型
  await click('#btn-filter');
  await p.waitForTimeout(400);
  R.cameraMenu = await ev(() => ({ open: document.getElementById('camera-menu').classList.contains('open'), items: [...document.querySelectorAll('#camera-menu .sg-menu-item')].map(b => b.textContent.trim()) }));
  await click('#camera-menu .sg-menu-item:nth-child(2)');
  await p.waitForTimeout(500);
  R.cameraFilter = await ev(() => ({ label: document.getElementById('filter-label').textContent, shown: document.querySelectorAll('.grid .photo-card[data-id], .stack-card').length }));
  await click('#btn-filter');
  await p.waitForTimeout(300);
  await click('#camera-menu .sg-menu-item:nth-child(1)');
  await p.waitForTimeout(500);

  // 8) 全屏：双击普通卡 → 飞出；Esc → 关闭(且不清选择)
  const cid = await ev(() => Number(document.querySelector('.grid .photo-card[data-id]:not(.stack-cell)').dataset.id));
  const cc = await center(`.photo-card[data-id="${cid}"]`);
  await p.mouse.dblclick(cc.x, cc.y);
  await p.waitForTimeout(80);
  R.fullscreen = { heroDuring: await ev(() => document.querySelectorAll('.fp-hero').length) };
  await p.waitForTimeout(600);
  R.fullscreen.open = await ev(() => document.getElementById('fp-overlay').classList.contains('open'));
  R.fullscreen.heroAfter = await ev(() => document.querySelectorAll('.fp-hero').length);
  R.fullscreen.selectedAfterDbl = await ev((id) => document.querySelector(`.photo-card[data-id="${id}"]`).classList.contains('selected'), cid);
  // 滚轮在左上区域放大 → 放大后光标下的点应基本不动(pan 朝光标反方向)
  await p.mouse.move(500, 300);
  for (let i = 0; i < 3; i++) { await p.mouse.wheel(0, -120); await p.waitForTimeout(60); }
  await p.waitForTimeout(500);
  R.fullscreen.zoom = await ev(() => { const m = /translate\(([-\d.]+)px, ([-\d.]+)px\) scale\(([\d.]+)\)/.exec(document.getElementById('fp-image').style.transform); return m ? { x: +m[1], y: +m[2], s: +m[3] } : null; });
  // 方向键翻页
  await p.keyboard.press('ArrowRight');
  await p.waitForTimeout(450);
  R.fullscreen.afterNext = await ev(() => document.getElementById('dp-fname').textContent);
  await p.keyboard.press('Escape');
  await p.waitForTimeout(100);
  R.fullscreen.heroOnClose = await ev(() => document.querySelectorAll('.fp-hero').length);
  await p.waitForTimeout(600);
  R.fullscreen.closed = await ev(() => !document.getElementById('fp-overlay').classList.contains('open'));

  // 9) 快捷键：Ctrl+A 全选当前视图；Esc 取消；悬停+空格 打开快速预览，再空格关闭
  await p.mouse.move(700, 600);
  await p.keyboard.press('Control+a');
  await p.waitForTimeout(300);
  R.keys = { ctrlA: await ev(() => Number(document.getElementById('sel-num').textContent)) };
  await p.keyboard.press('Escape');
  await p.waitForTimeout(250);
  R.keys.afterEsc = await ev(() => document.getElementById('sel-bar').classList.contains('show'));
  const hc = await center('.grid .photo-card[data-id]:not(.stack-cell)');
  await p.mouse.move(hc.x, hc.y);
  await p.keyboard.press(' ');
  await p.waitForTimeout(500);
  R.keys.spaceOpen = await ev(() => document.getElementById('fp-overlay').classList.contains('open'));
  await p.keyboard.press(' ');
  await p.waitForTimeout(500);
  R.keys.spaceClose = await ev(() => !document.getElementById('fp-overlay').classList.contains('open'));

  // 10) 一键全选(废片)只选当前范围；深色模式切换无报错
  await click('#btn-select-bad');
  await p.waitForTimeout(300);
  R.selectAllBad = await ev(() => ({ n: Number(document.getElementById('sel-num').textContent), badTotal: Number(document.getElementById('cnt-bad').textContent) }));
  await ev(() => document.getElementById('sel-clear').click());
  await click('#btn-theme');
  await p.waitForTimeout(600);
  R.dark = await ev(() => document.documentElement.getAttribute('data-theme'));
  await p.screenshot({ path: 'D:\\数据\\AI\\Project\\shiguang\\scripts\\ui_probe\\out\\dark.png' });
  await click('#btn-theme');
  await p.waitForTimeout(300);
  R.errors = errors;
  R.badResponses = bad;
  await p.close();
  return R;
  } finally { await hb.close(); }
}
