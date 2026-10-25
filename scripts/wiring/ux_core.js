
  // ══════════ 2026-10 体验大修：动效 / 缩略图加载 / 布局动画 基础设施 ══════════
  // 弹簧曲线(与样式表 --spring-* 同源)：snappy=干脆几乎不过冲，bouncy=发牌/弹出的轻微回弹，
  // smooth=临界阻尼无过冲(收拢、淡出)。用 Web Animations 播放；不支持 linear() 的内核自动退回贝塞尔。
  const SPRING = {
    snappy: { duration: 443, easing: 'linear(0, 0.0132, 0.0478, 0.0976, 0.1575, 0.2233, 0.2919, 0.3608, 0.4284, 0.4931, 0.5541, 0.6108, 0.6629, 0.7102, 0.7528, 0.7908, 0.8244, 0.8538, 0.8795, 0.9016, 0.9206, 0.9368, 0.9504, 0.9618, 0.9713, 0.9791, 0.9854, 0.9905, 0.9946, 0.9977, 1.0001, 1.0019, 1.0032, 1.0041, 1.0046, 1.0049, 1.005, 1.005, 1.0048, 1.0046, 1.0043, 1.0039, 1.0036, 1.0032, 1.0029, 1.0026, 1.0023, 1.002, 1)' },
    bouncy: { duration: 535, easing: 'linear(0, 0.0117, 0.0434, 0.0902, 0.1479, 0.2131, 0.2827, 0.3542, 0.4257, 0.4955, 0.5625, 0.6255, 0.6842, 0.7379, 0.7866, 0.8301, 0.8686, 0.9021, 0.931, 0.9555, 0.976, 0.9929, 1.0064, 1.017, 1.0251, 1.031, 1.0349, 1.0373, 1.0383, 1.0383, 1.0374, 1.0358, 1.0338, 1.0314, 1.0288, 1.026, 1.0233, 1.0206, 1.0179, 1.0154, 1.0131, 1.011, 1.009, 1.0072, 1.0057, 1.0043, 1.0031, 1.0021, 1)' },
    smooth: { duration: 495, easing: 'linear(0, 0.0144, 0.0511, 0.1024, 0.1625, 0.2272, 0.2932, 0.3585, 0.4214, 0.4809, 0.5366, 0.588, 0.635, 0.6777, 0.7162, 0.7508, 0.7817, 0.8092, 0.8335, 0.855, 0.8739, 0.8906, 0.9051, 0.9179, 0.929, 0.9387, 0.9471, 0.9544, 0.9607, 0.9662, 0.971, 0.975, 0.9786, 0.9816, 0.9843, 0.9865, 0.9885, 0.9901, 0.9916, 0.9928, 0.9938, 0.9947, 0.9955, 0.9962, 0.9967, 0.9972, 0.9976, 0.998, 1)' },
  };
  const REDUCED_MOTION = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  function sgAnimate(node, frames, preset, extra) {
    if (!node || !node.animate) return null;
    const opts = Object.assign({ duration: preset.duration, easing: preset.easing }, extra || {});
    if (REDUCED_MOTION) { opts.duration = 1; opts.delay = 0; }
    try { return node.animate(frames, opts); }
    catch (e) {
      try { opts.easing = 'cubic-bezier(0.22, 1, 0.36, 1)'; return node.animate(frames, opts); }
      catch (e2) { return null; }
    }
  }
  // 界面偏好：改动时写回后端 prefs.json(pywebview 每次启动是全新无痕配置，localStorage 跨启动
  // 留不住)，启动时 app.py 写出 prefs.js 让首帧就拿到。读取先看本会话的 localStorage(本会话里
  // 最新的改动，页面若被重载也不会退回启动时的旧值)，没有再用 prefs.js 的启动值。
  const sgPrefs = {
    _v: Object.assign({}, window.__sgPrefs || {}),
    getItem(k) {
      try { const s = window.localStorage.getItem(k); if (s != null) return s; } catch (e) {}
      return Object.prototype.hasOwnProperty.call(this._v, k) ? this._v[k] : null;
    },
    setItem(k, v) {
      const s = String(v);
      if (this.getItem(k) === s) return;
      this._v[k] = s;
      try { window.localStorage.setItem(k, s); } catch (e) {}
      try { if (window.pywebview && window.pywebview.api && window.pywebview.api.set_pref) window.pywebview.api.set_pref(k, s); } catch (e) {}
    },
  };
  // 整页重绘(render)之后要跑的收尾(吸顶状态等)：后面的模块往里登记
  const afterRenderHooks = [];
  function sgEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  const CHECK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path transform="translate(-1.3,0)" d="M4 12l6 6L20 6"/></svg>';
  const LAYERS_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="14" height="14" rx="2.5"/><path d="M3 8v10a3 3 0 0 0 3 3h10"/></svg>';

  // ── 缩略图加载引擎 ─────────────────────────────────────────────
  // 以前：每次重绘都把所有缩略图清空、等懒加载重新挂上(展开/收起堆叠时整屏闪白)；浏览器还会
  // 排队去要已经划走的图，把眼前要看的挤在后面(快速滑动大片空白)。
  // 现在：① 本会话解码过的图记在 thumbLoaded，重绘时直接贴上，不闪；② 进入"视口±1.2屏"的才
  // 列入待加载，按离视口中心的距离排优先级，最多同时 6 张(=浏览器对同一主机的并发上限)，划走
  // 还没开始的直接作废；③ 解码完成才贴图并淡入，不会出现"一半一半刷出来"。
  const thumbLoaded = new Set();
  // 失败记时间、过期重试：浏览时拔卡又插回，图要能重新出来(不能本会话永久判死)
  const thumbFailed = new Map();   // url → 失败时刻
  const THUMB_RETRY_MS = 15000;
  function isThumbFailed(url) {
    const t = thumbFailed.get(url);
    if (t == null) return false;
    if (performance.now() - t > THUMB_RETRY_MS) { thumbFailed.delete(url); return false; }
    return true;
  }
  const thumbDims = new Map();     // url → [宽, 高]：全屏"从缩略图飞出"要用真实宽高比
  // 眼前(视口±1.2屏)还没出图的格子 → 它要的地址。格子出图/离开范围才移出(加载中也留着，
  // 这样才知道哪些在途请求已经"没人要了"，可以撤掉给眼前的让路)
  const thumbWanted = new Map();
  const thumbJobs = new Map();     // url → { img, spec(预取), aborted, unwantedSince }：在途请求
  const THUMB_MAX = 6;             // 同时在途上限(=浏览器对同一主机的并发连接数)
  let thumbActive = 0;
  // 淡入只给"画面静止时新到的图"、同时最多十几张：滚动中到的图直接出现(手机相册也是这样)。
  // 每个正在淡入的图都要单独合成，快速滑动时几十张一起淡入会把每帧拖到 40ms 以上。
  let thumbFading = 0;
  const THUMB_FADE_MAX = 16;
  function thumbPaint(node, url, fade) {
    node.style.setProperty('--img', `url("${url}")`);
    node._painted = url;
    if (fade && thumbFading < THUMB_FADE_MAX && performance.now() - scrollLastT > 180 && !node.classList.contains('is-loaded')) {
      thumbFading++;
      node.classList.add('fade-in');
      setTimeout(() => { node.classList.remove('fade-in'); thumbFading--; }, 260);
    }
    node.classList.add('is-loaded');
    node.classList.remove('is-failed');
    if (node.dataset.thumb === url) {
      node.removeAttribute('data-thumb');
      thumbIO.unobserve(node);
      thumbWanted.delete(node);
    }
  }
  // 发起一个请求。撤掉(abort)的请求不算失败：格子回到"想要"状态，之后照常再要
  function thumbStart(url, spec) {
    const img = new Image();
    img.decoding = 'async';
    const job = { img, spec: !!spec, aborted: false, unwantedSince: 0 };
    thumbJobs.set(url, job);
    thumbActive++;
    img.src = url;
    img.decode().then(() => 'ok', () => (img.complete && img.naturalWidth > 0 ? 'ok' : 'fail')).then(res => {
      if (job.aborted) return;   // 撤掉时已经把名额还回去了
      thumbJobs.delete(url);
      thumbActive--;
      if (res === 'ok') { thumbLoaded.add(url); thumbFailed.delete(url); thumbDims.set(url, [img.naturalWidth, img.naturalHeight]); }
      else if (res === 'fail') thumbFailed.set(url, performance.now());
      thumbSettle(url, res === 'ok');
      thumbPump();
    });
  }
  function thumbAbort(url) {
    const j = thumbJobs.get(url);
    if (!j || j.aborted) return;
    j.aborted = true;
    // 名额当场还回去(不等浏览器回报——换掉 src 后 decode() 未必会结束，等它就会漏名额、越撤越堵)
    thumbJobs.delete(url);
    thumbActive--;
    j.img.src = '';   // 浏览器立刻断开这个请求，连接让给眼前要看的图
  }
  function thumbSettle(url, ok) {
    contentEl.querySelectorAll('.photo-thumb[data-thumb]').forEach(n => {
      if (n.dataset.thumb !== url) return;
      thumbWanted.delete(n);
      if (ok) thumbPaint(n, url, true);
      else {
        // 已用另一档的图垫着就保留它，不盖上"无法预览"
        if (!n.classList.contains('is-loaded')) n.classList.add('is-failed');
        n.removeAttribute('data-thumb');
        thumbIO.unobserve(n);
      }
    });
  }
  // 低优先级预取：鼠标停在折叠堆上/屏幕上的折叠堆，把它们藏着的成员图先取好——一展开就有图；
  // 快速划过、没来得及加载的也记在这里，眼前的都出图后再补。眼前有图要加载时，预取会被让掉。
  const thumbPre = [];
  function thumbPrefetch(urls, urgent) {
    const fresh = (urls || []).filter(u => u && !thumbLoaded.has(u) && !isThumbFailed(u)
      && !thumbJobs.has(u) && !thumbPre.includes(u));
    if (urgent) thumbPre.unshift(...fresh); else thumbPre.push(...fresh);
    thumbPump();
  }
  // 滚动方向/速度：快速往下甩时优先加载"即将进入屏幕"的(视口下方)，刚离开上沿的往后放
  let scrollVel = 0, scrollLastTop = 0, scrollLastT = 0;
  let thumbPumpTimer = 0;
  contentEl.addEventListener('scroll', () => {
    const now = performance.now();
    const st = contentEl.scrollTop;
    const v = (st - scrollLastTop) / Math.max(8, now - scrollLastT);   // px/ms
    scrollVel = scrollVel * 0.5 + v * 0.5;
    scrollLastTop = st;
    scrollLastT = now;
    // 停下来的那一刻立刻按新位置排一次(拖滚动条停住后不一定还有可见性变化来触发)
    clearTimeout(thumbPumpTimer);
    thumbPumpTimer = setTimeout(thumbPump, 150);
  }, { passive: true });
  let thumbFpEl = null;
  // 调度：眼前的永远最先。① 看大图时网格整体让路；② 拖滚动条/猛甩的那一瞬间路过的格子不值得开始
  // 加载，停下再说；③ 按离"视线焦点"的距离排序，前几名没在加载的立刻开始；④ 在途请求里已经没人要
  // 的(划走了 0.2 秒以上)或只是预取的，直接撤掉，把连接让给眼前的——以前划到一片空白处停住，连接
  // 全被刚才路过那段的请求占着，后端也还在按旧位置生成，眼前的就一直等。
  function thumbPump() {
    if (!thumbFpEl) thumbFpEl = document.getElementById('fp-overlay');
    if (thumbFpEl && thumbFpEl.classList.contains('open')) return;
    const now = performance.now();
    const moving = now - scrollLastT < 140;
    const vel = moving ? scrollVel : 0;
    if (moving && Math.abs(vel) > 3.5) return;   // 停下 150ms 后滚动监听会再叫一次
    const cr = contentEl.getBoundingClientRect();
    const lead = Math.max(-0.9, Math.min(0.9, vel * 400 / Math.max(1, cr.height)));   // 预判 0.4 秒后的位置
    const focus = cr.top + cr.height * (0.4 + lead);
    const cand = [];
    thumbWanted.forEach((url, node) => {
      if (!node.isConnected || node.dataset.thumb !== url) { thumbWanted.delete(node); return; }
      if (thumbLoaded.has(url)) { thumbPaint(node, url, false); return; }
      if (isThumbFailed(url)) { thumbSettle(url, false); return; }
      const r = node.getBoundingClientRect();
      const mid = (r.top + r.bottom) / 2;
      const leaving = (vel > 0.3 && r.bottom < cr.top) || (vel < -0.3 && r.top > cr.bottom);
      cand.push([Math.abs(mid - focus) + (leaving ? cr.height * 3 : 0), url]);
    });
    cand.sort((a, b) => a[0] - b[0]);
    const ranked = [];
    const seen = new Set();
    for (const [, url] of cand) if (!seen.has(url)) { seen.add(url); ranked.push(url); }
    const top = new Set(ranked.slice(0, THUMB_MAX * 2));
    // 撤掉没人要的/预取的在途请求(给眼前排着队的让位)
    const waiting = ranked.slice(0, THUMB_MAX).filter(u => !thumbJobs.has(u)).length;
    let recheck = false;
    thumbJobs.forEach((j, url) => {
      if (j.aborted) return;
      if (top.has(url)) { j.unwantedSince = 0; j.spec = false; return; }
      if (j.spec) { if (waiting > 0) { thumbAbort(url); thumbPre.unshift(url); } return; }
      if (!j.unwantedSince) { j.unwantedSince = now; recheck = true; }
      else if (now - j.unwantedSince > 200) thumbAbort(url);
      else recheck = true;
    });
    if (recheck) { clearTimeout(thumbPumpTimer); thumbPumpTimer = setTimeout(thumbPump, 220); }
    for (const url of ranked) {
      if (thumbActive >= THUMB_MAX) break;
      if (!thumbJobs.has(url)) thumbStart(url, false);
    }
    // 眼前的都在加载/加载完了，才轮到预取
    if (!ranked.some(u => !thumbJobs.has(u))) {
      while (thumbActive < THUMB_MAX && thumbPre.length) {
        const u = thumbPre.shift();
        if (thumbLoaded.has(u) || isThumbFailed(u) || thumbJobs.has(u)) continue;
        thumbStart(u, true);
      }
    }
  }
  const thumbIO = new IntersectionObserver(entries => {
    entries.forEach(en => {
      const node = en.target;
      const url = node.dataset.thumb;
      if (!url) { thumbIO.unobserve(node); return; }
      if (en.isIntersecting) thumbWanted.set(node, url);
      else if (thumbWanted.delete(node)) {
        // 一闪而过还没加载的：记进低优先级队列，眼前的都出图后再补——往回翻时就不再是空白
        if (!thumbPre.includes(url)) { thumbPre.push(url); if (thumbPre.length > 400) thumbPre.shift(); }   // 迷你密度一屏就上百张
      }
    });
    thumbPump();
  }, { root: contentEl, rootMargin: '120% 0px' });
  function thumbAttach(root) {
    const nodes = root.matches && root.matches('.photo-thumb[data-thumb]')
      ? [root] : Array.from(root.querySelectorAll('.photo-thumb[data-thumb]'));
    nodes.forEach(node => {
      const url = node.dataset.thumb;
      if (!url) { node.classList.add('is-failed'); return; }
      if (thumbLoaded.has(url)) { thumbPaint(node, url, false); return; }
      // 另一档(大/小)已经解码过：先垫上，等这一档到了再无缝换(切换密度时不出现空白)
      const alt = node.dataset.alt;
      if (alt && thumbLoaded.has(alt) && node._painted !== alt) thumbPaint(node, alt, false);
      if (isThumbFailed(url)) {
        if (!node.classList.contains('is-loaded')) node.classList.add('is-failed');
        node.removeAttribute('data-thumb');
      } else thumbIO.observe(node);
    });
  }
  function thumbReset() { thumbIO.disconnect(); thumbWanted.clear(); }

  // 网格缩略图分两档：512 与 256。小格子(迷你/紧凑、普通屏的标准密度)用 256——解码快约 4 倍、
  // 占内存少 4 倍，一屏上百张、快速滑动也跟得上；大格子/高分屏用 512 保证清晰。
  let thumbTier = 512;
  function thumbUrlFor(p, tier) {
    const u = (p && p.thumbnail) || '';
    return (tier || thumbTier) === 256 ? u.replace('/thumb_cache/', '/thumb256_cache/') : u;
  }
  function pickThumbTier() {
    if (!contentEl.clientWidth) return thumbTier;   // 窗口最小化/在托盘里：量不到宽度，保持原档
    const d = document.documentElement.getAttribute('data-density') || 'comfortable';
    const minCol = { mini: 84, compact: 120, comfortable: 168, large: 260 }[d] || 168;
    const gap = d === 'mini' ? 4 : d === 'compact' ? 12 : 16;
    const w = Math.max(200, contentEl.clientWidth - 48);
    const cols = Math.max(1, Math.floor((w + gap) / (minCol + gap)));
    const cell = (w - (cols - 1) * gap) / cols;
    thumbTier = cell * (window.devicePixelRatio || 1) <= 270 ? 256 : 512;
    return thumbTier;
  }
  // 密度/窗口宽度变了导致该用另一档：就地换地址(已解码的另一档先垫着)，不整页重绘
  function retierThumbs() {
    const before = thumbTier;
    if (pickThumbTier() === before) return;
    thumbReset();
    const other = thumbTier === 256 ? 512 : 256;
    contentEl.querySelectorAll('.photo-thumb').forEach(node => {
      const card = node.closest('[data-id], [data-cover]');
      if (!card || card.closest('.sg-ghost')) return;
      const p = PHOTO_BY_ID.get(Number(card.dataset.id || card.dataset.cover));
      if (!p) return;
      const url = thumbUrlFor(p);
      node.dataset.alt = thumbUrlFor(p, other);
      if (node._painted === url) { node.removeAttribute('data-thumb'); return; }
      node.dataset.thumb = url;
    });
    thumbAttach(contentEl);
  }

  // ── 布局动画(FLIP)：只量/只动视口附近的元素，上千张的图库也不卡 ──────────────
  const FLIP_MARGIN = 220;
  function inView(r, cr, margin) { return r.bottom >= cr.top - margin && r.top <= cr.bottom + margin; }
  function captureLayout() {
    const cr = contentEl.getBoundingClientRect();
    const m = new Map();
    contentEl.querySelectorAll('[data-key]').forEach(n => {
      const r = n.getBoundingClientRect();
      if (inView(r, cr, FLIP_MARGIN)) m.set(n.dataset.key, r);
    });
    return m;
  }
  // 位置变了的元素从旧位置弹簧滑到新位置(动 translate 属性，不碰 transform——不会和悬停/选中的
  // 抬起效果打架)；enter=true 时新出现的元素淡入放大。被吸顶的组头不参与(它本来就"钉"在那)。
  function flipFrom(before, exclude, enter) {
    const cr = contentEl.getBoundingClientRect();
    contentEl.querySelectorAll('[data-key]').forEach(n => {
      const key = n.dataset.key;
      if (exclude && exclude.has(key)) return;
      const r = n.getBoundingClientRect();
      if (!inView(r, cr, FLIP_MARGIN)) return;
      if (n.classList.contains('group-header') && r.top <= cr.top + 1) return;
      const b = before.get(key);
      if (!b) {
        if (enter && r.bottom > cr.top && r.top < cr.bottom) {
          sgAnimate(n, [{ opacity: 0, scale: '0.9' }, { opacity: 1, scale: '1' }], SPRING.bouncy);
        }
        return;
      }
      const dx = b.left - r.left, dy = b.top - r.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      // 正在让位滑动的卡不接收点击：换行的卡会斜着滑过别的卡上方，快速双击时第二下会落到它身上
      n.style.pointerEvents = 'none';
      const a = sgAnimate(n, [{ translate: `${dx}px ${dy}px` }, { translate: '0px 0px' }], SPRING.snappy);
      const clear = () => { n.style.pointerEvents = ''; };
      if (a) { a.onfinish = clear; a.oncancel = clear; } else clear();
    });
  }
  function ghostLayer() {
    let gl = contentEl.querySelector(':scope > .sg-ghost-layer');
    if (!gl) { gl = document.createElement('div'); gl.className = 'sg-ghost-layer'; contentEl.appendChild(gl); }
    return gl;
  }
  // 把一张卡在当前位置复制成"鬼影"(真身随后被移除/重建)，用来做飞回、淡出这类离场动画
  function makeGhost(node, r, cr) {
    const g = node.cloneNode(true);
    g.classList.add('sg-ghost');
    g.removeAttribute('data-key');
    g.removeAttribute('data-id');
    g.style.position = 'absolute';
    g.style.left = (r.left - cr.left + contentEl.scrollLeft) + 'px';
    g.style.top = (r.top - cr.top + contentEl.scrollTop) + 'px';
    g.style.width = r.width + 'px';
    g.style.height = r.height + 'px';
    g.style.margin = '0';
    g._rect = r;
    ghostLayer().appendChild(g);
    return g;
  }
  // 通用"带动画的整页重绘"：删除/改档/撤销等会让照片增减的操作用它——消失的原地缩小淡出，
  // 留下的平滑挪到新位置，新回来的弹出。全屏/对比打开时网格看不见，直接重绘不浪费动画。
  function animateLayoutChange(mutator) {
    const fpOpen = document.getElementById('fp-overlay');
    if (REDUCED_MOTION || (fpOpen && fpOpen.classList.contains('open'))) { mutator(); return; }
    const before = captureLayout();
    const oldNodes = new Map();
    contentEl.querySelectorAll('[data-key]').forEach(n => { if (before.has(n.dataset.key)) oldNodes.set(n.dataset.key, n); });
    mutator();
    const cr = contentEl.getBoundingClientRect();
    const now = new Set();
    contentEl.querySelectorAll('[data-key]').forEach(n => now.add(n.dataset.key));
    flipFrom(before, null, true);
    before.forEach((r, key) => {
      if (now.has(key) || !inView(r, cr, 0)) return;
      const old = oldNodes.get(key);
      if (!old || !(old.classList.contains('photo-card') || old.classList.contains('stack-card'))) return;
      const g = makeGhost(old, r, cr);
      const a = sgAnimate(g, [{ opacity: 1, scale: '1' }, { opacity: 0, scale: '0.82' }], SPRING.smooth, { duration: 300 });
      if (a) a.onfinish = a.oncancel = () => g.remove(); else g.remove();
    });
  }
