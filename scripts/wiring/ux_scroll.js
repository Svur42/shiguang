  // ══════════ 吸顶组头 / 拖滚动条时的时间刻度 / 网格缩放 ══════════
  // ── 吸顶：只给"此刻真正吸住"的那个组头加 is-stuck(毛玻璃 + 底部细线，与工具栏连成一块) ──
  // ── 时间刻度：鼠标移到右侧滚动条附近(或按住滚动条)时出现。轨道里每个拍摄日期一个小圆点(位置=
  //    拖到这里就是这一天)，旁边一列日期——每个日期都写出来，挤的地方自动错开、用细线连回自己的圆点；
  //    日期太多一屏放不下时按月份显示。点日期，页面平滑滚到那一天(顶上的日期随之切换)；当前那天高亮。
  const rulerEl = document.createElement('div');
  rulerEl.className = 'sg-ruler';
  (document.querySelector('.main') || document.body).appendChild(rulerEl);
  let stuckHeader = null;
  let rulerOn = false;       // 正在显示
  let rulerDrag = false;     // 正按着滚动条
  let rulerHover = false;    // 鼠标在刻度/滚动条附近
  let rulerHideTimer = 0;
  let rulerMarks = [];       // [{ secs: [这一行对应的日期组...], el, dot }]
  let scrollRaf = 0;
  const RULER_GAP = 22;      // 两行日期至少隔这么多像素
  // 当前视口顶部落在哪个日期组：按 offsetTop 二分(滚动时布局是干净的，读 offsetTop 不触发重排)
  function currentSection() {
    const secs = contentEl.children;
    let lo = 0, hi = secs.length - 1, found = null;
    const y = contentEl.scrollTop + 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const s = secs[mid];
      if (!s.classList.contains('day-group')) { hi = mid - 1; continue; }
      if (s.offsetTop <= y) { found = s; lo = mid + 1; } else hi = mid - 1;
    }
    return found;
  }
  function updateStuck(sec) {
    const h = sec && contentEl.scrollTop > sec.offsetTop + 0.5 ? sec.firstElementChild : null;
    if (h === stuckHeader) return;
    if (stuckHeader) stuckHeader.classList.remove('is-stuck');
    stuckHeader = h && h.classList.contains('group-header') ? h : null;
    if (stuckHeader) stuckHeader.classList.add('is-stuck');
  }
  // 拖动拇指时，"某个组的开头滚到顶上"对应的拇指中心位置(与样式里拇指最短 44px 一致)
  function thumbCenterFor(scrollTop) {
    const ch = contentEl.clientHeight, sh = contentEl.scrollHeight;
    const thumbH = Math.max(44, ch * ch / Math.max(1, sh));
    const ratio = Math.min(1, Math.max(0, scrollTop / Math.max(1, sh - ch)));
    return ratio * (ch - thumbH) + thumbH / 2;
  }
  function monthOf(title) {
    const m = /(?:(\d{4})年)?(\d{1,2})月/.exec(title || '');
    return m ? (m[1] ? `${m[1]}年${+m[2]}月` : `${+m[2]}月`) : (title || '');
  }
  function buildRuler() {
    const secs = Array.from(contentEl.children).filter(s => s.classList.contains('day-group'));
    const H = contentEl.clientHeight;
    rulerEl.style.top = contentEl.offsetTop + 'px';
    rulerEl.style.height = H + 'px';
    const maxScroll = contentEl.scrollHeight - contentEl.clientHeight;
    // 放得下就每天一行；放不下就按月合并(点月份跳到这个月的第一天)
    let groups = secs.map(sec => ({ secs: [sec], label: sec.dataset.title || '' }));
    if (groups.length * RULER_GAP > H - 16) {
      const byMonth = [];
      secs.forEach(sec => {
        const k = monthOf(sec.dataset.title);
        const last = byMonth[byMonth.length - 1];
        if (last && last.label === k) last.secs.push(sec); else byMonth.push({ secs: [sec], label: k });
      });
      groups = byMonth;
    }
    groups.forEach(g => { g.ideal = thumbCenterFor(Math.min(g.secs[0].offsetTop, maxScroll)); });
    // 一维排布：先按理想位置往下挤开，再从底部往回收——都在轨道范围内、互不重叠
    const top = 10, bottom = H - 10;
    let y = -1e9;
    groups.forEach(g => { g.y = Math.max(g.ideal, y + RULER_GAP, top); y = g.y; });
    y = 1e9;
    for (let i = groups.length - 1; i >= 0; i--) { groups[i].y = Math.min(groups[i].y, y - RULER_GAP, bottom); y = groups[i].y; }
    groups.forEach(g => { g.y = Math.max(g.y, top); });
    const W = 140, dotX = W - 7, lblX = W - 22;
    let svg = `<svg class="sg-ruler-links" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`;
    let html = '';
    groups.forEach((g, i) => {
      if (Math.abs(g.y - g.ideal) > 1.5) {
        const y1 = g.y.toFixed(1), y2 = g.ideal.toFixed(1);
        svg += `<path d="M${lblX + 2} ${y1} C ${lblX + 9} ${y1}, ${dotX - 8} ${y2}, ${dotX - 3} ${y2}"/>`;
      }
      html += `<i class="sg-ruler-dot" data-i="${i}" style="top:${g.ideal.toFixed(1)}px"></i>`
        + `<button class="sg-ruler-mark" data-i="${i}" style="top:${g.y.toFixed(1)}px" title="跳到 ${sgEsc(g.label)}">${sgEsc(g.label)}</button>`;
    });
    rulerEl.innerHTML = svg + '</svg>' + html;
    rulerMarks = groups.map((g, i) => ({
      secs: g.secs,
      el: rulerEl.querySelector(`.sg-ruler-mark[data-i="${i}"]`),
      dot: rulerEl.querySelector(`.sg-ruler-dot[data-i="${i}"]`),
    }));
  }
  function updateRuler(sec) {
    if (!rulerOn) return;
    // 滚到底了：最后几天短得滚不到顶上，此时高亮最后一天(点最后一个日期后亮的就是它)
    if (contentEl.scrollTop >= contentEl.scrollHeight - contentEl.clientHeight - 2 && rulerMarks.length) {
      sec = rulerMarks[rulerMarks.length - 1].secs[0];
    }
    rulerMarks.forEach(m => {
      const on = m.secs.includes(sec);
      m.el.classList.toggle('current', on);
      m.dot.classList.toggle('current', on);
    });
  }
  function showRuler() {
    clearTimeout(rulerHideTimer);
    if (!contentEl.querySelector(':scope > .day-group')) return;
    if (!rulerOn) { rulerOn = true; buildRuler(); rulerEl.classList.add('show'); }
    updateRuler(currentSection());
  }
  function maybeHideRuler() {
    if (rulerDrag || rulerHover) return;
    clearTimeout(rulerHideTimer);
    rulerHideTimer = setTimeout(() => {
      if (rulerDrag || rulerHover) return;
      rulerOn = false;
      rulerEl.classList.remove('show');
    }, 450);
  }
  function onScrollFrame() {
    scrollRaf = 0;
    const sec = currentSection();
    updateStuck(sec);
    updateRuler(sec);
  }
  contentEl.addEventListener('scroll', () => { if (!scrollRaf) scrollRaf = requestAnimationFrame(onScrollFrame); }, { passive: true });
  // 鼠标移到右侧滚动条附近(最右 26px)就出现；离开刻度和这一条就淡出
  contentEl.addEventListener('mousemove', (e) => {
    const r = contentEl.getBoundingClientRect();
    const near = e.clientX >= r.right - 26;
    if (near && !rulerHover) { rulerHover = true; showRuler(); }
    else if (!near && rulerHover && !rulerEl.matches(':hover')) { rulerHover = false; maybeHideRuler(); }
  });
  contentEl.addEventListener('mouseleave', () => { if (!rulerEl.matches(':hover')) { rulerHover = false; maybeHideRuler(); } });
  rulerEl.addEventListener('mouseenter', () => { rulerHover = true; clearTimeout(rulerHideTimer); });
  rulerEl.addEventListener('mouseleave', () => { rulerHover = false; maybeHideRuler(); });
  // 在刻度上滚滚轮照样滚照片
  rulerEl.addEventListener('wheel', (e) => {
    if (e.ctrlKey) return;
    cancelAnimationFrame(jumpRaf);
    contentEl.scrollTop += e.deltaY * (e.deltaMode === 1 ? 33 : 1);
    e.preventDefault();
  }, { passive: false });
  // 按住滚动条拖动时也显示
  contentEl.addEventListener('pointerdown', (e) => {
    if (e.offsetX < contentEl.clientWidth) return;
    cancelAnimationFrame(jumpRaf);
    rulerDrag = true;
    showRuler();
  });
  const endDrag = () => { if (!rulerDrag) return; rulerDrag = false; maybeHideRuler(); };
  window.addEventListener('pointerup', endDrag);
  window.addEventListener('pointercancel', endDrag);
  window.addEventListener('blur', () => { endDrag(); rulerHover = false; maybeHideRuler(); });
  // 点日期：平滑地滚过去(缓入缓出，距离越远时间略长)，而不是一下跳过去
  let jumpRaf = 0;
  function smoothScrollTo(target) {
    cancelAnimationFrame(jumpRaf);
    const from = contentEl.scrollTop;
    const to = Math.max(0, Math.min(target, contentEl.scrollHeight - contentEl.clientHeight));
    const dist = to - from;
    if (Math.abs(dist) < 1) return;
    const dur = REDUCED_MOTION ? 1 : Math.min(720, 320 + Math.abs(dist) / 25);
    const t0 = performance.now();
    const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
    const step = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      contentEl.scrollTop = from + dist * ease(t);
      if (t < 1) jumpRaf = requestAnimationFrame(step);
    };
    jumpRaf = requestAnimationFrame(step);
  }
  // 用户自己动了滚轮：中断正在进行的平滑滚动
  contentEl.addEventListener('wheel', () => cancelAnimationFrame(jumpRaf), { passive: true });
  rulerEl.addEventListener('click', (e) => {
    const b = e.target.closest('.sg-ruler-mark');
    if (!b) return;
    const m = rulerMarks[Number(b.dataset.i)];
    if (!m) return;
    sgAnimate(b, [{ scale: '0.9' }, { scale: '1' }], SPRING.bouncy, { duration: 360 });
    smoothScrollTo(m.secs[0].offsetTop + 1);   // +1：让这一组的组头正好吸在顶上
  });
  // 整页重绘后(切档位/删除等)吸顶状态要重算
  afterRenderHooks.push(() => { stuckHeader = null; if (rulerOn) buildRuler(); onScrollFrame(); });

  // ── 网格缩放：Ctrl+滚轮 / 触控板双指捏合 / Ctrl+加减号，在 迷你·紧凑·标准·大图 之间切换 ──
  // 以光标下那张照片为锚点(缩放后它还在原来的位置)，像相册里双指缩放那样。
  const DENSITIES = ['mini', 'compact', 'comfortable', 'large'];
  function currentDensity() { return document.documentElement.getAttribute('data-density') || 'comfortable'; }
  // 切换密度的过渡(用户要求)：点工具栏的 迷你/紧凑/标准/大图 时，画面跟着滑块的方向走——往右切
  // (标准→大图)旧排版向左滑出、新排版从右边滑进来；往左切反过来。Ctrl+滚轮/捏合缩放则是以光标
  // 为中心的缩放过渡。用浏览器的视图过渡(View Transitions)：先给旧画面拍快照，再换排版，新旧两张
  // 同时动——不再"一下变白虚化再一下出来"。
  function setDensity(d, anchorX, anchorY, mode) {
    const cur = currentDensity();
    if (!DENSITIES.includes(d) || d === cur) return;
    const dir = DENSITIES.indexOf(d) - DENSITIES.indexOf(cur);
    const cr = contentEl.getBoundingClientRect();
    let anchor = null;
    if (anchorY != null) {
      const hit = document.elementFromPoint(anchorX, anchorY);
      anchor = hit && hit.closest('#content .photo-card[data-id], #content .stack-card');
    }
    if (!anchor) {
      for (const c of contentEl.querySelectorAll('.photo-card[data-id], .stack-card')) {
        if (c.getBoundingClientRect().bottom > cr.top + 60) { anchor = c; break; }
      }
    }
    const off = anchor ? anchor.getBoundingClientRect().top - cr.top : 0;
    const zoom = mode === 'zoom';
    const root = document.documentElement;
    if (zoom) {
      const r = anchor ? anchor.getBoundingClientRect() : cr;
      root.style.setProperty('--vt-ox', `${r.left + r.width / 2 - cr.left}px`);
      root.style.setProperty('--vt-oy', `${r.top + r.height / 2 - cr.top}px`);
    }
    const update = () => {
      document.querySelectorAll('#density-toggle .seg-item').forEach(b => b.classList.toggle('active', b.dataset.density === d));
      applyDensity(d);
      densitySeg.sync();
      if (anchor && anchor.isConnected) contentEl.scrollTop += anchor.getBoundingClientRect().top - cr.top - off;
    };
    if (REDUCED_MOTION) { update(); return; }
    // 只动滚动区里的内容(眼前那几个日期组)，滚动区本身和它的滚动条不动——以前整块拍快照一起滑，
    // 右边的滚动条也跟着滑走了。旧排版先往一侧淡出滑走，换好排版再从另一侧滑进来(与工具栏滑块同向)。
    const visibleSecs = () => {
      const r0 = contentEl.getBoundingClientRect();
      return Array.from(contentEl.children).filter(s => {
        if (!s.classList.contains('day-group') && !s.classList.contains('empty-state')) return false;
        const r = s.getBoundingClientRect();
        return r.bottom > r0.top && r.top < r0.bottom;
      });
    };
    densitySeq++;
    const seq = densitySeq;
    const dx = zoom ? 0 : (dir > 0 ? -1 : 1);
    const outFrames = zoom
      ? [{ opacity: 1, scale: '1' }, { opacity: 0, scale: dir > 0 ? '1.06' : '0.94' }]
      : [{ opacity: 1, translate: '0px 0px' }, { opacity: 0, translate: `${dx * 64}px 0px` }];
    const inFrames = zoom
      ? [{ opacity: 0, scale: dir > 0 ? '0.94' : '1.06' }, { opacity: 1, scale: '1' }]
      : [{ opacity: 0, translate: `${-dx * 88}px 0px` }, { opacity: 1, translate: '0px 0px' }];
    const origin = sec => {
      if (!zoom) return;
      const r = sec.getBoundingClientRect();
      const ox = parseFloat(root.style.getPropertyValue('--vt-ox')) || r.width / 2;
      const oy = (parseFloat(root.style.getPropertyValue('--vt-oy')) || 0) + cr.top - r.top;
      sec.style.transformOrigin = `${ox}px ${oy}px`;
    };
    const olds = visibleSecs();
    const anims = olds.map(sec => { origin(sec); return sgAnimate(sec, outFrames, { duration: 170, easing: 'cubic-bezier(0.4, 0, 1, 1)' }, { fill: 'forwards' }); });
    densityOut.push(...anims.filter(Boolean));
    const swap = () => {
      if (seq !== densitySeq) return;   // 又切了一次：以最新那次为准
      densityOut.forEach(a => a.cancel());   // 连点几次时，之前没来得及换的淡出也一并撤掉
      densityOut = [];
      update();
      visibleSecs().forEach(sec => { origin(sec); sgAnimate(sec, inFrames, SPRING.snappy, { duration: 480 }); });
    };
    if (anims[0]) anims[0].onfinish = swap; else swap();
  }
  let densitySeq = 0;
  let densityOut = [];
  function sgSwitchDensity(d) { setDensity(d, null, null, 'slide'); }
  function stepDensity(dir, x, y) {
    const i = DENSITIES.indexOf(currentDensity());
    setDensity(DENSITIES[Math.max(0, Math.min(DENSITIES.length - 1, (i < 0 ? 2 : i) + dir))], x, y, x != null ? 'zoom' : 'slide');
  }
  let zoomAcc = 0, zoomAt = 0, zoomLockUntil = 0;
  contentEl.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();   // 不让 WebView 把整个界面放大
    const now = performance.now();
    if (now < zoomLockUntil) return;   // 刚跳过一级：这一下手势剩下的滚动不再连跳
    if (now - zoomAt > 400) zoomAcc = 0;
    zoomAt = now;
    zoomAcc += e.deltaY * (e.deltaMode === 1 ? 33 : 1);
    if (Math.abs(zoomAcc) < 60) return;
    stepDensity(zoomAcc < 0 ? 1 : -1, e.clientX, e.clientY);
    zoomAcc = 0;
    zoomLockUntil = now + 250;   // 一次手势只跳一级，避免一下子从迷你冲到大图
  }, { passive: false });
  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key;
    if (!['=', '+', '-', '_', '0'].includes(k)) return;
    e.preventDefault();   // 任何时候都不让 WebView 把整个界面放大/缩小/复位(桌面软件里误触很突兀)
    if (fpOverlay.classList.contains('open') || compareOverlay.classList.contains('open')) return;
    if (document.querySelector('.modal-backdrop:not(.hidden)')) return;
    if (k === '=' || k === '+') stepDensity(1);
    else if (k === '-' || k === '_') stepDensity(-1);
  });
  // 鼠标在侧栏/工具栏上按 Ctrl+滚轮也不缩放整个界面(网格区和全屏里各有自己的缩放)
  document.addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
  // 密度/窗口宽度变化：网格缩略图可能要换档(256 ↔ 512)
  document.addEventListener('sg-density', () => retierThumbs());
  let retierTimer = 0;
  window.addEventListener('resize', () => { clearTimeout(retierTimer); retierTimer = setTimeout(retierThumbs, 200); });

