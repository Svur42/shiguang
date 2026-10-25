  // ══════════ 全屏细看(2026-10)：缩放跟手 + 从缩略图飞出/飞回 + 翻页过渡 ══════════
  // 缩放：滚轮按光标所在位置放大(盯着鸟眼睛滚，鸟眼睛不会跑出画面)；每帧向目标值指数逼近，
  // 滚轮一格一格也是连续顺滑的；双击图片=放大到光标处 / 再双击回到全图。
  let fpZoomTarget = 1;
  let fpPanTarget = { x: 0, y: 0 };
  let fpAnimRaf = 0;
  function fpApplyLive() {
    fpImage.classList.add('fp-live');
    fpImage.style.transform = `translate(${fpPan.x}px, ${fpPan.y}px) scale(${fpZoom * (fpFit || 1)}) rotate(${fpRotation || 0}deg)`;
    fpImage.classList.toggle('zoomed', fpZoom > 1.001);
    el('#fp-hint').textContent = fpZoom > 1.001 ? zoomHint(fpZoom) : '滚轮缩放放大 · 可拖动查看';
  }
  function fpCancelAnim() {
    if (fpAnimRaf) { cancelAnimationFrame(fpAnimRaf); fpAnimRaf = 0; }
    fpImage.classList.remove('fp-live');
  }
  function fpKick() {
    if (fpAnimRaf) return;
    let last = performance.now();
    const step = (now) => {
      const dt = Math.min(48, now - last);
      last = now;
      const k = 1 - Math.pow(0.7, dt / 16.7);   // 帧率无关：60fps 下每帧追上剩余距离的 30%
      fpZoom += (fpZoomTarget - fpZoom) * k;
      fpPan = { x: fpPan.x + (fpPanTarget.x - fpPan.x) * k, y: fpPan.y + (fpPanTarget.y - fpPan.y) * k };
      const done = Math.abs(fpZoomTarget - fpZoom) < 0.001
        && Math.abs(fpPanTarget.x - fpPan.x) < 0.25 && Math.abs(fpPanTarget.y - fpPan.y) < 0.25;
      if (done) { fpZoom = fpZoomTarget; fpPan = { x: fpPanTarget.x, y: fpPanTarget.y }; }
      fpApplyLive();
      if (done) { fpAnimRaf = 0; fpImage.classList.remove('fp-live'); }
      else fpAnimRaf = requestAnimationFrame(step);
    };
    fpAnimRaf = requestAnimationFrame(step);
  }
  function fpZoomAt(clientX, clientY, z1) {
    const rect = fpStage.getBoundingClientRect();
    const cx = clientX - (rect.left + rect.width / 2);
    const cy = clientY - (rect.top + rect.height / 2);
    if (!fpAnimRaf) { fpZoomTarget = fpZoom; fpPanTarget = { x: fpPan.x, y: fpPan.y }; }
    const z0 = fpZoomTarget;
    z1 = Math.min(16, Math.max(1, z1));
    // 让光标下的那个像素保持不动：pan' = c - (c - pan) * z1/z0
    const pan = { x: cx - (cx - fpPanTarget.x) * (z1 / z0), y: cy - (cy - fpPanTarget.y) * (z1 / z0) };
    fpZoomTarget = z1;
    fpPanTarget = z1 <= 1.0001 ? { x: 0, y: 0 } : clampFpPan(z1, pan);
    fpKick();
    if (z1 > 1.15) ensureFpOriginal(fpPhotoId);   // 一放大就换原图(相机内嵌的全尺寸 JPEG)，看清像素/对焦
  }
  fpStage.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!fpAnimRaf) fpZoomTarget = fpZoom;
    const px = e.deltaY * (e.deltaMode === 1 ? 33 : 1);   // 行模式滚轮换算成像素
    fpZoomAt(e.clientX, e.clientY, fpZoomTarget * Math.exp(-px * 0.002));
  }, { passive: false });
  fpStage.addEventListener('dblclick', (e) => {
    if (e.target.closest('button')) return;
    fpZoomAt(e.clientX, e.clientY, (fpZoomTarget > 1.05 || fpZoom > 1.05) ? 1 : 2.5);
  });

  // ── 从缩略图"飞出"/飞回(苹果相册的标志性过渡) ──
  function fpRotOf(p) { return ((((p && p.rotation) || 0) % 360) + 360) % 360; }
  function fpFitRect(iw, ih) {
    const s = fpStage.getBoundingClientRect();
    const k = Math.min(s.width / iw, s.height / ih);
    const w = iw * k, h = ih * k;
    return { left: s.left + (s.width - w) / 2, top: s.top + (s.height - h) / 2, width: w, height: h };
  }
  // hero 的盒子=全屏里图片的最终位置；起始时用 translate+scale 缩到缩略图上，再用 clip-path
  // 裁成卡片的取景(卡片是 3:2 裁切)，然后弹簧展开到全图——裁切和尺寸一起连续变化，没有跳变。
  function heroFly(url, from, to, reverse, onDone) {
    const hero = document.createElement('div');
    hero.className = 'fp-hero';
    hero.style.left = to.left + 'px';
    hero.style.top = to.top + 'px';
    hero.style.width = to.width + 'px';
    hero.style.height = to.height + 'px';
    hero.style.backgroundImage = `url("${url}")`;
    document.body.appendChild(hero);
    const s = Math.max(from.width / to.width, from.height / to.height);
    const ix = Math.max(0, (to.width - from.width / s) / 2);
    const iy = Math.max(0, (to.height - from.height / s) / 2);
    const dx = (from.left + from.width / 2) - (to.left + to.width / 2);
    const dy = (from.top + from.height / 2) - (to.top + to.height / 2);
    const small = { translate: `${dx}px ${dy}px`, scale: String(s), clipPath: `inset(${iy}px ${ix}px round ${10 / s}px)` };
    const big = { translate: '0px 0px', scale: '1', clipPath: 'inset(0px 0px round 0px)' };
    const a = sgAnimate(hero, reverse ? [big, small] : [small, big], SPRING.snappy, { duration: reverse ? 400 : 460, fill: 'forwards' });
    const done = () => { hero.remove(); if (onDone) onDone(); };
    if (a) { a.onfinish = done; a.oncancel = done; } else done();
  }
  // 缩略图两档(256/512)宽高比相同，哪档量到过都能用
  function fpDimsOf(p) { return thumbDims.get(p.thumbnail) || thumbDims.get(thumbUrlFor(p, 256)); }
  function heroOpen(thumbEl, p) {
    if (REDUCED_MOTION || !thumbEl || !thumbEl.classList.contains('is-loaded') || fpRotOf(p)) return;
    const dims = fpDimsOf(p);
    const from = thumbEl.getBoundingClientRect();
    if (!dims || from.width < 4) return;
    fpOverlay.classList.add('hero-flying');
    const to = fpFitRect(dims[0], dims[1]);
    thumbEl.style.visibility = 'hidden';
    heroFly(thumbEl._painted || p.thumbnail, from, to, false, () => {
      thumbEl.style.visibility = '';
      fpOverlay.classList.remove('hero-flying');
    });
  }
  function heroClose(p) {
    setTimeout(() => { thumbPump(); scheduleWarm(); }, 0);   // 看大图时网格让了路，关掉后接着加载
    if (REDUCED_MOTION || !p || fpZoom > 1.02 || fpRotOf(p)) return;
    const thumb = contentEl.querySelector(`.photo-card[data-id="${p.id}"] .photo-thumb, .stack-card-thumb[data-cover="${p.id}"] .photo-thumb`);
    if (!thumb || !thumb.classList.contains('is-loaded')) return;
    const cr = contentEl.getBoundingClientRect();
    const to = thumb.getBoundingClientRect();
    if (to.bottom < cr.top + 8 || to.top > cr.bottom - 8) return;   // 卡片不在屏幕上：普通淡出
    const dims = fpDimsOf(p);
    if (!dims) return;
    const url = fpPreviewUrl.get(p.id) || thumb._painted || p.thumbnail;   // 飞回用屏幕预览(原图太大，不拿来做动画)
    fpOverlay.classList.add('hero-flying');
    thumb.style.visibility = 'hidden';
    heroFly(url, to, fpFitRect(dims[0], dims[1]), true, () => {
      thumb.style.visibility = '';
      fpOverlay.classList.remove('hero-flying');
    });
  }

  // ── 上一张/下一张：轻微滑入；到头了"橡皮筋"回弹一下 ──
  function fpGo(delta) {
    const idx = currentVisibleIds.indexOf(fpPhotoId);
    const j = idx + delta;
    if (idx === -1 || j < 0 || j >= currentVisibleIds.length) {
      sgAnimate(fpImage, [{ translate: '0px 0px' }, { translate: `${-delta * 22}px 0px`, offset: 0.3 }, { translate: '0px 0px' }],
        SPRING.bouncy, { duration: 460 });
      return;
    }
    openFullscreenPreview(currentVisibleIds[j]);
    sgAnimate(fpImage, [{ opacity: 0.3, translate: `${delta * 46}px 0px` }, { opacity: 1, translate: '0px 0px' }],
      SPRING.snappy, { duration: 380 });
  }
  // 全屏里删除当前这张：直接换到下一张(没有下一张就上一张)，而不是退出全屏
  function fpDeleteCurrent() {
    const id = fpPhotoId;
    if (id == null) return;
    const idx = currentVisibleIds.indexOf(id);
    const nextId = idx < 0 ? null
      : (currentVisibleIds[idx + 1] != null ? currentVisibleIds[idx + 1] : currentVisibleIds[idx - 1]);
    trashPhoto(id);
    if (nextId != null && currentVisibleIds.includes(nextId)) {
      openFullscreenPreview(nextId);
      sgAnimate(fpImage, [{ opacity: 0, scale: '0.94' }, { opacity: 1, scale: '1' }], SPRING.snappy, { duration: 380 });
    } else {
      closeFullscreenPreview();
    }
  }


  // ── 全屏清晰度：缩略图 → 屏幕预览 → 原图，逐级换清，只升不降 ──
  // 第 0 级：网格里已解码的缩略图，瞬间铺满(会有点糊)；
  // 第 1 级：2560 屏幕预览(后端从相机内嵌的全尺寸 JPEG 缩出)，铺满屏幕时与原图看不出差别；
  // 第 2 级：原图——相机写在 RAW 里的全尺寸 JPEG 原样，不再重新压缩；一放大就换上(4K 屏直接用它)。
  // 以前的问题：晚到的 2560 会把已换上的原图盖回去(放大后又变糊)；某次加载失败不重试，只能切到
  // 别的照片再切回来才变清楚；预览要等双击后才开始生成。
  let fpShown = { id: null, level: -1, url: '' };
  const fpReq = new Map();          // `级别:id` → Promise<url|null>，同一张同一级只请求一次
  const fpPreviewUrl = new Map();   // id → 屏幕预览地址(飞回动画用)
  function fpRequest(id, level, fresh) {
    const key = level + ':' + id;
    if (!fresh && fpReq.has(key)) return fpReq.get(key);
    let call;
    try { call = level === 2 ? window.pywebview.api.get_original(id) : window.pywebview.api.get_preview(id); }
    catch (e) { call = null; }
    const pr = Promise.resolve(call).then(res => (res && res.url) || null, () => null).then(url => {
      if (!url) fpReq.delete(key);   // 没拿到(卡拔了/出错)不记死，下次还会再要
      return url;
    });
    fpReq.set(key, pr);
    return pr;
  }
  // 让后端先把这张的屏幕预览备好(不在浏览器里解码)：鼠标按下时、翻页的相邻几张
  function fpPrefetch(id) {
    if (id == null || !(window.pywebview && window.pywebview.api)) return;
    fpRequest(id, 1).then(url => { if (url) fpPreviewUrl.set(id, url); });
  }
  function fpSetShown(id, level, url) {
    if (fpPhotoId !== id) return;
    if (fpShown.id === id && level <= fpShown.level) return;
    fpShown = { id, level, url };
    if (level >= 1) {
      window.__previewShown = window.__previewShown || {};
      window.__previewShown[id] = url;   // 过曝高亮关掉时还原到当前最清晰的这张
    }
    if (!el('#expo-switch').classList.contains('on')) fpImage.style.backgroundImage = `url('${url}')`;
  }
  // 先在后台解码好再换上：换图那一帧不卡、不闪；失败自动重试
  function fpLoadLevel(id, level, url, tries) {
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    img.decode().then(() => fpSetShown(id, level, url), () => {
      if (!(tries > 0)) return;
      setTimeout(() => {
        if (fpPhotoId !== id) return;
        fpRequest(id, level, true).then(u => {
          if (u && fpPhotoId === id) fpLoadLevel(id, level, u + (u.includes('?') ? '&' : '?') + 'r=' + Date.now(), tries - 1);
        });
      }, 350);
    });
  }
  function fpNeedsOriginal() {
    const s = fpStage.getBoundingClientRect();
    return Math.max(s.width, s.height) * (window.devicePixelRatio || 1) > 2560 * 1.05;
  }
  function ensureFpOriginal(id) {
    if (id == null || (fpShown.id === id && fpShown.level >= 2)) return;
    fpRequest(id, 2).then(url => { if (url && fpPhotoId === id) fpLoadLevel(id, 2, url, 1); });
  }
  function fpLoadImage(p) {
    const id = p.id;
    const thumbEl = contentEl.querySelector(`.photo-card[data-id="${id}"] .photo-thumb, .stack-card-thumb[data-cover="${id}"] .photo-thumb`);
    const first = (thumbEl && thumbEl._painted) || p.thumbnail || '';
    fpShown = { id, level: 0, url: first };
    fpImage.style.backgroundImage = `url('${first}')`;
    if (p.thumbnail && first !== p.thumbnail) fpLoadLevel(id, 0.5, p.thumbnail, 0);   // 网格用的是小档：先补 512
    fpRequest(id, 1).then(url => {
      if (fpPhotoId !== id) return;
      if (url) { fpPreviewUrl.set(id, url); fpLoadLevel(id, 1, url, 2); }
      if (fpNeedsOriginal()) ensureFpOriginal(id);
      // 眼前这张的预览到手了，才轮到相邻几张(一张接一张备，不和眼前这张抢读卡)
      fpPrefetchNeighbors(id);
      // 停留片刻再让后端备好原图(只生成缓存文件、不解码)，一放大就能换上；快速翻页时不白读卡
      if (!fpNeedsOriginal()) setTimeout(() => { if (fpPhotoId === id) fpRequest(id, 2); }, 900);
    });
    // 看门狗：2.5 秒还停在缩略图(后端正忙/偶发失败)就重新要一次
    setTimeout(() => {
      if (fpPhotoId === id && fpShown.id === id && fpShown.level < 1) {
        fpRequest(id, 1, true).then(u => { if (u && fpPhotoId === id) fpLoadLevel(id, 1, u, 1); });
      }
    }, 2500);
  }
  // 相邻几张的预览按"下一张 → 上一张 → 下下张"依次备好(串行)：左右翻页时直接就是清晰的。
  // 用户已经翻走了就停下，不再给旧位置备图。
  function fpPrefetchNeighbors(id) {
    const idx = currentVisibleIds.indexOf(id);
    if (idx < 0) return;
    const next = [1, -1, 2].map(d => currentVisibleIds[idx + d]).filter(x => x != null);
    let chain = Promise.resolve();
    next.forEach(nid => {
      chain = chain.then(() => {
        if (fpPhotoId !== id) return null;
        return fpRequest(nid, 1).then(url => { if (url) fpPreviewUrl.set(nid, url); });
      });
    });
  }

  // 详情面板里"高光/阴影修剪 + 噪点"那一段说明。RAW 实测时报传感器层面的结果和信噪比；
  // 只能看预览时如实说明"相机内嵌 JPEG 比 RAW 更早白到顶，RAW 里可能还有余量"。
  function fpExpoNote(res) {
    const pct = v => (v == null ? '0' : String(v));
    if (res.measured_on === 'raw') {
      const parts = [`RAW 实测：高光修剪 ${pct(res.over_pct)}%`];
      if (res.color_clip_pct > 0) parts.push(`部分通道饱和 ${pct(res.color_clip_pct)}%`);
      parts.push(`阴影修剪 ${pct(res.under_pct)}%`);
      let s = parts.join('，') + '。';
      if (res.snr_db != null) {
        const db = Math.round(res.snr_db);
        const level = db >= 30 ? '很干净' : db >= 20 ? '可接受' : db >= 11 ? '偏多，建议用 AI 降噪' : '过重，降噪也难以救回';
        s += `中间调信噪比 ${db} dB(噪点${level})。`;
      }
      return s + '少量修剪(太阳/灯/反光)属正常，落在主体上才值得注意。';
    }
    if (!(res.over_pct > 0 || res.under_pct > 0)) return '预览图上没有成片的高光修剪或阴影修剪。';
    return `预览图估算：高光修剪 ${pct(res.over_pct)}%，阴影修剪 ${pct(res.under_pct)}%。`
      + '相机内嵌的 JPEG 比 RAW 更早"白到顶"，RAW 里多半还有余量；落在主体上才值得注意。';
  }
