// 侧边栏：存储卡剩余空间 / 约还能拍张数
(function () {
  const btn = document.getElementById('btn-reimport');
  if (!btn || !btn.parentNode) return;
  const box = document.createElement('div');
  box.className = 'card-space';
  box.id = 'card-space';
  box.style.display = 'none';
  btn.parentNode.insertBefore(box, btn);

  async function refreshCardSpace() {
    try {
      const res = await window.pywebview.api.card_space();
      const cards = (res && res.cards) || [];
      box.textContent = '';
      for (const c of cards) {
        const row = document.createElement('div');
        row.className = 'cs-row';
        const txt = document.createElement('div');
        let s = '存储卡 ' + c.drive + ' · 剩余 ' + c.free_gb + ' GB';
        if (c.shots_left != null) s += ' · 约 ' + c.shots_left + ' 张';
        txt.textContent = s;
        const bar = document.createElement('div');
        bar.className = 'cs-bar';
        const fill = document.createElement('div');
        const freeRatio = c.total_gb > 0 ? c.free_gb / c.total_gb : 1;
        fill.className = 'cs-fill' + (freeRatio < 0.1 ? ' low' : '');
        fill.style.width = Math.max(0, Math.min(100, (1 - freeRatio) * 100)) + '%';
        bar.appendChild(fill);
        row.appendChild(txt);
        row.appendChild(bar);
        box.appendChild(row);
      }
      box.style.display = cards.length ? '' : 'none';
    } catch (e) {
      box.style.display = 'none';
    }
  }
  window.refreshCardSpace = refreshCardSpace;

  function start() {
    refreshCardSpace();
    setInterval(refreshCardSpace, 20000);
  }
  if (window.pywebview && window.pywebview.api) start();
  else window.addEventListener('pywebviewready', start);

  const orig = window.reloadPhotos;
  if (typeof orig === 'function') {
    window.reloadPhotos = function () {
      const r = orig.apply(this, arguments);
      refreshCardSpace();
      return r;
    };
  }
})();
