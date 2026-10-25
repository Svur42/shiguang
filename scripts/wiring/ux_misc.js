  // ══════════ 2026-10：选择栏 / 快捷键 / 流式分析 / 宿主通知 ══════════
  // toast 挪进主内容区：与底部选择栏同一条中轴，选择栏出现时自动让到它上方(样式里 has-selection)
  (function () {
    const t = document.getElementById('toast');
    const main = document.querySelector('.main');
    if (t && main) main.appendChild(t);
  })();

  // 按拍摄时间放回原位(撤销删除/恢复文件夹后)，口径与后端 list_photos 一致
  function sortPhotos() {
    PHOTOS.sort((a, b) => {
      const an = a.ts == null, bn = b.ts == null;
      if (an !== bn) return an ? 1 : -1;
      if (!an && a.ts !== b.ts) return a.ts < b.ts ? 1 : -1;
      return b.id - a.id;
    });
  }

  // 选择栏：批量标档(可撤销)、对比、删除、取消
  async function markSelected(tier) {
    const ids = [...state.selected];
    if (!ids.length) return;
    const prev = ids.map(id => [id, (byId(id) || {}).tier == null ? null : byId(id).tier]);
    ids.forEach(id => { const p = byId(id); if (p) p.tier = tier; });
    animateLayoutChange(render);
    try { await window.pywebview.api.set_tiers(ids, tier); } catch (e) {}
    showToast(`已将 ${ids.length} 张标为「${TIER_LABEL[tier]}」`, {
      undo: () => {
        const byTier = new Map();
        prev.forEach(([id, t]) => {
          const p = byId(id);
          if (p) p.tier = t;
          if (!byTier.has(t)) byTier.set(t, []);
          byTier.get(t).push(id);
        });
        byTier.forEach((list, t) => { try { window.pywebview.api.set_tiers(list, t); } catch (e) {} });
        animateLayoutChange(render);
      },
    });
  }
  function deleteSelected() {
    const ids = [...state.selected];
    if (!ids.length) return;
    state.selected.clear();
    commitDeleteAfterUndoWindow(ids, `已删除 ${ids.length} 张照片`);
  }
  (function () {
    const bar = document.getElementById('sel-bar');
    if (!bar) return;
    bar.addEventListener('click', (e) => {
      const tb = e.target.closest('[data-set-tier]');
      if (tb) markSelected(tb.dataset.setTier);
    });
    document.getElementById('sel-clear').addEventListener('click', clearSelection);
    document.getElementById('sel-delete').addEventListener('click', deleteSelected);
  })();

  // 网格快捷键(全屏/对比/弹窗打开时不生效)：
  // 空格=快速预览(鼠标所指那张，仿 QuickLook)，Ctrl+A=全选当前视图，Esc=取消选择，
  // Delete=删除所选(可撤销)，1/2/3=把所选标为 废片/可修/精选
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;
    const compareOpen = compareOverlay.classList.contains('open');
    if (compareOpen && e.key === 'Escape') { compareOverlay.classList.remove('open'); addPopover.classList.remove('open'); return; }
    if (fpOverlay.classList.contains('open') || compareOpen) return;
    if (document.querySelector('.modal-backdrop:not(.hidden)')) return;
    const tag = (e.target && e.target.tagName) || '';
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) { if (e.key === 'Escape') e.target.blur(); return; }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A')) {
      e.preventDefault();
      const n = selectAllVisible();
      showToast(`已选中当前视图的 ${n} 张照片`);
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Escape') { if (state.selected.size) { e.preventDefault(); clearSelection(); } return; }
    if (e.key === ' ') {
      const id = hoverId != null ? hoverId : lastClickedId;
      if (id == null || !byId(id)) return;
      e.preventDefault();
      const thumb = contentEl.querySelector(`.photo-card[data-id="${id}"] .photo-thumb, .stack-card-thumb[data-cover="${id}"] .photo-thumb`);
      openFullscreenPreview(id, thumb);
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.selected.size) { e.preventDefault(); deleteSelected(); return; }
    if (state.selected.size && (e.key === '1' || e.key === '2' || e.key === '3')) {
      markSelected({ '1': 'bad', '2': 'fix', '3': 'good' }[e.key]);
    }
  });

  // 分析中后端分批推来 {id,tier}：就地给卡片换色、档位标签弹一下，不整页重绘(设计单"逐步更新")
  window.onAnalyzeBatch = function (items) {
    let changed = false;
    (items || []).forEach(it => {
      const p = byId(it.id);
      if (!p || p.tier === it.tier) return;
      p.tier = it.tier;
      changed = true;
      contentEl.querySelectorAll(`.photo-card[data-id="${it.id}"], .stack-card-thumb[data-cover="${it.id}"]`).forEach(card => {
        card.classList.remove('tier-bad', 'tier-fix', 'tier-good', 'tier-pending');
        card.classList.add(tierClass(p));
        const tag = card.querySelector('.tier-tag');
        if (tag) {
          tag.className = `tier-tag ${tierClass(p)}`;
          tag.textContent = tierLabelOf(p);
          sgAnimate(tag, [{ scale: '0.5', opacity: 0 }, { scale: '1', opacity: 1 }], SPRING.bouncy);
        }
      });
    });
    if (changed) refreshSidebarCounts();
  };
  // 后端(插卡后台同步等)请主窗弹一条提示
  window.sgHostToast = function (msg) { showToast(String(msg || '')); };
  // 重新拉照片(插卡/导入后)时忘掉"加载失败"记录：拔卡又插回，之前白掉的图要能重新出来
  (function () {
    const orig = window.reloadPhotos;
    if (typeof orig !== 'function') return;
    window.reloadPhotos = function () { thumbFailed.clear(); return orig.apply(this, arguments); };
  })();

  function sgDismissModal(back) {
    if (!back || back.classList.contains('closing')) return;
    back.classList.add('closing');
    setTimeout(() => back.remove(), 170);
  }

