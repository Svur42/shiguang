  // ══════════ 选择(2026-10 重写) ══════════
  // 选中状态只改类名、不重建网格(不闪、不跳)。组头勾选圈显示 全选✓/部分— /未选；折叠堆按成员
  // 选中情况显示 全选/部分。选中≥1张时底部浮出选择栏(数量 · 标为废片/可修/精选 · 对比 · 删除)。
  function refreshSelectionUI() {
    const sel = state.selected;
    contentEl.querySelectorAll('.photo-card[data-id]').forEach(c => c.classList.toggle('selected', sel.has(Number(c.dataset.id))));
    contentEl.querySelectorAll('.stack-card[data-skey]').forEach(sc => {
      const sub = SUBSTACKS.get(sc.dataset.skey);
      if (!sub) return;
      const n = sub.memberIds.reduce((a, id) => a + (sel.has(id) ? 1 : 0), 0);
      sc.classList.toggle('selected', n === sub.memberIds.length);
      sc.classList.toggle('partial', n > 0 && n < sub.memberIds.length);
    });
    contentEl.querySelectorAll('[data-group-check]').forEach(b => {
      const ids = GROUPS.get(b.dataset.groupCheck) || [];
      const n = ids.reduce((a, id) => a + (sel.has(id) ? 1 : 0), 0);
      b.classList.toggle('is-all', ids.length > 0 && n === ids.length);
      b.classList.toggle('is-some', n > 0 && n < ids.length);
      b.title = n === ids.length && n > 0 ? '取消选中这一组' : '选中这一组的全部照片';
    });
    contentEl.classList.toggle('has-selection', sel.size > 0);
    refreshSelectionBar();
  }
  function refreshSelectionBar() {
    const bar = document.getElementById('sel-bar');
    if (!bar) return;
    const n = state.selected.size;
    const num = document.getElementById('sel-num');
    if (num && num.textContent !== String(n)) {
      const grew = n > Number(num.textContent || 0);
      num.textContent = n;
      if (n > 0 && bar.classList.contains('show')) sgAnimate(num, [{ scale: grew ? '1.28' : '0.82' }, { scale: '1' }], SPRING.bouncy, { duration: 420 });
    }
    const show = n > 0;
    bar.classList.toggle('show', show);
    bar.setAttribute('aria-hidden', String(!show));
    const win = document.querySelector('.app-window');
    if (win) win.classList.toggle('has-selection', show);
    const cmp = document.getElementById('sel-compare');
    if (cmp) { cmp.disabled = n < 2; cmp.title = n < 2 ? '至少选 2 张才能对比' : (n > 4 ? '最多同屏对比 4 张，将取前 4 张' : '同屏对比所选照片'); }
  }
  // 兼容旧调用点：以前只刷工具栏计数，现在统一刷选中状态+选择栏
  function refreshToolbar() { refreshSelectionUI(); }
  function toggleIdsSelection(ids) {
    if (!ids || !ids.length) return;
    const all = ids.every(id => state.selected.has(id));
    ids.forEach(id => (all ? state.selected.delete(id) : state.selected.add(id)));
    refreshSelectionUI();
  }
  // Shift+点击：从上一次点的那张连选到这一张(按网格顺序；折叠堆连同成员一起)
  function selectRange(fromId, toId) {
    const seq = currentVisibleIds;
    let a = seq.indexOf(fromId), b = seq.indexOf(toId);
    if (a < 0 || b < 0) { toggleIdsSelection([toId]); return; }
    if (a > b) [a, b] = [b, a];
    seq.slice(a, b + 1).forEach(id => {
      const sub = COVER_TO_SUB.get(id);
      (sub ? sub.memberIds : [id]).forEach(x => state.selected.add(x));
    });
    refreshSelectionUI();
  }
  function selectAllVisible() {
    const ids = [];
    currentVisibleIds.forEach(id => { const sub = COVER_TO_SUB.get(id); (sub ? sub.memberIds : [id]).forEach(x => ids.push(x)); });
    ids.forEach(id => state.selected.add(id));
    refreshSelectionUI();
    return ids.length;
  }
  function clearSelection() {
    if (!state.selected.size) return;
    state.selected.clear();
    refreshSelectionUI();
  }

