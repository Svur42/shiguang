  // ══════════ 网格交互(2026-10 重写) ══════════
  // 展开/收起堆叠只改动这一堆自己的 DOM(不再整屏重建)，所以：其余缩略图不闪白、页面不跳；
  // 被挤开的卡片用弹簧平滑让位(FLIP，只动视口附近的)；成员像从一摞牌里依次发出，收起时飞回那一摞。
  let lastClickedId = null;   // Shift 连选的锚点 / 空格快速预览的备选目标
  let hoverId = null;         // 鼠标停在哪张：空格快速预览优先看这张
  let expandedAt = 0;         // 刚展开过的时刻：紧跟的双击不把"展开"误当成一次选中去撤销

  function stackCardEl(skey) { return contentEl.querySelector(`.stack-card[data-skey="${CSS.escape(skey)}"]`); }
  function htmlToNodes(markup) {
    const tpl = document.createElement('template');
    tpl.innerHTML = markup;
    return tpl.content;
  }
  // 网格结构变了但没整页重绘时，按 DOM 实际顺序重算全屏左右翻页的序列
  function syncVisibleIdsFromDom() {
    const ids = [];
    contentEl.querySelectorAll('.photo-card[data-id], .stack-card[data-skey]').forEach(n => {
      if (n.classList.contains('stack-card')) {
        const sub = SUBSTACKS.get(n.dataset.skey);
        if (sub) ids.push(sub.cover);
      } else if (!n.classList.contains('sg-ghost')) {
        ids.push(Number(n.dataset.id));
      }
    });
    currentVisibleIds = ids;
    updateFpNavButtons();
  }

  function expandStack(skey) {
    const sub = SUBSTACKS.get(skey);
    const card = stackCardEl(skey);
    if (!sub || !card) return;
    expandedAt = performance.now();
    const before = captureLayout();
    const from = card.getBoundingClientRect();
    expandedStacks.add(skey);
    COVER_TO_SUB.delete(sub.cover);
    const frag = htmlToNodes(sub.memberIds.map((mid, i) => { const p = byId(mid); return p ? stackMemberCardHTML(p, sub, i === 0) : ''; }).join(''));
    const cells = Array.from(frag.children);
    card.replaceWith(frag);
    cells.forEach(c => thumbAttach(c));          // 封面等已加载过的图立刻贴上
    syncVisibleIdsFromDom();
    refreshSelectionUI();
    flipFrom(before, new Set(cells.map(c => c.dataset.key)), false);
    // 发牌：第一张就是原来那摞的封面，原地"抬起"；其余从那摞的位置依次飞向各自格子，
    // 起始带一点倾角和缩小(像从牌堆里抽出)，落位时轻微回弹。
    const n = cells.length;
    const step = Math.min(38, 300 / Math.max(1, n - 1));
    cells.forEach((cell, i) => {
      const to = cell.getBoundingClientRect();
      if (!to.width) return;
      if (i === 0) {
        sgAnimate(cell, [{ scale: '0.97' }, { scale: '1' }], SPRING.bouncy);
        return;
      }
      const dx = (from.left + from.width / 2) - (to.left + to.width / 2);
      const dy = (from.top + from.height / 2) - (to.top + to.height / 2);
      const tilt = (i % 2 ? -1 : 1) * Math.min(7, 2 + i * 0.8);
      cell.style.zIndex = String(n - i);
      // 飞行中(含还没起飞、透明地叠在牌堆上那段)不接收点击：快速双击牌堆时第二下应落在封面上
      cell.style.pointerEvents = 'none';
      const a = sgAnimate(cell, [
        { translate: `${dx}px ${dy}px`, scale: '0.9', rotate: `${tilt}deg`, opacity: 0 },
        { opacity: 1, offset: 0.16 },
        { translate: '0px 0px', scale: '1', rotate: '0deg', opacity: 1 },
      ], SPRING.bouncy, { delay: (i - 1) * step, fill: 'backwards' });
      const clear = () => { cell.style.zIndex = ''; cell.style.pointerEvents = ''; };
      if (a) { a.onfinish = clear; a.oncancel = clear; } else clear();
    });
  }

  function collapseStack(skey) {
    const sub = SUBSTACKS.get(skey);
    const cells = Array.from(contentEl.querySelectorAll(`.stack-cell[data-skey="${CSS.escape(skey)}"]`));
    expandedStacks.delete(skey);
    if (!sub || !cells.length) { render(); return; }
    const before = captureLayout();
    const cr = contentEl.getBoundingClientRect();
    // 先把还在屏幕上的成员复制成鬼影(真身马上换成折叠卡)，鬼影负责"飞回那一摞"
    const ghosts = [];
    cells.slice(1).forEach(c => {
      const r = c.getBoundingClientRect();
      if (r.bottom > cr.top && r.top < cr.bottom) ghosts.push(makeGhost(c, r, cr));
    });
    const card = htmlToNodes(stackCardHTML(sub)).firstElementChild;
    cells[0].replaceWith(card);
    cells.slice(1).forEach(c => c.remove());
    COVER_TO_SUB.set(sub.cover, sub);
    thumbAttach(card);
    syncVisibleIdsFromDom();
    refreshSelectionUI();
    // 后面的卡片同时平滑补位(和收拢一起动，而不是等收完再"啪"地跳上来)
    flipFrom(before, new Set([card.dataset.key]), false);
    const to = card.getBoundingClientRect();
    ghosts.forEach((g, i) => {
      const r = g._rect;
      const dx = (to.left + to.width / 2) - (r.left + r.width / 2);
      const dy = (to.top + to.height / 2) - (r.top + r.height / 2);
      const a = sgAnimate(g, [
        { translate: '0px 0px', scale: '1', opacity: 1 },
        { opacity: 1, offset: 0.62 },
        { translate: `${dx}px ${dy}px`, scale: '0.9', opacity: 0 },
      ], SPRING.smooth, { duration: 420, delay: (ghosts.length - 1 - i) * 18 });
      if (a) a.onfinish = a.oncancel = () => g.remove(); else g.remove();
    });
    // 那一摞把它们"接住"：轻轻一沉再回弹
    sgAnimate(card, [{ scale: '1' }, { scale: '0.96', offset: 0.35 }, { scale: '1' }], SPRING.bouncy,
      { delay: Math.min(220, 120 + ghosts.length * 18) });
  }

  contentEl.addEventListener('click', (e) => {
    const t = e.target;
    const gc = t.closest('[data-group-check]');
    if (gc) { toggleIdsSelection(GROUPS.get(gc.dataset.groupCheck) || []); return; }
    const sc = t.closest('[data-stack-check]');
    if (sc) { const sub = SUBSTACKS.get(sc.dataset.stackCheck); if (sub) toggleIdsSelection(sub.memberIds); return; }
    const fold = t.closest('[data-fold]');
    if (fold) { collapseStack(fold.dataset.fold); return; }
    const del = t.closest('[data-del-member]');
    if (del) { trashPhoto(Number(del.dataset.delMember)); return; }
    const stackCard = t.closest('.stack-card');
    if (stackCard) { if (e.detail > 1) return; expandStack(stackCard.dataset.skey); return; }
    const card = t.closest('.photo-card[data-id]');
    if (!card || e.detail > 1) return;   // detail>1 属于双击手势
    const id = Number(card.dataset.id);
    if (e.shiftKey && lastClickedId != null && lastClickedId !== id) selectRange(lastClickedId, id);
    else toggleIdsSelection([id]);
    lastClickedId = id;
  });

  // 双击 = 全屏细看(照片从缩略图位置放大飞出)。双击里的第一下单击已经切换过一次选中——撤销它；
  // 若那一下是"展开堆叠"，则不撤销(没选中过)，直接看这一组最清晰的那张。
  contentEl.addEventListener('dblclick', (e) => {
    const t = e.target;
    if (t.closest('[data-group-check],[data-stack-check],[data-fold],[data-del-member]')) return;
    const stackCard = t.closest('.stack-card');
    if (stackCard) {
      const sub = SUBSTACKS.get(stackCard.dataset.skey);
      if (sub) openFullscreenPreview(sub.cover, stackCard.querySelector('.photo-thumb'));
      return;
    }
    const card = t.closest('.photo-card[data-id]');
    if (!card) return;
    let id = Number(card.dataset.id);
    const justExpanded = performance.now() - expandedAt <= 700;
    if (justExpanded && card.dataset.skey) {
      // 双击的是牌堆(第一下已把它展开)：看这一组最清晰的那张
      const sub = SUBSTACKS.get(card.dataset.skey);
      if (sub) id = sub.cover;
    }
    if (!justExpanded) toggleIdsSelection([id]);
    const thumbEl = contentEl.querySelector(`.photo-card[data-id="${id}"] .photo-thumb`);
    openFullscreenPreview(id, thumbEl);
  });

  contentEl.addEventListener('mouseover', (e) => {
    const card = e.target.closest('.photo-card[data-id], .stack-card[data-skey]');
    if (!card) return;
    if (card.classList.contains('stack-card')) {
      const sub = SUBSTACKS.get(card.dataset.skey);
      hoverId = sub ? sub.cover : null;
      // 鼠标停在折叠堆上(多半马上要点开)：优先把它藏着的成员图取好
      if (sub) thumbPrefetch(sub.memberIds.map(id => thumbUrlFor(byId(id))), true);
    } else hoverId = Number(card.dataset.id);
  });
  contentEl.addEventListener('mouseleave', () => { hoverId = null; });
  // 双击的第二下按下时就让后端开始准备这张的高清预览：等双击打开全屏时多半已经好了，
  // 不用先看一会儿糊的缩略图
  contentEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.detail !== 2) return;   // 只在双击的第二下：单击/连选不白读卡
    const card = e.target.closest('.photo-card[data-id], .stack-card[data-skey]');
    if (!card) return;
    const sub = card.classList.contains('stack-card') ? SUBSTACKS.get(card.dataset.skey) : null;
    fpPrefetch(sub ? sub.cover : Number(card.dataset.id));
  });
  contentEl.addEventListener('scroll', () => scheduleWarm(), { passive: true });

