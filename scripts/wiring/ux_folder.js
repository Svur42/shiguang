  // ══════════ 文件夹左滑删除(2026-10 第二轮重做) ══════════
  // 按住文件夹往左拖：一颗红色胶囊从标签后面"挤"出来(先粘着标签边缘被拉出，到一定大小就停在右侧
  // 不再变大)；拖过整行 50% 时，胶囊 Q 弹地涨满剩下的空间，垃圾桶居中、桶盖掀开——表示此刻松手
  // 就删除。没到 50% 松手：标签弹回原位，胶囊缩回去。
  // 胶囊宽度由一个欠阻尼弹簧追着目标值跑(每帧积分)，所以无论跟手还是突变都是连续、带一点回弹的。
  (function initFolderSwipe() {
    const nav = el('#folder-nav');
    const DELETE_THRESHOLD = 0.5;   // 用户定：拖过整行 50% 才删(60% 嫌多)
    const PILL_SMALL = 44;          // 没到阈值时胶囊的最大宽度
    const GAP = 6;                  // 胶囊与行边缘/标签的间距
    const TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
      + '<g class="lid"><path d="M4 7h16"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></g>'
      + '<path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/><path d="M10 11v6M14 11v6"/></svg>';
    let drag = null;   // { swipe, row, pill, startX, width, moved, armed, spring }

    // 弹簧：x 追 target。k 刚度、zeta 阻尼比(<1 欠阻尼=有回弹，Q 弹手感)
    function makeSpring(pill) {
      const sp = { x: 0, v: 0, target: 0, raf: 0, last: 0, pill, onRest: null };
      const K = 520, ZETA = 0.58, C = 2 * ZETA * Math.sqrt(K);
      function frame(now) {
        const dt = Math.min(0.032, (now - sp.last) / 1000 || 0.016);
        sp.last = now;
        const a = K * (sp.target - sp.x) - C * sp.v;
        sp.v += a * dt;
        sp.x += sp.v * dt;
        const rest = Math.abs(sp.target - sp.x) < 0.3 && Math.abs(sp.v) < 4;
        if (rest) { sp.x = sp.target; sp.v = 0; }
        paint();
        if (rest) { sp.raf = 0; if (sp.onRest) { const f = sp.onRest; sp.onRest = null; f(); } }
        else sp.raf = requestAnimationFrame(frame);
      }
      function paint() {
        const w = Math.max(0, sp.x);
        pill.style.width = w.toFixed(1) + 'px';
        // 刚冒头时从小往大"挤"出来；快速伸缩时上下略微压扁(果冻感)
        const grow = Math.min(1, w / 26);
        const squash = Math.max(0.88, 1 - Math.abs(sp.v) / 9000);
        pill.style.opacity = String(Math.min(1, w / 14));
        pill.style.transform = `scale(${(0.55 + 0.45 * grow).toFixed(3)}, ${(squash * (0.55 + 0.45 * grow)).toFixed(3)})`;
      }
      sp.set = (t) => {
        sp.target = t;
        if (!sp.raf) { sp.last = performance.now(); sp.raf = requestAnimationFrame(frame); }
      };
      sp.stop = () => { if (sp.raf) cancelAnimationFrame(sp.raf); sp.raf = 0; };
      return sp;
    }
    function pillOf(swipe) {
      let pill = swipe.querySelector(':scope > .folder-swipe-pill');
      if (!pill) {
        pill = document.createElement('div');
        pill.className = 'folder-swipe-pill';
        pill.setAttribute('aria-hidden', 'true');
        pill.innerHTML = TRASH;
        swipe.insertBefore(pill, swipe.firstChild);
      }
      return pill;
    }
    function setArmed(d, armed) {
      if (d.armed === armed) return;
      d.armed = armed;
      d.swipe.classList.toggle('armed', armed);
    }

    nav.addEventListener('mousedown', (e) => {
      if (e.button !== 0 || e.target.closest('[data-multi-folder]')) return;   // 勾选框有自己的点击语义
      const swipe = e.target.closest('.folder-swipe');
      if (!swipe) return;
      const row = swipe.querySelector('.folder-row');
      const pill = pillOf(swipe);
      if (swipe._spring) swipe._spring.stop();
      drag = { swipe, row, pill, startX: e.clientX, width: swipe.getBoundingClientRect().width, moved: false, armed: false, spring: makeSpring(pill) };
      swipe._spring = drag.spring;
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      if (e.buttons === 0) { window.dispatchEvent(new MouseEvent('mouseup')); return; }   // 丢了松手事件(Alt-Tab 等)：当作松手
      const dx = Math.min(0, e.clientX - drag.startX);   // 只能往左
      if (!drag.moved && Math.abs(dx) <= 4) return;
      if (!drag.moved) { drag.moved = true; drag.swipe.classList.add('dragging'); }
      drag.swipe.style.setProperty('--swipe-x', `${dx}px`);
      const revealed = -dx;
      const armed = revealed / drag.width >= DELETE_THRESHOLD;
      setArmed(drag, armed);
      drag.spring.set(armed ? revealed - 2 * GAP : Math.min(Math.max(0, revealed - 2 * GAP), PILL_SMALL));
    });
    window.addEventListener('mouseup', () => {
      if (!drag) return;
      const d = drag;
      drag = null;
      if (!d.moved) { d.spring.stop(); return; }   // 普通点击：照常冒泡(切换文件夹)
      d.swipe.classList.remove('dragging');
      const folder = d.swipe.dataset.folder;
      if (d.armed) {
        // 确认删除：标签整个滑出去，胶囊涨满整行，然后这一行收起
        d.swipe.style.setProperty('--swipe-x', '-100%');
        d.spring.set(d.width - 2 * GAP);
        setTimeout(() => {
          const h = d.swipe.offsetHeight;
          const a = sgAnimate(d.swipe, [{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }], SPRING.smooth, { duration: 260, fill: 'forwards' });
          const done = () => deleteFolder(folder);
          if (a) a.onfinish = done; else done();
        }, 260);
      } else {
        // 没过 50%：标签弹回，胶囊缩回去
        d.swipe.style.setProperty('--swipe-x', '0px');
        setArmed(d, false);
        d.spring.set(0);
      }
      suppressNextClick = true;
    });
    // 拖动松手后浏览器还会补发一次 click：吞掉它，免得删完/弹回后又切换了文件夹或勾了勾选框
    let suppressNextClick = false;
    nav.addEventListener('click', (e) => {
      if (suppressNextClick) { suppressNextClick = false; e.stopImmediatePropagation(); e.preventDefault(); }
    }, true);
    nav.addEventListener('mousedown', () => { suppressNextClick = false; }, true);
    nav.addEventListener('dblclick', (e) => { if (drag && drag.moved) e.stopImmediatePropagation(); }, true);
  })();

