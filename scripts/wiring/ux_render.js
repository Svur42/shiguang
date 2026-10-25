  // ══════════ 网格渲染(2026-10 重写) ══════════
  // · 按天分组(废片/可修/精选里也一样按时间分)。原来的"分类视图"已去掉：左侧的废片/可修/精选
  //   本身就是按档位看，分类视图与它重复(用户反馈)。
  // · 每个日期组头旁有勾选圈：一点选中这一天(这一段时间)的全部照片，再点取消。
  // · 堆叠在任何视图下都可用：只按"本组里看得见的成员"成堆，≥2 张才成堆——所以在"精选"里只会
  //   把精选的那几张叠起来，不会把别的档位成员拽出来(以前只能在"全部"里折叠的原因)。
  // · 缩略图走加载引擎：重绘时已加载的图直接贴上，不再整屏闪白。
  let PHOTO_BY_ID = new Map();
  let SUBSTACKS = new Map();     // skey → { skey, stackId, gkey, memberIds(本组可见成员,最清晰在前), cover }
  let COVER_TO_SUB = new Map();  // 折叠堆的封面 id → sub(连选/预生成时把整堆成员带上)
  let GROUPS = new Map();        // 组 key → 本组全部照片 id(含折叠在堆里的)，组头勾选用
  let STACK_BY_ID = new Map();
  function byId(id) { return PHOTO_BY_ID.get(id) || PHOTOS.find(p => p.id === id); }
  function thumbAttrs(p) {
    const rot = (((p.rotation || 0) % 360) + 360) % 360;
    const alt = thumbUrlFor(p, thumbTier === 256 ? 512 : 256);
    return `data-thumb="${sgEsc(thumbUrlFor(p))}" data-alt="${sgEsc(alt)}"${rot ? ` data-rot="${rot}"` : ''}`;
  }

  function cardHTML(p) {
    const sel = state.selected.has(p.id) ? ' selected' : '';
    return `
      <div class="photo-card ${tierClass(p)}${sel}" data-id="${p.id}" data-key="p:${p.id}">
        <div class="photo-thumb" ${thumbAttrs(p)}>
          <span class="photo-check" aria-hidden="true">${CHECK_SVG}</span>
          <span class="tier-tag ${tierClass(p)}">${tierLabelOf(p)}</span>
        </div>
        <div class="photo-meta">
          <div class="fname">${sgEsc(p.name)}</div>
          <div class="ftime">${sgEsc(p.time || '')}</div>
        </div>
      </div>`;
  }

  // 背后探出的"纸层"数随成员数增加(最多4层)，一眼看出这堆有多厚
  function stackLayerCount(memberCount) {
    if (memberCount <= 2) return 1;
    if (memberCount === 3) return 2;
    if (memberCount === 4) return 3;
    return 4;
  }

  // 折叠态：一张代表卡(封面=这组里最清晰的)。左上勾选圈=整组选中/取消；点卡片其余位置=展开。
  function stackCardHTML(sub) {
    const cover = byId(sub.cover);
    if (!cover) return '';
    const n = sub.memberIds.length;
    const layers = Array.from({ length: stackLayerCount(n) }, (_, i) => `<div class="stack-layer" data-depth="${i + 1}"></div>`).join('');
    return `
      <div class="stack-card" data-skey="${sgEsc(sub.skey)}" data-key="s:${sgEsc(sub.skey)}" title="${n} 张相似照片 · 点击展开">
        ${layers}
        <div class="photo-card stack-card-thumb ${tierClass(cover)}" data-cover="${cover.id}">
          <div class="photo-thumb" ${thumbAttrs(cover)}>
            <button class="photo-check stack-check" data-stack-check="${sgEsc(sub.skey)}" aria-label="选中这组 ${n} 张相似照片">${CHECK_SVG}</button>
            <span class="stack-count-badge">${LAYERS_SVG}${n}</span>
            <span class="tier-tag ${tierClass(cover)}">${tierLabelOf(cover)}</span>
          </div>
          <div class="photo-meta">
            <div class="fname">${sgEsc(cover.name)}</div>
            <div class="ftime">相似 ${n} 张 · ${sgEsc(cover.time || '')}</div>
          </div>
        </div>
      </div>`;
  }

  // 展开态的一个成员 = 一张普通照片卡(单击选中、双击全屏、懒加载都沿用)。最清晰那张带金色★，
  // ★兼作"收起这组"按钮(用户建议)；悬停出现右下角删除钮。
  function stackMemberCardHTML(p, sub, isFirst) {
    const sel = state.selected.has(p.id) ? ' selected' : '';
    const best = p.id === sub.cover;
    return `
      <div class="photo-card stack-cell${best ? ' is-keep' : ''}${sel} ${tierClass(p)}" data-id="${p.id}" data-key="p:${p.id}" data-skey="${sgEsc(sub.skey)}">
        <div class="photo-thumb" ${thumbAttrs(p)}>
          <span class="photo-check" aria-hidden="true">${CHECK_SVG}</span>
          ${best ? `<button class="stack-keep-star" data-fold="${sgEsc(sub.skey)}" title="这组里最清晰的一张 · 点此收起这组">★</button>` : ''}
          <button class="stack-cell-del" data-del-member="${p.id}" title="删除这张" aria-label="删除这张">✕</button>
          <span class="tier-tag ${tierClass(p)}">${tierLabelOf(p)}</span>
        </div>
        <div class="photo-meta"><div class="fname">${sgEsc(p.name)}</div><div class="ftime">${sgEsc(p.time || '')}</div></div>
      </div>`;
  }

  // 当前看到的照片：档位 ∩ 文件夹 ∩ 搜索 ∩ 机型
  function currentList() {
    const q = state.search.trim().toLowerCase();
    return PHOTOS.filter(p => {
      const tierOk = state.filter === 'all' ? true : state.filter === 'pending' ? p.tier === null : p.tier === state.filter;
      return tierOk && inScope(p, q);
    });
  }
  // "当前范围"：不看档位筛选(文件夹/搜索/机型)。一键全选某档时只选这个范围里的——以前会把
  // 别的文件夹里看不见的废片也选上，一删就删到看不见的照片。
  function inScope(p, q) {
    const folderOk = state.folder === 'all' ? true
      : Array.isArray(state.folder) ? state.folder.includes(p.folder) : p.folder === state.folder;
    const searchOk = !q || (p.filename && p.filename.toLowerCase().includes(q));
    const cameraOk = state.camera === 'all' || p.cam === state.camera;
    return folderOk && searchOk && cameraOk;
  }
  function scopeList() {
    const q = state.search.trim().toLowerCase();
    return PHOTOS.filter(p => inScope(p, q));
  }

  const WEEKDAYS = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
  function dayInfo(day) {
    if (!day) return { title: '未知日期', sub: '没有拍摄时间' };
    const m = /^(\d{4})年(\d{1,2})月(\d{1,2})日$/.exec(day);
    if (!m) return { title: day, sub: '' };
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const diff = Math.round((today - d) / 86400000);
    const rel = diff === 0 ? '今天 · ' : diff === 1 ? '昨天 · ' : '';
    const title = d.getFullYear() === today.getFullYear() ? `${+m[2]}月${+m[3]}日` : day;
    return { title, sub: rel + WEEKDAYS[d.getDay()] };
  }
  function groupHeaderHTML(gkey, title, sub, count, extraCls) {
    return `<div class="group-header${extraCls ? ' ' + extraCls : ''}" data-key="g:${sgEsc(gkey)}">
        <button class="group-check" data-group-check="${sgEsc(gkey)}" title="选中这一组的全部照片" aria-label="选中这一组的全部照片">${CHECK_SVG}</button>
        <h3>${sgEsc(title)}</h3>${sub ? `<span class="group-sub">${sgEsc(sub)}</span>` : ''}
        <span class="group-count">${count} 张</span>
      </div>`;
  }

  // 一个日期组里的卡片：普通照片 / 折叠堆 / 展开的堆成员。visibleIds 按网格顺序收集(全屏左右翻页用)。
  function renderGroupGrid(gkey, items, visibleIds) {
    const inGroup = new Set(items.map(p => p.id));
    const done = new Set();
    let html = '';
    items.forEach(p => {
      const sid = state.stackMode ? photoIdToStack.get(p.id) : undefined;
      const stack = sid && STACK_BY_ID.get(sid);
      const skey = stack ? sid + '@' + gkey : '';
      if (stack && done.has(skey)) return;
      const members = stack ? stack.memberIds.filter(id => inGroup.has(id)) : [];
      if (members.length < 2) { html += cardHTML(p); visibleIds.push(p.id); return; }
      done.add(skey);
      const sub = { skey, stackId: sid, gkey, memberIds: members, cover: members[0] };
      SUBSTACKS.set(skey, sub);
      if (expandedStacks.has(skey)) {
        members.forEach((mid, i) => { const mp = byId(mid); if (mp) { html += stackMemberCardHTML(mp, sub, i === 0); visibleIds.push(mid); } });
      } else {
        html += stackCardHTML(sub);
        COVER_TO_SUB.set(sub.cover, sub);
        visibleIds.push(sub.cover);   // 折叠态：封面也能在全屏里翻到
      }
    });
    GROUPS.set(gkey, items.map(p => p.id));
    return html;
  }

  const EMPTY_ICONS = {
    photos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-8 8"/></svg>',
  };
  function emptyStateHTML() {
    if (!PHOTOS.length) {
      return `<div class="empty-state"><div class="empty-icon">${EMPTY_ICONS.photos}</div><h3>图库还是空的</h3><p>插入存储卡会自动弹出导入窗口；也可以点左下角「导入新存储卡…」选一个文件夹。</p></div>`;
    }
    // 档位视图的空状态说人话：告诉用户这里为什么空、怎么让照片出现在这里
    const narrowed = state.search.trim() || state.camera !== 'all' || state.folder !== 'all';
    const TIER_EMPTY = {
      good: ['还没有精选照片', '在大图里按 3、或选中照片后在底部选择栏点「精选」，喜欢的照片就会出现在这里。'],
      fix: ['没有可修的照片', '分析后清晰度、曝光或噪点"差一点"、修一修还能用的照片会归到这里。'],
      bad: ['没有废片', '分析后严重模糊、大面积高光修剪(细节已丢)或噪点重到降噪也救不回的照片会归到这里。'],
      pending: ['照片都分析过了', '新导入的照片会先出现在这里，点左侧「开始分析」即可分档。'],
    };
    if (!narrowed && TIER_EMPTY[state.filter]) {
      const [t, d] = TIER_EMPTY[state.filter];
      return `<div class="empty-state"><div class="empty-icon">${EMPTY_ICONS.photos}</div><h3>${t}</h3><p>${d}</p></div>`;
    }
    return `<div class="empty-state"><div class="empty-icon">${EMPTY_ICONS.photos}</div><h3>这里没有照片</h3><p>当前的筛选条件下没有照片，换个档位、文件夹或清空搜索试试。</p></div>`;
  }

  function byDay(arr) {
    const m = new Map();
    arr.forEach(p => { const k = p.day || ''; if (!m.has(k)) m.set(k, []); m.get(k).push(p); });
    return [...m.entries()];
  }
  function dayGroupHTML(gkey, day, items, visibleIds) {
    const grid = renderGroupGrid(gkey, items, visibleIds);
    const info = dayInfo(day);
    // data-title/sub：拖滚动条时旁边浮出的日期标签读这里
    return `<section class="day-group" data-title="${sgEsc(info.title)}" data-sub="${sgEsc(info.sub)}">${groupHeaderHTML(gkey, info.title, info.sub, items.length, '')}<div class="grid">${grid}</div></section>`;
  }

  function render() {
    PHOTO_BY_ID = new Map(PHOTOS.map(p => [p.id, p]));
    STACK_BY_ID = new Map(STACKS.map(s => [s.id, s]));
    SUBSTACKS = new Map();
    COVER_TO_SUB = new Map();
    GROUPS = new Map();
    const list = currentList();
    // 选中只保留当前看得见的照片(含折叠在堆里的)：标档后离开视图、或切换筛选后看不见的自动
    // 取消选中——否则随后按删除会删到看不见的照片
    if (state.selected.size) {
      const visible = new Set(list.map(p => p.id));
      [...state.selected].forEach(id => { if (!visible.has(id)) state.selected.delete(id); });
    }
    const visibleIds = [];
    let html = '';
    pickThumbTier();
    byDay(list).forEach(([day, items]) => { html += dayGroupHTML('d:' + day, day, items, visibleIds); });
    currentVisibleIds = visibleIds;
    thumbReset();
    contentEl.innerHTML = html || emptyStateHTML();
    thumbAttach(contentEl);
    contentEl.classList.toggle('stack-mode-on', state.stackMode);
    refreshSidebarCounts();
    refreshAnalyzeButton();
    refreshSelectionUI();
    refreshStackToggle();
    renderFolderNav();
    updateFpNavButtons();
    scheduleWarm();
    afterRenderHooks.forEach(f => f());
  }

  // 切换档位/文件夹/视图/搜索：内容区轻轻淡入上浮，而不是硬切
  function renderWithFade(opts) {
    render();
    if (opts && opts.toTop) contentEl.scrollTop = 0;
    sgAnimate(contentEl, [{ opacity: 0, translate: '0px 8px' }, { opacity: 1, translate: '0px 0px' }], SPRING.smooth, { duration: 380 });
  }

  // 后台预生成缩略图：先眼前这一屏，再从这一屏往下、往上交替向外扩，最后是别的视图里的照片。
  // 停止滚动 150ms 就按新位置重排(以前要等 450ms，且只往后排，拖到远处时后端还在按旧位置生成)
  let warmTimer = 0;
  function visibleIdRange(ids) {
    const cr = contentEl.getBoundingClientRect();
    let lo = -1, hi = -1;
    for (const c of contentEl.querySelectorAll('.photo-card[data-id], .stack-card[data-skey]')) {
      const r = c.getBoundingClientRect();
      if (r.bottom <= cr.top) continue;
      if (r.top >= cr.bottom) break;
      let id;
      if (c.classList.contains('stack-card')) { const sub = SUBSTACKS.get(c.dataset.skey); id = sub ? sub.cover : null; }
      else id = Number(c.dataset.id);
      const k = id == null ? -1 : ids.indexOf(id);
      if (k < 0) continue;
      if (lo < 0) lo = k;
      hi = k;
    }
    return [lo, hi];
  }
  function scheduleWarm(delay) {
    clearTimeout(warmTimer);
    warmTimer = setTimeout(() => {
      // 屏幕上折叠堆藏着的成员图：空闲时顺手取好(低优先级)
      const cr = contentEl.getBoundingClientRect();
      const pre = [];
      contentEl.querySelectorAll('.stack-card[data-skey]').forEach(sc => {
        const r = sc.getBoundingClientRect();
        if (r.bottom < cr.top || r.top > cr.bottom) return;
        const sub = SUBSTACKS.get(sc.dataset.skey);
        if (sub) sub.memberIds.forEach(id => { const p = byId(id); if (p) pre.push(thumbUrlFor(p)); });
      });
      if (pre.length) thumbPrefetch(pre, false);
      if (!(window.pywebview && window.pywebview.api && window.pywebview.api.warm_thumbnails)) return;
      const ids = [];
      currentVisibleIds.forEach(id => { const sub = COVER_TO_SUB.get(id); (sub ? sub.memberIds : [id]).forEach(x => ids.push(x)); });
      let [lo, hi] = visibleIdRange(ids);
      if (lo < 0) { lo = 0; hi = -1; }
      const seen = new Set(), order = [];
      const push = id => { if (id != null && !seen.has(id)) { seen.add(id); order.push(id); } };
      for (let k = lo; k <= hi; k++) push(ids[k]);
      for (let d = 1; hi + d < ids.length || lo - d >= 0; d++) { push(ids[hi + d]); push(ids[lo - d]); }
      PHOTOS.forEach(p => push(p.id));
      const todo = order.filter(id => { const p = byId(id); return p && p.thumbnail && !thumbLoaded.has(thumbUrlFor(p)); });
      try { window.pywebview.api.warm_thumbnails(todo, thumbTier === 256); } catch (e) {}
    }, delay == null ? 150 : delay);
  }

