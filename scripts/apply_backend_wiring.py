# -*- coding: utf-8 -*-
"""把 Open Design 设计工作台导出的纯前端原型，接上真实后端，生成 frontend/app.html。

用途（方式C：外观归工作台、接线归这里）：
  你在设计工作台改完 UI 外观后，运行本脚本即可把接后端的逻辑重新打上去：
    cd shiguang && .venv/Scripts/python.exe scripts/apply_backend_wiring.py

它做的事：读取工作台原文件（纯设计版、假数据），套用下面所有"接线"改动，
写出 frontend/app.html（真实数据版）。每处改动都做唯一性校验，若工作台大改
导致某个锚点匹配不上，会明确报出是哪一处，方便定位手工修。

工作台原文件路径（如变化改这里）：
"""
from pathlib import Path

SRC = Path(
    r"C:\Users\s1949\AppData\Roaming\Open Design\namespaces\release-stable-win"
    r"\data\projects\e75c54c2-937e-435f-9975-00613aaf7efa\shiguang-photo-culler.html"
)
DST = Path(__file__).resolve().parent.parent / "frontend" / "app.html"

html = SRC.read_text(encoding="utf-8")
applied = []


def once(old, new, label):
    global html
    n = html.count(old)
    if n != 1:
        raise SystemExit(f"[失败] {label}: 期望精确匹配1处，实际{n}处。锚点前80字符:\n  {old[:80]!r}")
    html = html.replace(old, new)
    applied.append(label)


def times(old, new, expect, label):
    global html
    n = html.count(old)
    if n != expect:
        raise SystemExit(f"[失败] {label}: 期望{expect}处，实际{n}处。锚点:\n  {old[:80]!r}")
    html = html.replace(old, new)
    applied.append(f"{label}(x{expect})")


def block(start, end, new, label):
    """整段替换：从 start 锚点(含)到 end 锚点(不含，end 保留)之间的全部内容换成 new。
    两个锚点都必须唯一且 end 在 start 之后——用来整段换掉大函数，不必逐字复刻函数体当锚点。"""
    global html
    for name, s in (("start", start), ("end", end)):
        n = html.count(s)
        if n != 1:
            raise SystemExit(f"[失败] {label}: {name} 锚点期望1处，实际{n}处：\n  {s[:80]!r}")
    i, j = html.index(start), html.index(end)
    if j <= i:
        raise SystemExit(f"[失败] {label}: end 锚点出现在 start 之前")
    html = html[:i] + new + html[j:]
    applied.append(label)


WIRING_DIR = Path(__file__).resolve().parent / "wiring"


def wiring(name):
    """读 scripts/wiring/ 下的大段新代码(独立成文件便于维护，由下面的 Y 段拼进去)。"""
    return (WIRING_DIR / name).read_text(encoding="utf-8")


# ══════════ A. 数据接线（替代写死的假数据/假交互）══════════

# A1. 5处缩略图地址(普通卡4 + 堆叠展开成员1) → 真实http地址
times("assets/photos/${p.file}", "${p.thumbnail || ''}", 5, "缩略图地址")
# A1b. 堆叠折叠卡封面缩略图(用 cover 变量) → 真实http地址
once("assets/photos/${cover.file}", "${cover.thumbnail || ''}", "堆叠封面缩略图地址")

# A2. PHOTOS 改为可变空数组，启动时从后端拉；演示数据改名为死代码
once(
    "  const PHOTOS = [\n",
    "  let PHOTOS = [];   // 真实照片在初始化时从后端拉取；下面这份是原型演示数据，已停用\n  const PHOTOS_DEMO = [\n",
    "PHOTOS声明",
)

# A3. 侧边栏文件夹显示末级短名而非整条长路径
once(
    '<span class="folder-row-label">${f}</span>',
    '<span class="folder-row-label">${(window.__folderNames && window.__folderNames[f]) || f}</span>',
    "文件夹短名显示",
)

# A4. 去掉启动时自动弹出的假导入弹窗
once(
    "  openImport();\n",
    "  // openImport();  // 停用：不再启动就弹假的存储卡检测弹窗\n",
    "去掉自动openImport",
)

# A5. 「导入新存储卡…」接真实导入
once(
    "  el('#btn-reimport').addEventListener('click', openImport);",
    """  el('#btn-reimport').addEventListener('click', async () => {
    showToast('正在导入…');
    const result = await window.pywebview.api.choose_folder_and_scan();
    if (result && result.error) { showToast('导入失败：' + result.error); return; }
    PHOTOS.length = 0;
    (result.photos || []).forEach(p => PHOTOS.push(p));
    await refreshFolders();
    render();
    renderFolderNav();
    showToast(`已导入，共 ${PHOTOS.length} 张`);
  });""",
    "btn-reimport接真实导入",
)

# A6. 详情面板手动改判 → 持久化
once(
    """    const p = PHOTOS.find(p => p.id === fpPhotoId);
    p.tier = btn.dataset.tier;
    document.querySelectorAll('#dp-tier-picker .tier-btn').forEach(b => b.classList.toggle('active', b === btn));""",
    """    const p = PHOTOS.find(p => p.id === fpPhotoId);
    p.tier = btn.dataset.tier;
    window.pywebview.api.set_tier(p.id, p.tier);  // 持久化改判到数据库
    document.querySelectorAll('#dp-tier-picker .tier-btn').forEach(b => b.classList.toggle('active', b === btn));""",
    "详情面板改判持久化",
)

# A7. 对比模式手动改判 → 持久化
once(
    """        p.tier = tierBtn.dataset.ccTier;
        renderCompare();
        render();""",
    """        p.tier = tierBtn.dataset.ccTier;
        window.pywebview.api.set_tier(p.id, p.tier);  // 持久化改判到数据库
        renderCompare();
        render();""",
    "对比模式改判持久化",
)

# A8. trashPhoto 改为统一删除逻辑 + 新增 refreshFolders/commitDeleteAfterUndoWindow
once(
    """  function trashPhoto(id) {
    const idx = PHOTOS.findIndex(p => p.id === id);
    if (idx === -1) return;
    const [removed] = PHOTOS.splice(idx, 1);
    compareIds = compareIds.filter(x => x !== id);
    state.selected.delete(id);
    zoomMap.delete(id);
    panMap.delete(id);
    render();
    if (compareIds.length === 0) {
      compareOverlay.classList.remove('open');
    } else {
      renderCompare();
    }
    showToast(`已删除 ${removed.name}`, {
      undo: () => {
        PHOTOS.splice(idx, 0, removed);
        render();
      },
    });
  }""",
    """  // 从后端拉取文件夹列表并更新侧边栏所需的 importedFolders + 短名映射
  async function refreshFolders() {
    const folders = await window.pywebview.api.list_folders();
    importedFolders = folders.map(f => f.folder);
    window.__folderNames = {};
    window.__folderKinds = {};   // folder→'card'|'local'：本地文件夹侧边栏用不同图标区分
    folders.forEach(f => { window.__folderNames[f.folder] = f.name; window.__folderKinds[f.folder] = f.kind || 'card'; });
  }

  // 统一删除逻辑：先前端乐观移除（立刻消失），弹5秒可撤销toast，撤销则恢复、
  // 后端从未被调用；超时才真正调后端把文件送进回收站+删库记录。
  function commitDeleteAfterUndoWindow(ids, label) {
    if (!ids.length) return;
    const idSet = new Set(ids);
    const removed = PHOTOS.filter(p => idSet.has(p.id));
    PHOTOS = PHOTOS.filter(p => !idSet.has(p.id));
    ids.forEach(id => { state.selected.delete(id); zoomMap.delete(id); panMap.delete(id); });
    compareIds = compareIds.filter(x => !idSet.has(x));
    render();
    renderFolderNav();
    if (compareOverlay.classList.contains('open')) {
      if (compareIds.length === 0) compareOverlay.classList.remove('open');
      else renderCompare();
    }
    let committed = false;
    const timer = setTimeout(async () => {
      committed = true;
      try {
        const res = await window.pywebview.api.delete_photos(ids);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    }, 5000);
    showToast(label, {
      undo: () => {
        if (committed) return;
        clearTimeout(timer);
        PHOTOS = PHOTOS.concat(removed).sort((a, b) => b.id - a.id);
        render();
        renderFolderNav();
      },
    });
  }

  function trashPhoto(id) {
    const p = PHOTOS.find(x => x.id === id);
    if (!p) return;
    commitDeleteAfterUndoWindow([id], `已删除 ${p.name}`);
  }""",
    "trashPhoto改造+删除助手",
)

# A9. 批量删除走统一逻辑
once(
    """  el('#btn-delete').addEventListener('click', () => {
    const n = state.selected.size;
    for (let i = PHOTOS.length - 1; i >= 0; i--) {
      if (state.selected.has(PHOTOS[i].id)) PHOTOS.splice(i, 1);
    }
    state.selected.clear();
    render();
    showToast(`已删除 ${n} 张照片`);
  });""",
    """  el('#btn-delete').addEventListener('click', () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    state.selected.clear();
    commitDeleteAfterUndoWindow(ids, `已删除 ${ids.length} 张照片`);
  });""",
    "批量删除改造",
)

# A10. 结尾初始化：从后端拉真实数据 + 定义导入进度回调
once(
    "  render();\n})();",
    """  // 底部固定进度条：导入/分析这类耗时批量操作用它显示"已处理X/共Y张(百分比)"，
  // 让用户明确知道在载入、还剩多少，而不是以为卡死。完成后短暂停留再自动隐藏。
  function sgProgress(done, total, label) {
    let bar = document.getElementById('sg-progress');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'sg-progress';
      bar.style.cssText = 'position:fixed; left:50%; bottom:24px; transform:translateX(-50%); z-index:9999; background:var(--surface,#fff); color:var(--fg,#222); border:1px solid var(--border,#ddd); border-radius:10px; padding:10px 16px; box-shadow:0 8px 24px rgba(0,0,0,.18); font-size:13px; min-width:260px;';
      document.body.appendChild(bar);
    }
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    bar.innerHTML = `<div style="margin-bottom:6px;">${label} ${done}/${total}（${pct}%）</div>`
      + `<div style="height:6px; background:var(--border,#eee); border-radius:3px; overflow:hidden;"><div style="height:100%; width:${pct}%; background:var(--accent,#2b6cb0); transition:width .15s;"></div></div>`;
    bar.style.display = 'block';
    clearTimeout(bar._t);
    if (done >= total) { bar._t = setTimeout(() => { bar.style.display = 'none'; }, 1200); }
  }
  window.sgProgress = sgProgress;
  window.onImportProgress = function (done, total) { sgProgress(done, total, '正在导入照片'); };

  // 独立小导入窗确认导入后，调这个让主窗重新拉照片并重绘
  window.reloadPhotos = async function () {
    try {
      const photos = await window.pywebview.api.list_photos();
      PHOTOS.length = 0;
      photos.forEach(p => PHOTOS.push(p));
      await refreshFolders();
      render();
      renderFolderNav();
    } catch (e) {}
  };

  async function initFromBackend() {
    try {
      const photos = await window.pywebview.api.list_photos();
      PHOTOS.length = 0;
      photos.forEach(p => PHOTOS.push(p));
      await refreshFolders();
      render();
      renderFolderNav();
      // 后台给存量照片补读EXIF拍摄时间（仅原文件可访问的会被补），补完刷新排序
      window.pywebview.api.backfill_metadata().then(res => {
        if (res && res.photos) {
          PHOTOS.length = 0;
          res.photos.forEach(p => PHOTOS.push(p));
          render();
          if (res.updated > 0) showToast(`已按拍摄时间整理 ${res.updated} 张照片`);
        }
      });
    } catch (e) {
      showToast('加载照片失败：' + e);
    }
  }

  // 无边框窗口：标题栏三个按钮接后端窗口控制
  document.getElementById('win-min').addEventListener('click', () => window.pywebview.api.minimize_window());
  document.getElementById('win-max').addEventListener('click', () => window.pywebview.api.toggle_maximize());
  document.getElementById('win-close').addEventListener('click', () => window.pywebview.api.close_window());

  if (window.pywebview && window.pywebview.api) initFromBackend();
  else window.addEventListener('pywebviewready', initFromBackend);
})();""",
    "结尾初始化接后端+窗口按钮",
)

# A11. 全屏 blur-up 模糊类（先糊后清时给512缩略图加模糊，高清加载完去掉）
once(
    ".fp-image.zoomed.dragging { cursor: grabbing; transition: none; }",
    ".fp-image.zoomed.dragging { cursor: grabbing; transition: none; }\n.fp-image.fp-loading { filter: blur(8px); }",
    "全屏blur-up样式",
)

# A12. 全屏打开时先糊后清换2560高清 + 预加载相邻两张
once(
    "    fpImage.style.backgroundImage = `url('${p.thumbnail || ''}')`;",
    """    fpImage.style.backgroundImage = `url('${p.thumbnail || ''}')`;
    // 切到新照片时复位过曝开关（否则开关显示"开"但图是新照片的普通图，状态错位）
    el('#expo-switch').classList.remove('on');
    // 先糊后清：缩略图(512)已铺上，去请求2560高清预览，加载完平滑换上、去模糊
    fpImage.classList.add('fp-loading');
    window.pywebview.api.get_preview(id).then(res => {
      if (res && res.url && fpPhotoId === id) {
        const hi = new Image();
        hi.onload = () => {
          if (fpPhotoId === id) {
            window.__previewShown = window.__previewShown || {};
            window.__previewShown[id] = res.url;  // 供过曝开关关闭时还原到高清
            // 只有当前没开过曝高亮时才把背景换成高清，否则会把用户正看的高亮图冲掉
            if (!el('#expo-switch').classList.contains('on')) {
              fpImage.style.backgroundImage = `url('${res.url}')`;
            }
            fpImage.classList.remove('fp-loading');
          }
        };
        hi.src = res.url;
      } else if (fpPhotoId === id) {
        // 当前这张确实没高清(原文件缺失)才去模糊；陈旧请求(fpPhotoId!==id)静默丢弃不动UI
        fpImage.classList.remove('fp-loading');
      }
    });
    // 预加载相邻两张的高清，方向键切换更跟手（fire-and-forget，只为触发生成+缓存）
    (function () {
      const idx = currentVisibleIds.indexOf(id);
      [idx - 1, idx + 1].forEach(j => {
        if (j >= 0 && j < currentVisibleIds.length) {
          try { window.pywebview.api.get_preview(currentVisibleIds[j]); } catch (e) {}
        }
      });
    })();""",
    "全屏blur-up换高清+预加载",
)

# A13. 详情面板真实直方图 + 过曝欠曝占比（替换写死的HIST_PRESETS假直方图）
once(
    """    const preset = HIST_PRESETS[p.tier] || HIST_PRESETS.pending;
    buildHist('#hist-main', preset, 'var(--fg-2)');
    buildHist('#hist-r', preset.map(v => v * 0.9), 'var(--chan-r)');
    buildHist('#hist-g', preset.map(v => v * 1.0), 'var(--chan-g)');
    buildHist('#hist-b', preset.map(v => v * 0.8), 'var(--chan-b)');
    refreshExpoSpots(p);""",
    """    // 真实直方图 + 高光/阴影修剪与噪点：等这张的屏幕预览备好后再要(眼前这张的清晰图优先；
    // RAW 实测要读整张 RAW，不能和它抢读卡)。fpPhotoId===id 防切走
    // 切图时先清掉上一张的直方图与说明，免得等测量的几秒里一直显示别的照片的数据
    ['#hist-main', '#hist-r', '#hist-g', '#hist-b'].forEach(s => { el(s).innerHTML = ''; });
    el('#expo-note').textContent = '测量中…';
    fpRequest(id, 1).then(() => (fpPhotoId === id ? window.pywebview.api.get_analysis(id) : null)).then(res => {
      if (fpPhotoId !== id) return;
      if (!res || res.histograms == null) { el('#expo-note').textContent = '这张照片暂时无法分析(原文件不在?)。'; return; }
      buildHist('#hist-main', res.histograms.main, 'var(--fg-2)');
      buildHist('#hist-r', res.histograms.r, 'var(--chan-r)');
      buildHist('#hist-g', res.histograms.g, 'var(--chan-g)');
      buildHist('#hist-b', res.histograms.b, 'var(--chan-b)');
      window.__expoOverlay = window.__expoOverlay || {};
      window.__expoOverlay[id] = res.overlay_url;
      if (el('#expo-switch').classList.contains('on') && res.overlay_url) fpImage.style.backgroundImage = `url('${res.overlay_url}')`;   // 等待期间开了开关：补应用
      const note = document.getElementById('expo-note');
      if (note) note.textContent = fpExpoNote(res);
    });
    refreshExpoSpots(p);""",
    "详情真实直方图+过曝占比",
)

# A14. gut refreshExpoSpots：只隐藏4个写死框、不再设note（note交给get_analysis真实占比）
once(
    """  function refreshExpoSpots(p) {
    if (p.tier === null) {
      ['es1','es2','es3','es4'].forEach(id2 => el('#' + id2).classList.remove('show'));
      el('#expo-note').textContent = '该照片尚未分析，暂无曝光标注数据。';
      return;
    }
    const spotCount = p.tier === 'bad' ? 4 : p.tier === 'fix' ? 2 : 0;
    ['es1','es2','es3','es4'].forEach((id2, i) => {
      el('#' + id2).classList.toggle('show', el('#expo-switch').classList.contains('on') && i < spotCount);
    });
    el('#expo-note').textContent = spotCount === 0
      ? '该照片未检测到明显过曝或欠曝区域。'
      : `检测到 ${spotCount} 处过曝/欠曝区域，开启开关可在大图上查看标注。`;
  }""",
    """  function refreshExpoSpots(p) {
    // 真实高亮走整图切换(见expo-switch)，这些写死的框一律隐藏；note由get_analysis真实占比填
    ['es1','es2','es3','es4'].forEach(id2 => el('#' + id2).classList.remove('show'));
  }""",
    "gut refreshExpoSpots",
)

# A15. 过曝开关：打开切成高亮图、关闭还原到高清/缩略图
once(
    """  el('#expo-switch').addEventListener('click', () => {
    el('#expo-switch').classList.toggle('on');
    const p = PHOTOS.find(p => p.id === fpPhotoId);
    if (p) refreshExpoSpots(p);
  });""",
    """  el('#expo-switch').addEventListener('click', () => {
    el('#expo-switch').classList.toggle('on');
    const on = el('#expo-switch').classList.contains('on');
    const ov = (window.__expoOverlay || {})[fpPhotoId];
    const cur = PHOTOS.find(p => p.id === fpPhotoId);
    if (on && ov) {
      fpImage.style.backgroundImage = `url('${ov}')`;   // 高亮图(过曝红/欠曝蓝)
    } else if (cur) {
      // 关掉：还原到当前显示的图(有高清用高清，否则缩略图)
      const back = (window.__previewShown && window.__previewShown[fpPhotoId]) || cur.thumbnail || '';
      fpImage.style.backgroundImage = `url('${back}')`;
    }
  });""",
    "过曝开关切高亮图",
)

# A16. state 加 search/camera 两个筛选维度
once(
    "  const state = { filter: 'all', folder: 'all', view: 'time', selected: new Set(), stackMode: true };",
    "  const state = { filter: 'all', folder: 'all', view: 'time', selected: new Set(), stackMode: true, search: '', camera: 'all' };",
    "state加search/camera",
)

# A17. render 筛选加 搜索 + 机型 两个条件
once(
    """        : Array.isArray(state.folder) ? state.folder.includes(p.folder) : p.folder === state.folder;
      return tierOk && folderOk;""",
    """        : Array.isArray(state.folder) ? state.folder.includes(p.folder) : p.folder === state.folder;
      const q = state.search.trim().toLowerCase();
      const searchOk = !q || (p.filename && p.filename.toLowerCase().includes(q));
      const cameraOk = state.camera === 'all' || p.cam === state.camera;
      return tierOk && folderOk && searchOk && cameraOk;""",
    "render加搜索+机型筛选",
)

# A18. 搜索框加 id
once(
    '          <input type="text" placeholder="搜索文件名、标签…" />',
    '          <input type="text" id="search-input" placeholder="搜索文件名、标签…" />',
    "搜索框加id",
)

# A19. 机型筛选按钮文字包 span（便于只更新文字不动图标）
once(
    "          筛选 · 全部机型\n",
    '          <span id="filter-label">筛选 · 全部机型</span>\n',
    "机型按钮文字包span",
)

# A20. 快捷键：全屏下 1/2/3/0 打分、e 外部打开
once(
    "    if (e.key === 'ArrowRight') { el('#fp-next').click(); return; }\n  });",
    """    if (e.key === 'ArrowRight') { el('#fp-next').click(); return; }
    // 若焦点在输入框(如搜索框)，不把数字/字母当快捷键，避免既打分又输入
    if (/^(INPUT|TEXTAREA)$/.test((e.target && e.target.tagName) || '')) return;
    // 快捷键打分：1废片 2可修 3精选 0待分析；e 用外部程序打开原文件
    const kp = PHOTOS.find(x => x.id === fpPhotoId);
    if (kp && ['1','2','3','0'].includes(e.key)) {
      kp.tier = { '1': 'bad', '2': 'fix', '3': 'good', '0': null }[e.key];
      window.pywebview.api.set_tier(kp.id, kp.tier);
      document.querySelectorAll('#dp-tier-picker .tier-btn').forEach(b => b.classList.toggle('active', b.dataset.tier === kp.tier));
      render();
      showToast(kp.tier ? `已标记为「${TIER_LABEL[kp.tier]}」` : '已标记为「待分析」');
      return;
    }
    if (kp && (e.key === 'e' || e.key === 'E')) {
      window.pywebview.api.open_external(kp.id).then(r => {
        if (r && !r.opened) showToast('原文件不可访问，无法打开（可能卡已拔出）');
      });
      return;
    }
  });""",
    "快捷键打分+外部打开",
)

# A21. 搜索/机型筛选的事件监听（注入到 applyDensity 初始化之后）
once(
    "  applyDensity(savedDensity);",
    """  applyDensity(savedDensity);

  // 搜索：防抖过滤(避免每敲一键就重画1000+张导致卡顿/丢字) + 加载动效 + 清除
  function resetSearchState() {
    const si = document.getElementById('search-input');
    if (si) si.value = '';
    state.search = '';
    const sf = document.querySelector('.search-field');
    if (sf) sf.classList.remove('has-text', 'searching');
  }
  function clearSearch() { resetSearchState(); render(); }
  (function () {
    const si = document.getElementById('search-input');
    if (!si) return;
    const sf = si.closest('.search-field');
    let debTimer;
    si.addEventListener('input', () => {
      state.search = si.value;
      if (sf) { sf.classList.toggle('has-text', si.value.length > 0); sf.classList.add('searching'); }
      clearTimeout(debTimer);
      debTimer = setTimeout(() => {
        render();
        if (sf) sf.classList.remove('searching');
      }, 250);
    });
    const cb = document.getElementById('search-clear');
    if (cb) cb.addEventListener('click', clearSearch);
  })();
  // 按机型筛选：点击循环切换 全部机型→各机型→全部
  (function () {
    const bf = document.getElementById('btn-filter');
    if (!bf) return;
    bf.addEventListener('click', () => {
      const cams = ['all', ...Array.from(new Set(PHOTOS.map(p => p.cam).filter(Boolean)))];
      const i = cams.indexOf(state.camera);
      state.camera = cams[(i + 1) % cams.length];
      const label = document.getElementById('filter-label');
      if (label) label.textContent = state.camera === 'all' ? '筛选 · 全部机型' : '筛选 · ' + state.camera;
      render();
    });
  })();""",
    "搜索+机型筛选监听",
)

# A22. 搜索框加清除(×)按钮
once(
    '          <input type="text" id="search-input" placeholder="搜索文件名、标签…" />',
    '          <input type="text" id="search-input" placeholder="搜索文件名、标签…" />\n          <button id="search-clear" class="search-clear" type="button" aria-label="清除搜索" title="清除">×</button>',
    "搜索框加清除按钮",
)

# A23. CSS：搜索框不被工具栏挤压 + 清除按钮 + 搜索中动效(放大镜转圈)
once(
    ".search-field svg { width: 14px; height: 14px; color: var(--meta); flex: 0 0 auto; }",
    """.search-field svg { width: 14px; height: 14px; color: var(--meta); flex: 0 0 auto; }
.search-field { flex: 0 0 auto; }
.search-clear { display: none; border: none; background: transparent; color: var(--meta); cursor: pointer; font-size: 17px; line-height: 1; padding: 0 2px; flex: 0 0 auto; }
.search-clear:hover { color: var(--fg); }
.search-field.has-text .search-clear { display: block; }
.search-field.searching svg { animation: sg-spin 0.7s linear infinite; }
@keyframes sg-spin { to { transform: rotate(360deg); } }""",
    "搜索框CSS(不压缩+清除+动效)",
)

# A24. 点质量档位导航时退出搜索
once(
    """  el('#tier-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.side-item');
    if (!btn) return;""",
    """  el('#tier-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.side-item');
    if (!btn) return;
    resetSearchState();""",
    "档位导航退出搜索",
)

# A25. 点文件夹导航时退出搜索
once(
    "  el('#folder-nav').addEventListener('click', (e) => {\n    const combineBtn = e.target.closest('#btn-combine-folders');",
    "  el('#folder-nav').addEventListener('click', (e) => {\n    resetSearchState();\n    const combineBtn = e.target.closest('#btn-combine-folders');",
    "文件夹导航退出搜索",
)

# ══════════ B. 无边框窗口外观 ══════════

# B1. app-window 去圆角+阴影（现在它就是真窗口，圆角会露黑角）
once(
    "  background: var(--bg);\n  border-radius: var(--radius-lg);\n  box-shadow: 0 40px 90px rgba(0,0,0,0.45);\n  overflow: hidden;",
    "  background: var(--bg);\n  border-radius: 0;\n  box-shadow: none;\n  overflow: hidden;",
    "app-window去圆角阴影",
)

# B1.5 去掉 app-window 尺寸上限（原型设计成"桌面里的一个卡片窗口"故限1600x1000，
#      但现在它就是真窗口，最大化时若被卡在1600x1000居中，四周会露出body白底）
once(
    "  width: 100vw;\n  height: 100vh;\n  max-width: 1600px;\n  max-height: 1000px;",
    "  width: 100vw;\n  height: 100vh;",
    "去app-window尺寸上限",
)

# B2. body 深色背景 → --bg
once(
    "body {\n  margin: 0;\n  background: var(--backdrop);",
    "body {\n  margin: 0;\n  background: var(--bg);",
    "body背景改bg",
)

# B3. 标题栏可拖动
once(
    '  <div class="titlebar" data-od-id="titlebar">',
    '  <div class="titlebar pywebview-drag-region" data-od-id="titlebar">',
    "标题栏可拖动",
)

# B4. 窗口控制区不参与拖动
once(
    '    <div class="win-controls" data-od-id="window-controls">',
    '    <div class="win-controls pywebview-no-drag" data-od-id="window-controls">',
    "窗口控制区no-drag",
)

# B5-B7. 三个窗口按钮加 id
once('      <button class="win-btn" aria-label="最小化">',
     '      <button class="win-btn" id="win-min" aria-label="最小化">', "最小化按钮id")
once('      <button class="win-btn" aria-label="最大化">',
     '      <button class="win-btn" id="win-max" aria-label="最大化">', "最大化按钮id")
once('      <button class="win-btn win-close" aria-label="关闭">',
     '      <button class="win-btn win-close" id="win-close" aria-label="关闭">', "关闭按钮id")

# B8. 标题栏文字去掉假路径
once(
    '    <span class="tl-title">拾光 ShiGuang — D:\\DCIM\\100CANON</span>',
    '    <span class="tl-title">拾光 ShiGuang</span>',
    "标题栏文字",
)

# ══════════ C. 小改动 ══════════

# C1. 删除所选 → 删除已选
once('删除所选（<span id="sel-count">0</span>）',
     '删除已选（<span id="sel-count">0</span>）', "删除按钮文字")

# C2. 分类视图未分析时给提示
once(
    """    } else {
      const groups = [
        { key: 'pending', label: PENDING_LABEL, dotVar: 'meta' },
        { key: 'bad', label: TIER_LABEL.bad, dotVar: 'danger' },
        { key: 'fix', label: TIER_LABEL.fix, dotVar: 'warn' },
        { key: 'good', label: TIER_LABEL.good, dotVar: 'success' },
      ];
      groups.forEach(g => {""",
    """    } else {
      const analyzedCount = list.filter(p => p.tier !== null).length;
      if (analyzedCount === 0) {
        html = '<p style="color:var(--muted); padding:48px; text-align:center; line-height:1.7;">这些照片还没有分析。<br>点击左侧「开始分析」，软件会把它们分成 废片 / 可修 / 精选 后在这里按类查看。</p>';
      }
      const groups = analyzedCount === 0 ? [] : [
        { key: 'pending', label: PENDING_LABEL, dotVar: 'meta' },
        { key: 'bad', label: TIER_LABEL.bad, dotVar: 'danger' },
        { key: 'fix', label: TIER_LABEL.fix, dotVar: 'warn' },
        { key: 'good', label: TIER_LABEL.good, dotVar: 'success' },
      ];
      groups.forEach(g => {""",
    "分类视图未分析提示",
)

# ══════════ D. 自动评分（Phase 2C）══════════

# D1.「开始分析」按钮接真实 P0 评分（替代 demo 的 tier=autoTier 假填充）
once(
    """  el('#btn-analyze').addEventListener('click', () => {
    const pending = PHOTOS.filter(p => p.tier === null);
    if (!pending.length) return;
    el('#btn-analyze').disabled = true;
    showToast(`正在分析 ${pending.length} 张照片的清晰度与曝光…`);
    setTimeout(() => {
      pending.forEach(p => { p.tier = p.autoTier; });
      render();
      showToast(`已完成 ${pending.length} 张照片的分析`);
    }, 900);
  });""",
    """  el('#btn-analyze').addEventListener('click', async () => {
    const pending = PHOTOS.filter(p => p.tier === null);
    // 旧数据虽已定档但缺感知哈希(__needsWork>0)，也要能点分析去补(出堆叠+用新模型重评)
    if (!pending.length && !(window.__needsWork > 0)) return;
    el('#btn-analyze').disabled = true;
    showToast(`正在分析 ${Math.max(pending.length, window.__needsWork || 0)} 张照片的清晰度与曝光…`);
    // 真实后台评分：清晰度(分块拉普拉斯+Tenengrad) + 曝光裁切 + 噪点 → 三档
    const result = await window.pywebview.api.analyze_all();
    if (result && result.error) {
      showToast('分析失败：' + result.error);
      el('#btn-analyze').disabled = false;
      return;
    }
    PHOTOS.length = 0;
    (result.photos || []).forEach(p => PHOTOS.push(p));
    window.__needsWork = 0;   // 这一趟已把待处理(未定档+缺phash)都跑完
    render();
    showToast(`已完成 ${result.analyzed} 张照片的分析`);
  });
  // 后台评分逐张进度推送（api.analyze_all 每处理完一张调一次）
  window.onAnalyzeProgress = function (done, total) {
    const c = el('#analyze-count');
    if (c) c.textContent = (total - done);
    if (window.sgProgress) window.sgProgress(done, total, '正在分析照片');
  };""",
    "开始分析接真实评分",
)

# ══════════ F. 托盘挂机：关闭按钮改为"最小化到托盘/退出"确认（Phase 2E）══════════

# F1. 关闭按钮(X) → 弹确认框问"最小化到托盘 还是 退出"，可勾选记住选择
once(
    "  document.getElementById('win-close').addEventListener('click', () => window.pywebview.api.close_window());",
    """  document.getElementById('win-close').addEventListener('click', () => handleCloseRequest());

  // 关闭按钮行为：托盘=隐藏后台继续检测插卡；退出=真正关进程。可记住选择(localStorage)
  function doCloseAction(action) {
    if (action === 'quit') window.pywebview.api.quit_app();
    else window.pywebview.api.hide_to_tray();
  }
  async function handleCloseRequest() {
    const pref = localStorage.getItem('shiguang-close-pref');
    if (pref === 'quit') { doCloseAction('quit'); return; }
    let trayOk = true;
    try { trayOk = await window.pywebview.api.tray_available(); } catch (e) {}
    // 记住了"最小化"且托盘可用 → 直接执行；托盘不可用时不能静默隐藏(窗口会回不来)，
    // 仍弹框让用户至少能选"退出"。
    if (pref === 'tray' && trayOk) { doCloseAction('tray'); return; }
    showCloseDialog(trayOk);
  }
  function showCloseDialog(trayOk) {
    if (document.getElementById('close-modal')) return;   // 已弹出就不重复弹
    const back = document.createElement('div');
    back.className = 'modal-backdrop';
    back.id = 'close-modal';
    const minLabel = trayOk ? '最小化到托盘' : '最小化到任务栏';
    const sub = trayOk
      ? '最小化到托盘可以让它在后台继续检测存储卡；退出则完全关闭程序。'
      : '托盘不可用，将改为最小化到任务栏（后台检测会停止）；退出则完全关闭程序。';
    back.innerHTML = `
      <div class="modal-card" style="max-width:380px;">
        <h2>关闭拾光</h2>
        <p class="modal-sub">${sub}</p>
        <label class="no-drag" style="display:flex; align-items:center; gap:8px; margin:4px 0 6px; font-size:13px; color:var(--muted); cursor:pointer;">
          <input type="checkbox" id="close-remember" /> 记住我的选择（之后不再询问）
        </label>
        <div class="modal-actions">
          <button class="btn btn-sm" id="close-quit">退出</button>
          <button class="btn btn-primary btn-sm" id="close-tray">${minLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(back);
    const finish = (action) => {
      if (document.getElementById('close-remember').checked) {
        localStorage.setItem('shiguang-close-pref', action);
      }
      back.remove();
      doCloseAction(action);
    };
    document.getElementById('close-tray').addEventListener('click', () => finish('tray'));
    document.getElementById('close-quit').addEventListener('click', () => finish('quit'));
    // 点遮罩空白处 = 取消关闭(什么都不做)
    back.addEventListener('click', (e) => { if (e.target === back) back.remove(); });
  }""",
    "关闭按钮改托盘/退出确认",
)

# ══════════ E. 存储卡自动检测（Phase 2E）══════════

# E1. 定义 showCardModal(用真实检测结果填充弹窗) + 启动时主动拉一次 + 接收后台推送
once(
    "  function closeImport() { importModal.classList.add('hidden'); }",
    """  function closeImport() { importModal.classList.add('hidden'); }

  // 用后端检测到的真实卡数据填充「检测到存储卡」弹窗并打开它
  function sgEscHtml(s) {
    return String(s).replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
  }
  function showCardModal(card) {
    if (!card || !(card.folders || []).length) return;
    folderCheckList.innerHTML = card.folders.map(f => `
      <label class="folder-check-item">
        <input type="checkbox" checked data-count="${f.count}" data-size="${(f.size_mb/1024).toFixed(3)}" />
        <svg class="folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>
        <span class="folder-check-name">${sgEscHtml(f.name)}<span class="folder-check-path">${sgEscHtml(f.path)}</span></span>
        <span class="folder-check-meta">${f.count} 张</span>
      </label>`).join('');
    // 真实路径用 property 赋值(不走HTML属性)，避免路径里的反斜杠/特殊字符转义问题
    Array.from(folderCheckList.querySelectorAll('input')).forEach((cb, i) => { cb.value = card.folders[i].path; });
    openImport();
  }
  // 后台监听线程检测到新插入的卡 → 推来这里弹窗
  window.onCardDetected = showCardModal;
  // 覆盖"开软件时卡已经插着"：启动主动叫后端检测当前插着的卡，有照片就弹独立小导入窗
  // (走和运行时插卡同一条 present_card 路径，行为一致——都是小窗，不弹主窗内嵌框)。
  (async () => {
    try { await window.pywebview.api.popup_cards_now(); } catch (e) {}
  })();""",
    "存储卡弹窗填充+启动检测",
)

# E2.「确认导入」接真实多文件夹导入(替代 demo 的假勾选)
once(
    """  el('#btn-confirm-import').addEventListener('click', () => {
    const checked = Array.from(folderCheckList.querySelectorAll('input:checked')).map(cb => cb.value);
    checked.forEach(f => { if (!importedFolders.includes(f)) importedFolders.push(f); });
    const total = checked.reduce((sum, f) => sum + (FOLDER_META[f]?.count || 0), 0);
    closeImport();
    render();
    showToast(checked.length
      ? `已导入 ${total} 张照片 · 前往侧边栏点击「开始分析」`
      : '未勾选任何文件夹，没有导入照片');
  });""",
    """  el('#btn-confirm-import').addEventListener('click', async () => {
    const checked = Array.from(folderCheckList.querySelectorAll('input:checked')).map(cb => cb.value);
    if (!checked.length) { showToast('未勾选任何文件夹'); return; }
    const confirmBtn = el('#btn-confirm-import');
    confirmBtn.disabled = true;   // 导入期间禁用，防连点触发多次 import_folders
    closeImport();
    showToast(`正在导入 ${checked.length} 个文件夹…`);
    try {
      const result = await window.pywebview.api.import_folders(checked);
      if (result && result.error) { showToast('导入失败：' + result.error); return; }
      PHOTOS.length = 0;
      (result.photos || []).forEach(p => PHOTOS.push(p));
      await refreshFolders();
      render();
      renderFolderNav();
      showToast(`已导入 ${result.imported} 张 · 前往侧边栏点击「开始分析」`);
    } finally {
      confirmBtn.disabled = false;
    }
  });""",
    "确认导入接真实多文件夹",
)

# ══════════ G. 性能与交互修复（大库卡顿/选中跳动/取消选择/响应式）══════════

# G1. 网格缩略图改懒加载：不再内联 background-image(会让上千张图一次性全请求→慢慢渗
#     出来/载不全)，改成 data-thumb，由 IntersectionObserver 只加载进入视口的那些。
times(
    """        <div class="photo-thumb" style="background-image:url('${p.thumbnail || ''}')">""",
    """        <div class="photo-thumb" data-thumb="${p.thumbnail || ''}">""",
    2,
    "缩略图懒加载(data-thumb)",
)

# G2. render() 写完 innerHTML 后，给可见卡片挂懒加载观察器(全局只建一次)
once(
    """    contentEl.innerHTML = html || '<p style="color:var(--muted); padding:40px; text-align:center;">该分类下暂无照片</p>';""",
    """    contentEl.innerHTML = html || '<p style="color:var(--muted); padding:40px; text-align:center;">该分类下暂无照片</p>';
    if (!window.__thumbObserver) {
      // rootMargin 提前 300px 开始加载，滚动时不至于看到空白格
      window.__thumbObserver = new IntersectionObserver((entries) => {
        entries.forEach(en => {
          if (!en.isIntersecting) return;
          const d = en.target;
          if (d.dataset.thumb) { d.style.backgroundImage = `url('${d.dataset.thumb}')`; d.removeAttribute('data-thumb'); }
          window.__thumbObserver.unobserve(d);
        });
      }, { root: contentEl, rootMargin: '400px' });   // root=滚动容器#content，否则内部滚动不触发加载
    }
    contentEl.querySelectorAll('.photo-thumb[data-thumb]').forEach(d => window.__thumbObserver.observe(d));""",
    "懒加载观察器",
)

# G3. 单击选中：只切当前卡片的 selected 类 + 刷工具栏，不再整页 render()(避免重载全部
#     缩略图 + innerHTML 重建导致滚动位置重置→"页面往上跳")
once(
    """  contentEl.addEventListener('click', (e) => {
    if (e.target.closest('.stack-card')) return; // handled by the stack click listener below
    const card = e.target.closest('.photo-card');
    if (!card || e.detail > 1) return; // detail>1 belongs to a dblclick gesture
    const id = Number(card.dataset.id);
    state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id);
    render();
  });""",
    """  contentEl.addEventListener('click', (e) => {
    if (e.target.closest('.stack-card')) return; // handled by the stack click listener below
    const card = e.target.closest('.photo-card');
    if (!card || e.detail > 1) return; // detail>1 belongs to a dblclick gesture
    const id = Number(card.dataset.id);
    if (state.selected.has(id)) { state.selected.delete(id); card.classList.remove('selected'); }
    else { state.selected.add(id); card.classList.add('selected'); }
    refreshToolbar();   // 只更新选中计数/按钮，不重建网格(不跳、不重载图)
  });""",
    "单击选中不重建网格",
)

# G4. 双击预览：同样把"撤销单击那次选中"从 render() 改成只切类，避免跳动
once(
    """    const id = Number(card.dataset.id);
    state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id);
    render();
    openFullscreenPreview(id);""",
    """    const id = Number(card.dataset.id);
    if (state.selected.has(id)) { state.selected.delete(id); card.classList.remove('selected'); }
    else { state.selected.add(id); card.classList.add('selected'); }
    refreshToolbar();
    openFullscreenPreview(id);""",
    "双击预览不重建网格",
)

# G5. refreshToolbar 增加"取消选择"按钮的显隐与计数
once(
    """  function refreshToolbar() {
    const n = state.selected.size;
    el('#sel-count').textContent = n;
    el('#btn-delete').disabled = n === 0;
  }""",
    """  function refreshToolbar() {
    const n = state.selected.size;
    el('#sel-count').textContent = n;
    el('#btn-delete').disabled = n === 0;
    const cs = el('#btn-clear-sel');
    if (cs) { cs.style.display = n > 0 ? '' : 'none'; const csc = el('#clear-sel-count'); if (csc) csc.textContent = n; }
  }""",
    "工具栏取消选择按钮显隐",
)

# G6. 工具栏加"取消选择"按钮(默认隐藏，有选中才显示)——不区分档位，一键清空所有选中。
#     放在"对比模式"按钮之前(用户要求)。
once(
    '        <button class="btn btn-sm" id="btn-compare">',
    '        <button class="btn btn-sm" id="btn-clear-sel" style="display:none;">取消选择（<span id="clear-sel-count">0</span>）</button>\n        <button class="btn btn-sm" id="btn-compare">',
    "工具栏加取消选择按钮",
)

# G7. 「取消选择」按钮逻辑：清空选中集 + 去掉所有卡片的 selected 类 + 刷工具栏(不重建网格)
once(
    """  el('#btn-delete').addEventListener('click', () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    state.selected.clear();
    commitDeleteAfterUndoWindow(ids, `已删除 ${ids.length} 张照片`);
  });""",
    """  el('#btn-delete').addEventListener('click', () => {
    const ids = [...state.selected];
    if (!ids.length) return;
    state.selected.clear();
    commitDeleteAfterUndoWindow(ids, `已删除 ${ids.length} 张照片`);
  });

  el('#btn-clear-sel').addEventListener('click', () => {
    state.selected.clear();
    contentEl.querySelectorAll('.photo-card.selected').forEach(c => c.classList.remove('selected'));
    refreshToolbar();
  });""",
    "取消选择按钮逻辑",
)

# G9. 响应式：工具栏窄了自动换行(不再把右侧按钮挤出屏幕看不见)；侧边栏窄屏收窄
once(
    """.toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);""",
    """.toolbar {
  flex: 0 0 auto;
  display: flex;
  flex-wrap: wrap;            /* 窗口变窄时按钮换行，保证全部可见，不被挤出屏幕 */
  row-gap: 8px;
  align-items: center;
  gap: var(--space-3);""",
    "工具栏响应式换行",
)

# ══════════ H. 全屏原图 + 对比精细版 + 放大倍率（详情看图质量）══════════

# H1. 对比模式的每格改用2560精细版(默认是512缩略图，糊)；缺的异步拉、拉到重绘
once(
    """          <div class="compare-cell-img${zoom > 1 ? ' zoomed' : ''}" data-zoomimg="${p.id}" style="background-image:url('${p.thumbnail || ''}'); transform:translate(${pan.x}px, ${pan.y}px) scale(${zoom});"></div>""",
    """          <div class="compare-cell-img${zoom > 1 ? ' zoomed' : ''}" data-zoomimg="${p.id}" style="background-image:url('${(window.__cmpPreview && window.__cmpPreview[p.id]) || p.thumbnail || ''}'); transform:translate(${pan.x}px, ${pan.y}px) scale(${zoom}) rotate(${(p.rotation || 0)}deg);"></div>""",
    "对比格用精细版",
)

# H2. renderCompare 末尾：给对比中的每张按需拉2560预览，拉到后重绘那一格
once(
    """        </div>`;
    }).join('');
  }

  function removeFromCompare(id) {""",
    """        </div>`;
    }).join('');
    // 对比看图要清晰：给每张按需拉 2560 精细版(比512缩略图清楚)，拉到后重绘
    window.__cmpPreview = window.__cmpPreview || {};
    window.__cmpLoading = window.__cmpLoading || {};
    items.forEach(p => {
      if (window.__cmpPreview[p.id] || window.__cmpLoading[p.id]) return;
      window.__cmpLoading[p.id] = true;
      window.pywebview.api.get_preview(p.id).then(res => {
        window.__cmpLoading[p.id] = false;
        if (res && res.url) { window.__cmpPreview[p.id] = res.url; if (compareOverlay.classList.contains('open')) renderCompare(); }
      });
    });
  }

  function removeFromCompare(id) {""",
    "对比按需拉精细版",
)

# H3. 全屏：放大上限 8→16 倍；放大到>2倍时按需换真正原图(全分辨率)看清细节
once(
    """  fpStage.addEventListener('wheel', (e) => {
    e.preventDefault();
    fpZoom += e.deltaY < 0 ? 0.4 : -0.4;
    fpZoom = Math.min(8, Math.max(1, fpZoom));
    fpPan = clampFpPan(fpZoom, fpPan);
    applyFpTransform();
  }, { passive: false });""",
    """  fpStage.addEventListener('wheel', (e) => {
    e.preventDefault();
    fpZoom += e.deltaY < 0 ? 0.4 : -0.4;
    fpZoom = Math.min(16, Math.max(1, fpZoom));
    fpPan = clampFpPan(fpZoom, fpPan);
    applyFpTransform();
    if (fpZoom > 2) ensureFpOriginal(fpPhotoId);   // 放大细看时换真正原图，看清像素/对焦
  }, { passive: false });

  // 放大到高倍时按需加载原图(全分辨率)替掉2560预览，让像素级细节清晰(检查对焦用)。
  // 原图大且慢，只在真放大某张时才调；拉到后若还停在这张、仍放大、没开过曝高亮才换上。
  function ensureFpOriginal(id) {
    window.__origShown = window.__origShown || {};
    window.__origLoading = window.__origLoading || {};
    if (window.__origShown[id]) {
      if (fpPhotoId === id && !el('#expo-switch').classList.contains('on')) {
        fpImage.style.backgroundImage = `url('${window.__origShown[id]}')`;
      }
      return;
    }
    if (window.__origLoading[id]) return;
    window.__origLoading[id] = true;
    window.pywebview.api.get_original(id).then(res => {
      window.__origLoading[id] = false;
      if (res && res.url) {
        window.__origShown[id] = res.url;
        const hi = new Image();
        hi.onload = () => {
          if (fpPhotoId === id && fpZoom > 1 && !el('#expo-switch').classList.contains('on')) {
            fpImage.style.backgroundImage = `url('${res.url}')`;
          }
        };
        hi.src = res.url;
      }
    });
  }""",
    "全屏放大倍率+原图",
)

# H4. 对比模式放大上限也 8→16 倍
once(
    "    zoom = Math.min(8, Math.max(1, zoom));",
    "    zoom = Math.min(16, Math.max(1, zoom));",
    "对比放大倍率16",
)

# ══════════ I. 文件夹拖拽删除接真删库（Phase 2E 扩展）══════════

# I1. 工作台的 deleteFolder(纯前端+undo) 接后端：延迟5秒真的从数据库移除该文件夹
#     所有照片记录+清缓存(不删原文件)；undo 窗口内撤销则取消删库。
once(
    """    render();
    showToast(`已删除文件夹「${f}」及其 ${removedPhotos.length} 张照片`, {
      undo: () => {
        importedFolders.splice(folderIdx, 0, f);
        PHOTOS.push(...removedPhotos);
        prevState.selected.forEach(id => state.selected.add(id));
        if (prevState.wasStagedForCombine) selectedFolderSet.add(f);
        state.folder = prevState.folder;
        isCombinedView = prevState.isCombinedView;
        previousFolderView = prevState.previousFolderView;
        render();
      },
    });""",
    """    render();
    renderFolderNav();
    // 延迟真删库：5秒 undo 窗口内不撤销，才真的从数据库移除该文件夹的照片记录+清缓存
    // (不删原始照片文件，见后端 forget_folder 说明)。撤销则清掉这个定时器。
    const forgetIds = [...removedIds];   // 锁定当时这批id，避免延迟提交误删期间新导入的同名文件夹照片
    const forgetTimer = setTimeout(() => {
      window.pywebview.api.forget_photos(forgetIds).then(() => refreshFolders());
    }, 5000);
    showToast(`已从相册移除文件夹「${f}」及其 ${removedPhotos.length} 张照片`, {
      undo: () => {
        clearTimeout(forgetTimer);
        importedFolders.splice(folderIdx, 0, f);
        PHOTOS.push(...removedPhotos);
        prevState.selected.forEach(id => state.selected.add(id));
        if (prevState.wasStagedForCombine) selectedFolderSet.add(f);
        state.folder = prevState.folder;
        isCombinedView = prevState.isCombinedView;
        previousFolderView = prevState.previousFolderView;
        render();
        renderFolderNav();
      },
    });""",
    "文件夹删除接真删库",
)

# ══════════ J. 全屏细看旋转（顺/逆时针，持久化）══════════

# J1. 声明当前全屏图的旋转角 + 旋转适配缩放(90/270度时把长边缩进短边视口，防裁切)
once(
    "  let fpZoom = 1;",
    "  let fpZoom = 1;\n  let fpRotation = 0;   // 当前全屏图的显示旋转角(0/90/180/270)\n  let fpFit = 1;        // 旋转90/270度时的适配缩放，防转正后长边超出横向视口被裁",
    "声明fpRotation",
)

# J2. 把旋转+适配缩放叠进 transform（applyFpTransform 和拖动 mousemove 两处都要）
times(
    "    fpImage.style.transform = `translate(${fpPan.x}px, ${fpPan.y}px) scale(${fpZoom})`;",
    "    fpImage.style.transform = `translate(${fpPan.x}px, ${fpPan.y}px) scale(${fpZoom * (fpFit || 1)}) rotate(${fpRotation || 0}deg)`;",
    2,
    "全屏应用旋转",
)

# J3. 打开某张全屏时，从该照片的持久化 rotation 恢复旋转角
once(
    """    fpPhotoId = id;
    fpZoom = 1;
    fpPan = { x: 0, y: 0 };
    applyFpTransform();""",
    """    fpPhotoId = id;
    fpZoom = 1;
    fpPan = { x: 0, y: 0 };
    fpRotation = (PHOTOS.find(x => x.id === id) || {}).rotation || 0;
    computeFpFit();
    // 切换到新照片时瞬间摆到它自己的角度，不要带旋转动画(否则会从上一张的角度绕过去)
    fpImage.style.transition = 'none';
    applyFpTransform();
    void fpImage.offsetWidth;
    fpImage.style.transition = '';""",
    "全屏恢复旋转角",
)

# J4. 全屏两个旋转按钮放进 .fp-stage 内(与照片区域绑定)：详情面板打开时 stage 右边
#     缩进 380px，按钮跟着照片区域走，不再与右侧详情面板重合(同 prev/next 导航按钮做法)。
once(
    '''      <span class="fp-hint" id="fp-hint">滚轮缩放放大 · 可拖动查看</span>''',
    '''      <button class="fp-icon-btn" id="fp-rotate-ccw" aria-label="逆时针旋转90°" style="top:auto; bottom:16px; left:16px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/></svg>
      </button>
      <button class="fp-icon-btn" id="fp-rotate-cw" aria-label="顺时针旋转90°" style="top:auto; bottom:16px; right:16px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v4h-4"/></svg>
      </button>
      <span class="fp-hint" id="fp-hint">滚轮缩放放大 · 可拖动查看</span>''',
    "全屏旋转按钮(放stage内)",
)

# J5. 旋转逻辑：改角度→应用→更新本地→持久化到数据库
once(
    "  const fpToggleInfo = el('#fp-toggle-info');",
    """  const fpToggleInfo = el('#fp-toggle-info');
  // 旋转90/270度时把图的长边缩进短边视口，避免转正后上下被裁
  function computeFpFit() {
    const s = fpStage.getBoundingClientRect();
    fpFit = (fpRotation % 180 !== 0 && s.width && s.height)
      ? Math.min(s.width, s.height) / Math.max(s.width, s.height) : 1;
  }
  // 旋转当前全屏图：delta=+90顺时针/-90逆时针。fpRotation 连续累加、**不归一化**，
  // 这样 CSS transition 永远只转最近的 90°，不会在跨 0/360 边界时倒着绕一整圈。
  // 存库/存本地时才归一化到 0/90/180/270（后端 rotate_photo 也 %360）。
  function rotateFp(delta) {
    if (fpPhotoId == null) return;
    fpRotation = (fpRotation || 0) + delta;
    computeFpFit();
    applyFpTransform();
    const idx = PHOTOS.findIndex(x => x.id === fpPhotoId);
    if (idx >= 0) PHOTOS[idx].rotation = ((fpRotation % 360) + 360) % 360;
    try { window.pywebview.api.rotate_photo(fpPhotoId, delta); } catch (e) {}
  }
  const fpRotCw = el('#fp-rotate-cw');
  if (fpRotCw) fpRotCw.addEventListener('click', () => rotateFp(90));
  const fpRotCcw = el('#fp-rotate-ccw');
  if (fpRotCcw) fpRotCcw.addEventListener('click', () => rotateFp(-90));""",
    "全屏旋转逻辑",
)

# ══════════ K. 详情单张删除 + 对比模式每张旋转 ══════════

# K1. 全屏详情加"删除这张"按钮(放在关闭按钮左边)
once(
    '''    <button class="fp-icon-btn fp-close" id="fp-close" aria-label="关闭">''',
    '''    <button class="fp-icon-btn" id="fp-delete" aria-label="删除这张" style="right:108px;">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0 1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/></svg>
    </button>
    <button class="fp-icon-btn fp-close" id="fp-close" aria-label="关闭">''',
    "全屏删除按钮",
)

# K2. 全屏删除按钮逻辑：删当前这张(送回收站+可撤销)并关闭全屏
once(
    "  el('#fp-close').addEventListener('click', closeFullscreenPreview);",
    """  el('#fp-close').addEventListener('click', closeFullscreenPreview);
  const fpDelete = el('#fp-delete');
  if (fpDelete) fpDelete.addEventListener('click', () => {
    const id = fpPhotoId;
    if (id == null) return;
    closeFullscreenPreview();
    trashPhoto(id);   // 复用单张删除(送回收站+5秒可撤销)
  });""",
    "全屏删除逻辑",
)

# K3. 对比模式每格加"旋转"按钮(顺时针90°，持久化)
once(
    '''              <button class="cc-icon-btn cc-del" data-del="${p.id}" aria-label="从对比中移除">''',
    '''              <button class="cc-icon-btn cc-rotate" data-rotate="${p.id}" aria-label="顺时针旋转90°"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v4h-4"/></svg></button>
              <button class="cc-icon-btn cc-del" data-del="${p.id}" aria-label="从对比中移除">''',
    "对比旋转按钮",
)

# K4. 对比旋转按钮逻辑：转90°+持久化+重绘该对比视图
once(
    """    const trashBtn = e.target.closest('[data-trash]');
    if (trashBtn) { trashPhoto(Number(trashBtn.dataset.trash)); return; }""",
    """    const trashBtn = e.target.closest('[data-trash]');
    if (trashBtn) { trashPhoto(Number(trashBtn.dataset.trash)); return; }

    const rotBtn = e.target.closest('[data-rotate]');
    if (rotBtn) {
      const id = Number(rotBtn.dataset.rotate);
      const p = PHOTOS.find(x => x.id === id);
      if (p) {
        p.rotation = ((p.rotation || 0) + 90) % 360;
        try { window.pywebview.api.rotate_photo(id, 90); } catch (e2) {}
        renderCompare();
      }
      return;
    }""",
    "对比旋转逻辑",
)

# ══════════ N. 全屏详情面板默认关闭(点详情按钮才开) ══════════

# N1. 详情面板开合改由 fpInfoOpen 状态驱动，默认 false(关)。工作台原型 HTML 里带的
#     info-open/open/active 默认打开 class 不动(方式C:外观归工作台)，而是每次打开全屏
#     时用 applyFpInfo() 按 fpInfoOpen 复位——默认关闭；用户点开后，全屏内上一张/下一张
#     保持其上次开合。
once(
    """  fpToggleInfo.addEventListener('click', () => {
    const willOpen = !fpSidebar.classList.contains('open');
    fpSidebar.classList.toggle('open', willOpen);
    fpStage.classList.toggle('info-open', willOpen);
    fpToggleInfo.classList.toggle('active', willOpen);""",
    """  // 详情面板默认关闭，点详情按钮才打开。开合状态记在 fpInfoOpen，全屏内切上一张/
  // 下一张时保持用户上次的开合(openFullscreenPreview 里 applyFpInfo() 复位)。
  let fpInfoOpen = false;
  function applyFpInfo() {
    fpSidebar.classList.toggle('open', fpInfoOpen);
    fpStage.classList.toggle('info-open', fpInfoOpen);
    fpToggleInfo.classList.toggle('active', fpInfoOpen);
  }
  fpToggleInfo.addEventListener('click', () => {
    fpInfoOpen = !fpInfoOpen;
    applyFpInfo();""",
    "详情面板默认关闭",
)

# N2. 每次打开全屏都按 fpInfoOpen 复位面板(首次=关)。applyFpInfo 是函数声明(提升)，
#     fpInfoOpen 是 let——openFullscreenPreview 在用户交互时才跑，此时早已初始化，无 TDZ。
once(
    "    fpOverlay.classList.add('open');",
    """    applyFpInfo();   // 按当前 fpInfoOpen 决定详情面板开合(默认关)
    fpOverlay.classList.add('open');""",
    "全屏打开时复位详情面板",
)

# ══════════ M. 全屏删除键红色（破坏性操作醒目，苹果设计语言）══════════

# M1. 删除按钮填红色(--danger)，从一排灰按钮里跳出来当破坏性信号
once(
    ".fp-close { right: 16px; }",
    """.fp-close { right: 16px; }
#fp-delete { background: var(--danger); border-color: rgba(255,255,255,0.4); color: #fff; }
#fp-delete:hover { background: var(--danger); filter: brightness(1.12); }""",
    "删除键红色",
)

# ══════════ L. 深浅切换动画柔和化（排除照片网格避免上千元素同时重绘卡顿）══════════

# L1. 主题切换的过渡不作用于 #content(照片网格,可能上千张缩略图卡片)——上千元素同时
#     过渡颜色/重绘会明显掉帧;网格背景是图片、颜色几乎看不出变化,让它瞬间切换即可,
#     只让界面外壳(标题栏/工具栏/侧栏/面板/按钮)柔和过渡。
once(
    """  transition: background-color 380ms ease, color 380ms ease, border-color 380ms ease, box-shadow 380ms ease, fill 380ms ease, stroke 380ms ease !important;
}""",
    """  transition: background-color 380ms ease, color 380ms ease, border-color 380ms ease, box-shadow 380ms ease, fill 380ms ease, stroke 380ms ease !important;
}
/* 深浅切换柔和化：照片网格(可能上千张缩略图)不参与颜色过渡，避免上千元素同时重绘卡顿 */
html.theme-transitioning #content,
html.theme-transitioning #content * {
  transition: none !important;
}""",
    "深浅切换排除网格",
)

# ══════════ O. 连拍/相似堆叠接线（把工作台 mock STACKS 换成后端真实分组）══════════

# O1. mock STACKS 三条假数据 → 声明为空 + rebuildStackIndex(数据由 refreshStacks 从后端拉)
once(
    """  const STACKS = [
    { id: 'stack-1', memberIds: [1, 2, 3], cover: 1, burst: true, similar: false },
    { id: 'stack-2', memberIds: [9, 10], cover: 10, burst: false, similar: true },
    { id: 'stack-3', memberIds: [13, 14, 15, 16], cover: 14, burst: true, similar: true },
  ];
  // which member is currently marked "keep" per stack — starts at each
  // stack's recommended cover, but the user can reassign it by hand.
  const stackKeep = new Map(STACKS.map(s => [s.id, s.cover]));
  // stacks currently showing their expanded member strip.
  const expandedStacks = new Set();
  const photoIdToStack = new Map();
  STACKS.forEach(s => s.memberIds.forEach(id => photoIdToStack.set(id, s.id)));""",
    """  // 连拍/相似堆叠：真实分组由后端 list_stacks() 给(分析趟里算的 phash + 拍摄时间)，
  // 启动/重载/分析后 refreshStacks() 拉取；先空着，数据回来再由 rebuildStackIndex 填索引。
  let STACKS = [];
  let stackKeep = new Map();          // 每个 stack 当前"保留"的成员(默认=后端推荐的最锐封面)
  const expandedStacks = new Set();
  let photoIdToStack = new Map();
  function rebuildStackIndex() {
    stackKeep = new Map(STACKS.map(s => [s.id, s.cover]));
    photoIdToStack = new Map();
    STACKS.forEach(s => s.memberIds.forEach(id => photoIdToStack.set(id, s.id)));
  }""",
    "堆叠mock改真实数据源",
)

# O2. 定义 refreshStacks（放在 reloadPhotos 之前）
once(
    "  window.reloadPhotos = async function () {",
    """  // 从后端拉真实堆叠分组(连拍/相似)，重建索引；失败或空则清空(网格退回平铺)。
  async function refreshStacks() {
    try {
      const s = await window.pywebview.api.list_stacks();
      STACKS = Array.isArray(s) ? s : [];
    } catch (e) { STACKS = []; }
    rebuildStackIndex();
  }
  window.reloadPhotos = async function () {""",
    "定义refreshStacks",
)

# O3. reloadPhotos 与 initFromBackend 两处：拉完照片/文件夹后也刷新堆叠再渲染
times(
    """      await refreshFolders();
      render();
      renderFolderNav();""",
    """      await refreshFolders();
      await refreshStacks();
      render();
      renderFolderNav();""",
    3,
    "三处加载后刷新堆叠",
)

# O4. 分析完成后刷新堆叠（分析才算出 phash，堆叠此时才成形）
once(
    """    render();
    showToast(`已完成 ${result.analyzed} 张照片的分析`);""",
    """    await refreshStacks();
    render();
    showToast(`已完成 ${result.analyzed} 张照片的分析`);""",
    "分析后刷新堆叠",
)

# O5. 堆叠内删除某张 → 接真实后端删除(送回收站+5秒可撤销，与全局删除同款)
once(
    """    render();
    showToast(`已删除 ${removedPhoto ? removedPhoto.name : '该照片'}`, {
      undo: () => {
        stack.memberIds.splice(memberIdx, 0, photoId);""",
    """    render();
    // 乐观删除已更新UI；5秒后真正调后端把这张送回收站+删库记录，撤销则取消、后端从未被调。
    let committed = false;
    const timer = setTimeout(async () => {
      committed = true;
      try {
        const res = await window.pywebview.api.delete_photos([photoId]);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    }, 5000);
    showToast(`已删除 ${removedPhoto ? removedPhoto.name : '该照片'}`, {
      undo: () => {
        if (committed) return;
        clearTimeout(timer);
        stack.memberIds.splice(memberIdx, 0, photoId);""",
    "堆叠内删除接后端",
)

# O6. 分析按钮亮灯改用"待处理数"(未定档 + 旧数据缺phash)——否则旧库(都已定档)按钮恒灰，
#     没法点分析去补 phash 出堆叠。__needsWork 由 initFromBackend 从后端拉。
once(
    """  function refreshAnalyzeButton() {
    const pending = tierCounts().pending;
    el('#analyze-count').textContent = pending;
    el('#btn-analyze').disabled = pending === 0;
  }""",
    """  function refreshAnalyzeButton() {
    const pending = tierCounts().pending;
    const needs = Math.max(pending, window.__needsWork || 0);   // 含旧数据"缺感知哈希待补"
    el('#analyze-count').textContent = needs;
    el('#btn-analyze').disabled = needs === 0;
  }""",
    "分析按钮含缺phash待处理",
)

# O6b. 启动时从后端拉"待处理数"(含旧数据缺phash)存 __needsWork，供分析按钮判亮灯
once(
    """  async function initFromBackend() {
    try {
      const photos = await window.pywebview.api.list_photos();
      PHOTOS.length = 0;
      photos.forEach(p => PHOTOS.push(p));""",
    """  async function initFromBackend() {
    try {
      const photos = await window.pywebview.api.list_photos();
      PHOTOS.length = 0;
      photos.forEach(p => PHOTOS.push(p));
      try { const nc = await window.pywebview.api.needs_analysis_count(); window.__needsWork = (nc && nc.count) || 0; } catch (e) {}""",
    "启动拉待处理数",
)

# O7. 文件夹拖拽删除阈值 50% → 60%(用户改的)
once(
    "    const DELETE_THRESHOLD = 0.5; // matches the industry-standard",
    "    const DELETE_THRESHOLD = 0.6; // 用户定为拖过60%才删(原50%易误触)。matches the industry-standard",
    "拖拽删除阈值60%",
)

# ══════════ P. 堆叠视觉/动画修正（用户真机反馈：盖住左邻/卡顿/动画难看/撑高同行）══════════

# P1. 网格 align-items:start：展开条(带"收起"按钮)比普通卡高，默认 stretch 会把同一行其它
#     卡也拉到一样高(下框被拉长)。改 start 让每张卡保持自然高度、顶对齐，不被撑高。
#     另加展开条的轻量淡入(纯CSS,无reflow)取代原来卡顿的发牌动画。
once(
    """.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: var(--space-4);
}""",
    """.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: var(--space-4);
  align-items: start;   /* 展开条撑高不再连累同行其它卡(下框被拉长)——各卡保持自然高度顶对齐 */
}""",
    "网格顶对齐",
)

# P2. 层叠偏移收小：原来最多向左偏 -12~-20px，超过网格间距、盖住左邻照片。收到 ≤-6px
#     (落在 gap 内不碰邻居)，仍保留"一摞纸"的观感。
once(
    """.stack-layer[data-depth="1"] { z-index: 0;  transform: rotate(-2deg) translate(-3px, -2.5px); }
.stack-layer[data-depth="2"] { z-index: -1; transform: rotate(-4deg) translate(-6px, -5px); }
.stack-layer[data-depth="3"] { z-index: -2; transform: rotate(-6deg) translate(-9px, -7.5px); }
.stack-layer[data-depth="4"] { z-index: -3; transform: rotate(-8deg) translate(-12px, -10px); }
.stack-card:hover .stack-layer[data-depth="1"] { transform: rotate(-3deg) translate(-5px, -4px); }
.stack-card:hover .stack-layer[data-depth="2"] { transform: rotate(-6deg) translate(-10px, -8px); }
.stack-card:hover .stack-layer[data-depth="3"] { transform: rotate(-9deg) translate(-15px, -12px); }
.stack-card:hover .stack-layer[data-depth="4"] { transform: rotate(-12deg) translate(-20px, -16px); }""",
    """.stack-layer[data-depth="1"] { z-index: 0;  transform: rotate(-1.5deg) translate(-2px, -2px); }
.stack-layer[data-depth="2"] { z-index: -1; transform: rotate(-3deg) translate(-3px, -3.5px); }
.stack-layer[data-depth="3"] { z-index: -2; transform: rotate(-4deg) translate(-4px, -5px); }
.stack-layer[data-depth="4"] { z-index: -3; transform: rotate(-5deg) translate(-5px, -6.5px); }
.stack-card:hover .stack-layer[data-depth="1"] { transform: rotate(-2deg) translate(-3px, -3px); }
.stack-card:hover .stack-layer[data-depth="2"] { transform: rotate(-3.5deg) translate(-4px, -5px); }
.stack-card:hover .stack-layer[data-depth="3"] { transform: rotate(-5deg) translate(-5px, -7px); }
.stack-card:hover .stack-layer[data-depth="4"] { transform: rotate(-6deg) translate(-6px, -8px); }""",
    "层叠偏移收小防盖邻",
)

# P3. 左侧留白从 40px 收到 16px(偏移收小后不需要那么多"探头"空间)
once(
    ".content.stack-mode-on { padding-left: 40px; }",
    ".content.stack-mode-on { padding-left: 16px; }",
    "堆叠模式左留白收小",
)

# P4. 保留"发牌"动画但砍掉卡顿元凶：原来展开时除了发牌，还跑一个 playFlip(整屏 FLIP，
#     captureFlipRects 量了整屏所有卡的位置再逐张动画重排)——这才是"卡几秒 + 无规律堆叠"的
#     根源。现在：展开=只保留 dealStackMembersIn(一张张从那摞卡发到各自格子的扑克牌效果)，
#     不再跑 playFlip；收起=瞬间收(原来的克隆聚拢动画又乱又卡，去掉)。
once(
    """    const collapseBtn = e.target.closest('.stack-collapse');
    if (collapseBtn) { dealStackMembersOut(collapseBtn.dataset.stackId); return; }""",
    """    const collapseBtn = e.target.closest('.stack-collapse');
    if (collapseBtn) { expandedStacks.delete(collapseBtn.dataset.stackId); render(); return; }""",
    "收起瞬间收(去乱又卡的聚拢动画)",
)
once(
    """    const stackCard = e.target.closest('.stack-card');
    if (stackCard) {
      const id = stackCard.dataset.stackId;
      const fromRect = stackCard.getBoundingClientRect();
      const beforeFlipRects = captureFlipRects();
      expandedStacks.add(id);
      render();
      playFlip(beforeFlipRects, 'stack:' + id);
      dealStackMembersIn(document.querySelector(`.stack-expand[data-stack-id="${id}"]`), fromRect);
    }""",
    """    const stackCard = e.target.closest('.stack-card');
    if (stackCard) {
      const id = stackCard.dataset.stackId;
      const fromRect = stackCard.getBoundingClientRect();
      expandedStacks.add(id);
      render();
      // 只发牌，不跑整屏 FLIP(playFlip/captureFlipRects 是卡顿+乱堆的元凶)
      dealStackMembersIn(document.querySelector(`.stack-expand[data-stack-id="${id}"]`), fromRect);
    }""",
    "展开保留发牌去掉整屏FLIP",
)

# ══════════ Q. 展开后的堆叠成员可选中/可双击查看(接现有全屏+选中/对比)══════════

# Q1. 堆叠点击监听里加"成员"分支：单击成员=切换选中(供对比/批量)，双击交给下面的 dblclick。
#     放在 keep/delete 判断之后(点这两个按钮不会误触选中)、stack-card 之前。
once(
    """    const deleteBtn = e.target.closest('.stack-delete');
    if (deleteBtn) { deleteStackMember(deleteBtn.dataset.stackId, Number(deleteBtn.dataset.id)); return; }""",
    """    const deleteBtn = e.target.closest('.stack-delete');
    if (deleteBtn) { deleteStackMember(deleteBtn.dataset.stackId, Number(deleteBtn.dataset.id)); return; }
    const memberEl = e.target.closest('.stack-member');
    if (memberEl) {
      if (e.detail > 1) return;   // 双击交给 dblclick 打开全屏
      const mid = Number(memberEl.dataset.id);
      if (state.selected.has(mid)) { state.selected.delete(mid); memberEl.classList.remove('selected'); }
      else { state.selected.add(mid); memberEl.classList.add('selected'); }
      refreshToolbar();
      return;
    }""",
    "堆叠成员单击可选中",
)

# Q2. dblclick 加成员分支：双击展开里的成员=打开全屏查看/放大(和普通照片一致)。
once(
    """  contentEl.addEventListener('dblclick', (e) => {
    if (e.target.closest('.stack-card')) return;""",
    """  contentEl.addEventListener('dblclick', (e) => {
    const memberEl = e.target.closest('.stack-member');
    if (memberEl) { openFullscreenPreview(Number(memberEl.dataset.id)); return; }
    if (e.target.closest('.stack-card')) return;""",
    "堆叠成员双击查看",
)

# Q3. 成员选中的视觉(与推荐保留★的accent边框区分：用外描边)。
once(
    ".stack-member.is-keep { border-color: var(--accent); }",
    """.stack-member.is-keep { border-color: var(--accent); }
.stack-member.selected { outline: 2px solid var(--accent); outline-offset: 1px; }""",
    "堆叠成员选中描边",
)

# Q4. 重绘后保持成员的选中视觉(state.selected 里的成员渲染时带上 selected 类)。
once(
    '''            <div class="stack-member${p.id === keepId ? ' is-keep' : ''}" data-id="${p.id}" data-od-id="stack-member-${p.id}">''',
    '''            <div class="stack-member${p.id === keepId ? ' is-keep' : ''}${state.selected.has(p.id) ? ' selected' : ''}" data-id="${p.id}" data-od-id="stack-member-${p.id}">''',
    "堆叠成员重绘保留选中",
)

# ══════════ R. 展开重构：成员当普通网格卡"原地铺开"(修停顿/跳行/收回;发牌用逐卡动画)══════════

# R1. 新增 stackMemberCardHTML：一个成员=普通 .photo-card 网格卡(复用选中/双击/懒加载),
#     叠加连拍/相似角标、推荐保留★、首张的"收起"钮、每张的删除钮。放在 renderCardsHTML 前。
once(
    "  function renderCardsHTML(items, renderedStackIds) {",
    """  function stackMemberCardHTML(p, stack, isKeep, isFirst) {
    const sel = state.selected.has(p.id) ? ' selected' : '';
    const badges = `${stack.burst ? '<span class="stack-badge-burst" title="连拍">⚡</span>' : ''}${stack.similar ? '<span class="stack-badge-similar" title="相似">⧉</span>' : ''}`;
    // 最锐那张的★兼作"收起整组"按钮(用户建议:省一个钮、不与左下角档位标识打架)
    const star = isKeep ? `<button class="stack-keep-star" data-stack-id="${stack.id}" title="最锐 · 点此收起这组">★</button>` : '';
    return `
      <div class="photo-card stack-cell${isKeep ? ' is-keep' : ''}${sel} ${tierClass(p)}" data-id="${p.id}" data-stack-id="${stack.id}" data-od-id="stack-cell-${p.id}">
        <div class="photo-thumb" data-thumb="${p.thumbnail || ''}">
          <span class="photo-check" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path transform="translate(-1.3,0)" d="M4 12l6 6L20 6"/></svg></span>
          <div class="stack-badges">${badges}</div>
          ${star}
          <button class="stack-cell-del" data-stack-id="${stack.id}" data-del-member="${p.id}" title="删除这张" aria-label="删除这张">✕</button>
          <span class="tier-tag ${tierClass(p)}">${tierLabelOf(p)}</span>
        </div>
        <div class="photo-meta"><div class="fname">${p.name}</div><div class="ftime">${p.time}</div></div>
      </div>`;
  }

  function renderCardsHTML(items, renderedStackIds) {""",
    "新增成员网格卡模板",
)

# R2. renderCardsHTML 展开分支：不再输出跨列条，改成把成员当普通卡逐个铺开(自然换行、自适应)。
once(
    "      html += expandedStacks.has(stackId) ? stackExpandHTML(stack) : stackCardHTML(stack);",
    """      if (expandedStacks.has(stackId)) {
        const keepId = stackKeep.get(stack.id);
        stack.memberIds.forEach((mid, mi) => {
          const mp = PHOTOS.find(x => x.id === mid);
          if (mp) html += stackMemberCardHTML(mp, stack, mid === keepId, mi === 0);
        });
      } else {
        html += stackCardHTML(stack);
      }""",
    "展开改成员卡铺开",
)

# R3. 逐卡发牌/收回动画(只动这组成员卡，不跑整屏 FLIP、不建克隆——不卡)。stagger 总时长封顶,
#     大堆叠也不会拖很久。放在堆叠点击监听之前定义。
once(
    """  contentEl.addEventListener('click', (e) => {
    const collapseBtn = e.target.closest('.stack-collapse');""",
    """  function dealStackCellsIn(stackId, fromRect) {
    const cells = Array.from(document.querySelectorAll(`.stack-cell[data-stack-id="${stackId}"]`));
    const step = Math.min(45, 500 / Math.max(1, cells.length));
    cells.forEach((cell, i) => {
      const to = cell.getBoundingClientRect();
      if (!to.width || !to.height) return;
      const dx = fromRect.left + fromRect.width / 2 - (to.left + to.width / 2);
      const dy = fromRect.top + fromRect.height / 2 - (to.top + to.height / 2);
      const scale = Math.max(0.3, Math.min(fromRect.width / to.width, fromRect.height / to.height));
      cell.animate([
        { transform: `translate(${dx}px, ${dy}px) scale(${scale})`, opacity: 0.4 },
        { transform: 'none', opacity: 1 },
      ], { duration: 320, delay: i * step, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'both' });
    });
  }
  function collapseStackAnimated(stackId) {
    const cells = Array.from(document.querySelectorAll(`.stack-cell[data-stack-id="${stackId}"]`));
    if (!cells.length) { expandedStacks.delete(stackId); render(); return; }
    const toRect = cells[0].getBoundingClientRect();   // 收拢到首张(收起后那摞卡的位置)
    const step = Math.min(35, 400 / cells.length);
    let remaining = cells.length;
    const done = () => { if (--remaining > 0) return; expandedStacks.delete(stackId); render(); };
    cells.forEach((cell, i) => {
      const r = cell.getBoundingClientRect();
      const a = cell.animate([
        { transform: 'none', opacity: 1 },
        { transform: `translate(${toRect.left - r.left}px, ${toRect.top - r.top}px)`, opacity: 0.1 },
      ], { duration: 240, delay: (cells.length - 1 - i) * step, easing: 'cubic-bezier(0.4, 0, 1, 1)', fill: 'forwards' });
      a.onfinish = done; a.oncancel = done;
    });
  }
  contentEl.addEventListener('click', (e) => {
    const starBtn = e.target.closest('.stack-keep-star');
    if (starBtn) { collapseStackAnimated(starBtn.dataset.stackId); return; }
    const delMem = e.target.closest('.stack-cell-del');
    if (delMem) { deleteStackMember(delMem.dataset.stackId, Number(delMem.dataset.delMember)); return; }
    const collapseBtn = e.target.closest('.stack-collapse');""",
    "逐卡发牌收回+收起删除",
)

# R4. 展开点击：发牌改用 dealStackCellsIn(动新铺开的成员卡)，不再找已废弃的 .stack-expand 条。
once(
    """    const stackCard = e.target.closest('.stack-card');
    if (stackCard) {
      const id = stackCard.dataset.stackId;
      const fromRect = stackCard.getBoundingClientRect();
      expandedStacks.add(id);
      render();
      // 只发牌，不跑整屏 FLIP(playFlip/captureFlipRects 是卡顿+乱堆的元凶)
      dealStackMembersIn(document.querySelector(`.stack-expand[data-stack-id="${id}"]`), fromRect);
    }""",
    """    const stackCard = e.target.closest('.stack-card');
    if (stackCard) {
      const id = stackCard.dataset.stackId;
      const fromRect = stackCard.getBoundingClientRect();
      expandedStacks.add(id);
      render();
      dealStackCellsIn(id, fromRect);   // 成员卡从那摞卡位置逐张发出(扑克牌效果)
      return;
    }""",
    "展开发牌改动成员卡",
)

# R5. 成员卡是 .photo-card，会被下面的单击/双击监听正常处理(选中/全屏)——但点"收起/删除"钮
#     不能连带触发选中或全屏，加守卫忽略这两个钮。
once(
    """  contentEl.addEventListener('click', (e) => {
    if (e.target.closest('.stack-card')) return; // handled by the stack click listener below
    const card = e.target.closest('.photo-card');""",
    """  contentEl.addEventListener('click', (e) => {
    if (e.target.closest('.stack-card')) return; // handled by the stack click listener below
    if (e.target.closest('.stack-keep-star, .stack-cell-del')) return; // 组内按钮不当选中
    const card = e.target.closest('.photo-card');""",
    "单击守卫组内按钮",
)
once(
    """  contentEl.addEventListener('dblclick', (e) => {
    const memberEl = e.target.closest('.stack-member');
    if (memberEl) { openFullscreenPreview(Number(memberEl.dataset.id)); return; }
    if (e.target.closest('.stack-card')) return;""",
    """  contentEl.addEventListener('dblclick', (e) => {
    if (e.target.closest('.stack-keep-star, .stack-cell-del')) return; // 组内按钮不当双击查看
    if (e.target.closest('.stack-card')) return;""",
    "双击守卫组内按钮",
)

# R6. 成员卡叠加元素的样式(角标/★/收起钮/删除钮/推荐高亮)。
once(
    ".stack-count-badge {",
    """.stack-cell .photo-thumb { box-shadow: inset 0 0 0 2px color-mix(in oklab, var(--accent), transparent 80%); }
.stack-cell.is-keep .photo-thumb { box-shadow: inset 0 0 0 2px var(--accent); }
.stack-cell .stack-badges { position: absolute; top: 8px; right: 8px; z-index: 2; }
.stack-cell .stack-keep-star { position: absolute; top: 6px; left: 50%; transform: translateX(-50%); z-index: 3; color: #ffd54a; font-size: 12px; line-height: 1; background: rgba(0,0,0,.6); padding: 3px 8px; border-radius: var(--radius-pill); border: none; cursor: pointer; }
.stack-cell .stack-keep-star:hover { background: rgba(0,0,0,.8); color: #ffe082; }
.stack-cell-del { position: absolute; bottom: 8px; right: 8px; z-index: 3; width: 24px; height: 24px; border-radius: 50%; background: rgba(0,0,0,.5); color: #fff; border: none; cursor: pointer; display: grid; place-items: center; font-size: 12px; opacity: 0; transition: opacity .12s; }
.stack-cell:hover .stack-cell-del { opacity: 1; }
.stack-cell-del:hover { background: var(--danger); }
.stack-count-badge {""",
    "成员卡叠加样式",
)

# ══════════ S. 全屏左右切换按网格实际顺序(修:展开组成员被跳过)══════════
# 原 currentVisibleIds 用"全部照片时间序"填,但相似组成员拍摄时间分散→在时间序里被别的照片
# 隔开→全屏左右按时间走会跳过同组成员。改成按**网格渲染顺序**填(展开组成员连续、折叠组只入封面)
# ——正是 render() 注释本来声明的意图。

# S1. renderCardsHTML 边渲染边把 id 按网格顺序推进 visibleIds。
once(
    """  function renderCardsHTML(items, renderedStackIds) {
    let html = '';
    items.forEach(p => {
      const stackId = state.stackMode ? photoIdToStack.get(p.id) : undefined;
      if (!stackId) { html += cardHTML(p); return; }
      if (renderedStackIds.has(stackId)) return;
      renderedStackIds.add(stackId);
      const stack = STACKS.find(s => s.id === stackId);
      if (expandedStacks.has(stackId)) {
        const keepId = stackKeep.get(stack.id);
        stack.memberIds.forEach((mid, mi) => {
          const mp = PHOTOS.find(x => x.id === mid);
          if (mp) html += stackMemberCardHTML(mp, stack, mid === keepId, mi === 0);
        });
      } else {
        html += stackCardHTML(stack);
      }
    });
    return html;
  }""",
    """  function renderCardsHTML(items, renderedStackIds, visibleIds) {
    let html = '';
    items.forEach(p => {
      const stackId = state.stackMode ? photoIdToStack.get(p.id) : undefined;
      if (!stackId) { html += cardHTML(p); if (visibleIds) visibleIds.push(p.id); return; }
      if (renderedStackIds.has(stackId)) return;
      renderedStackIds.add(stackId);
      const stack = STACKS.find(s => s.id === stackId);
      // 只算"还在库里"的成员——任何删除途径(✕/选中删/全屏删)后都对齐。其它重复删光只剩≤1张
      // 的堆自动解散，成员回落普通照片卡(脱掉相似/★标识)。非破坏性(不改STACKS，撤销恢复后回组)。
      const liveIds = stack ? stack.memberIds.filter(mid => PHOTOS.some(x => x.id === mid)) : [];
      if (liveIds.length < 2) {
        liveIds.forEach(mid => {
          const mp = PHOTOS.find(x => x.id === mid);
          if (mp) { html += cardHTML(mp); if (visibleIds) visibleIds.push(mp.id); }
        });
        return;
      }
      const cover = liveIds.includes(stack.cover) ? stack.cover : liveIds[0];
      const liveStack = { id: stack.id, memberIds: liveIds, cover: cover, burst: stack.burst, similar: stack.similar };
      if (expandedStacks.has(stackId)) {
        const rawKeep = stackKeep.get(stack.id);
        const keepId = liveIds.includes(rawKeep) ? rawKeep : cover;
        liveIds.forEach((mid, mi) => {
          const mp = PHOTOS.find(x => x.id === mid);
          if (mp) { html += stackMemberCardHTML(mp, liveStack, mid === keepId, mi === 0); if (visibleIds) visibleIds.push(mp.id); }
        });
      } else {
        html += stackCardHTML(liveStack);
        // 折叠态只显封面、成员不在网格里→不进导航序列(全屏左右不会跳进看不见的折叠成员)
      }
    });
    return html;
  }""",
    "导航序列按网格顺序+存活成员对齐",
)

# S2. 时间视图：去掉"按时间序全推"，改由 renderCardsHTML 按网格顺序推。
once(
    """        const items = list.filter(p => p.day === d);
        visibleIds.push(...items.map(p => p.id));
        html += `<div class="group-header"><h3>${d}</h3><span class="group-count">${items.length} 张</span></div>
                 <div class="grid">${renderCardsHTML(items, renderedStackIds)}</div>`;""",
    """        const items = list.filter(p => p.day === d);
        html += `<div class="group-header"><h3>${d}</h3><span class="group-count">${items.length} 张</span></div>
                 <div class="grid">${renderCardsHTML(items, renderedStackIds, visibleIds)}</div>`;""",
    "时间视图导航序列",
)

# S3. 档位视图：同上。
once(
    """        if (!items.length) return;
        visibleIds.push(...items.map(p => p.id));
        html += `<div class="group-header"><span class="group-dot" style="background:var(--${g.dotVar})"></span><h3>${g.label}</h3><span class="group-count">${items.length} 张</span></div>
                 <div class="grid">${renderCardsHTML(items, renderedStackIds)}</div>`;""",
    """        if (!items.length) return;
        html += `<div class="group-header"><span class="group-dot" style="background:var(--${g.dotVar})"></span><h3>${g.label}</h3><span class="group-count">${items.length} 张</span></div>
                 <div class="grid">${renderCardsHTML(items, renderedStackIds, visibleIds)}</div>`;""",
    "档位视图导航序列",
)

# ══════════ T. 删到只剩1张自动脱堆叠 + 折叠按钮凹/浮触感 ══════════

# T2. 折叠按钮启用判据：按"还在库里的成员"算，≥2张才是真堆叠(删到剩1张的不点亮)。
once(
    "const hasStacks = STACKS.some(s => s.memberIds.length > 0);",
    "const hasStacks = STACKS.some(s => s.memberIds.filter(mid => PHOTOS.some(x => x.id === mid)).length > 1);",
    "折叠按钮需真堆叠才亮",
)

# T3. 折叠按钮凹/浮触感(参考深浅切换 .theme-dip)：默认(折叠开=active)看起来往下凹，
#     点一下关掉折叠(非active)就浮起来。
once(
    "#toolbar-stack-toggle.active { background: color-mix(in oklab, var(--accent), transparent 88%); border-color: var(--accent); color: var(--accent-active); }",
    """#toolbar-stack-toggle { box-shadow: inset 0 2px 5px rgba(0,0,0,0.28), inset 0 0 0 1px var(--border); transform: translateY(1px); transition: box-shadow 420ms var(--ease-emphasized), transform 420ms var(--ease-emphasized); }
#toolbar-stack-toggle.active:not(:disabled) { box-shadow: var(--elev-raised), var(--elev-ring); transform: translateY(0); background: color-mix(in oklab, var(--accent), transparent 88%); border-color: var(--accent); color: var(--accent-active); }""",
    "折叠按钮凹浮触感",
)

# ══════════ U. 修:档位筛选/分类视图下堆叠跨档残留 + 分类视图点待分析空白 ══════════

# U1. 堆叠只在"全部筛选 + 时间视图"启用。按档位筛选(废/可修/精选/待分析)或分类视图分组时
#     不堆叠——否则一个命中档位的照片会把它整组(含别的档位成员)都拽出来显示(用户反馈的残留)。
once(
    "      const stackId = state.stackMode ? photoIdToStack.get(p.id) : undefined;",
    """      // 堆叠只在"全部+时间视图"有意义(浏览时折叠重复);按档位筛选/分类分组时不堆叠,
      // 免把整组跨档位成员拽出来。
      const useStacks = state.stackMode && state.filter === 'all' && state.view === 'time';
      const stackId = useStacks ? photoIdToStack.get(p.id) : undefined;""",
    "堆叠仅全部+时间视图",
)

# U2. 分类视图"还没分析"空提示的判据错了：用了筛选后的 list,导致点"待分析"(list全是未分析的)
#     被误判成"整库没分析"而整屏空白。改成:用**全库**判有没有分析过,且只在"全部筛选"下才显示
#     空提示;其余情况正常按档位分组(空组自动跳过),这样点"待分析"能看到待分析照片。
once(
    """      const analyzedCount = list.filter(p => p.tier !== null).length;
      if (analyzedCount === 0) {
        html = '<p style="color:var(--muted); padding:48px; text-align:center; line-height:1.7;">这些照片还没有分析。<br>点击左侧「开始分析」，软件会把它们分成 废片 / 可修 / 精选 后在这里按类查看。</p>';
      }
      const groups = analyzedCount === 0 ? [] : [""",
    """      const analyzedCount = PHOTOS.filter(p => p.tier !== null).length;   // 全库判,不受当前筛选影响
      if (analyzedCount === 0 && state.filter === 'all') {
        html = '<p style="color:var(--muted); padding:48px; text-align:center; line-height:1.7;">这些照片还没有分析。<br>点击左侧「开始分析」，软件会把它们分成 废片 / 可修 / 精选 后在这里按类查看。</p>';
      }
      const groups = (analyzedCount === 0 && state.filter === 'all') ? [] : [""",
    "分类视图待分析不再空白",
)

# ══════════ V. 本地文件夹在侧边栏也显示，用笔记本图标区分(不进SD卡记忆,只是显示)══════════
# 后端 list_folders 现在也返回本地文件夹(kind=local)。侧边栏对 local 用笔记本电脑图标、
# card 用文件夹图标区分——满足"本地也得显示、但一眼看出不是SD卡"。
once(
    "          ${folderIcon}<span class=\"folder-row-label\">${(window.__folderNames && window.__folderNames[f]) || f}</span><span class=\"count\">${count}</span>",
    "          ${(window.__folderKinds && window.__folderKinds[f] === 'local') ? laptopIcon : folderIcon}<span class=\"folder-row-label\">${(window.__folderNames && window.__folderNames[f]) || f}</span><span class=\"count\">${count}</span>",
    "本地文件夹用笔记本图标",
)
once(
    "    const folderIcon = '<svg class=\"folder-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\"><path d=\"M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z\"/></svg>';",
    "    const folderIcon = '<svg class=\"folder-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\"><path d=\"M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z\"/></svg>';\n    const laptopIcon = '<svg class=\"folder-icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\"><rect x=\"3\" y=\"4\" width=\"18\" height=\"12\" rx=\"1.5\"/><path d=\"M2 20h20\"/></svg>';   // 本地文件夹标识",
    "笔记本图标定义",
)

# ══════════ W. 点文件夹时清掉残留的档位筛选(修:已分析的SD卡文件夹在"待分析"筛选下点进去空)══════════
# 文件夹筛选 与 档位筛选(全部/待分析/废/可修/精选)是 AND 叠加的。用户点过"待分析"后 filter
# 粘在 pending,再点一个"照片全已分析"的SD卡文件夹→folder∩pending=空→"该分类下无照片",而
# 侧边栏那个数量不看档位筛选仍显示→"有数量却点进去空"的困惑。点文件夹=看该文件夹全部,重置
# filter=all 并把档位高亮切回"全部照片"。
once(
    """    state.folder = btn.dataset.folder;
    isCombinedView = false; // navigating directly always leaves combine mode
    render();""",
    """    state.folder = btn.dataset.folder;
    // 点文件夹=看这个文件夹的全部照片：清掉可能残留的档位筛选(如"待分析")，否则 文件夹∩档位
    // 叠加会让"已全部分析的SD卡文件夹"在"待分析"下显示为空(用户困惑的根源)。
    state.filter = 'all';
    document.querySelectorAll('#tier-nav .side-item').forEach(b => b.classList.toggle('active', b.dataset.filter === 'all'));
    isCombinedView = false; // navigating directly always leaves combine mode
    render();""",
    "点文件夹重置档位筛选",
)

# ══════════ X. 退出前flush "5秒撤销倒计时"里未提交的延迟删除（修复:关软件删除复活）══════════
# 三处独立的"乐观删除+5秒后才真提交"逻辑(单张/批量删除照片、堆叠内删除、文件夹拖拽删除)
# 都用JS的 setTimeout 做延迟提交。问题：如果用户在5秒内直接关软件，JS连同计时器一起被
# 销毁，那个"真正调后端删除"的回调永远不会执行——数据库里其实从没删，下次打开又"复活"。
# 修法：所有延迟提交都注册进一个共享清单 window.__pendingDeletes；退出前(do_quit)让Python
# 调 window.flushPendingDeletes()，把清单里还没提交的立刻执行完，再真正销毁窗口。

# X1. commitDeleteAfterUndoWindow(单张/批量删除照片)：注册进清单 + 定义 flushPendingDeletes
once(
    """  // 统一删除逻辑：先前端乐观移除（立刻消失），弹5秒可撤销toast，撤销则恢复、
  // 后端从未被调用；超时才真正调后端把文件送进回收站+删库记录。
  function commitDeleteAfterUndoWindow(ids, label) {
    if (!ids.length) return;
    const idSet = new Set(ids);
    const removed = PHOTOS.filter(p => idSet.has(p.id));
    PHOTOS = PHOTOS.filter(p => !idSet.has(p.id));
    ids.forEach(id => { state.selected.delete(id); zoomMap.delete(id); panMap.delete(id); });
    compareIds = compareIds.filter(x => !idSet.has(x));
    render();
    renderFolderNav();
    if (compareOverlay.classList.contains('open')) {
      if (compareIds.length === 0) compareOverlay.classList.remove('open');
      else renderCompare();
    }
    let committed = false;
    const timer = setTimeout(async () => {
      committed = true;
      try {
        const res = await window.pywebview.api.delete_photos(ids);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    }, 5000);
    showToast(label, {
      undo: () => {
        if (committed) return;
        clearTimeout(timer);
        PHOTOS = PHOTOS.concat(removed).sort((a, b) => b.id - a.id);
        render();
        renderFolderNav();
      },
    });
  }""",
    """  // 待提交的延迟删除清单：关软件前必须把这里还没提交的立刻执行完，否则计时器随
  // 页面一起销毁、数据库里从未真删，下次打开又"复活"(见 do_quit 里的flush调用)。
  window.__pendingDeletes = [];
  window.flushPendingDeletes = async function () {
    const pending = window.__pendingDeletes.filter(e => !e.committed);
    window.__pendingDeletes = [];
    pending.forEach(e => clearTimeout(e.timer));
    await Promise.all(pending.map(e => e.commit()));
  };

  // 统一删除逻辑：先前端乐观移除（立刻消失），弹5秒可撤销toast，撤销则恢复、
  // 后端从未被调用；超时(或退出前被flush)才真正调后端把文件送进回收站+删库记录。
  function commitDeleteAfterUndoWindow(ids, label) {
    if (!ids.length) return;
    const idSet = new Set(ids);
    const removed = PHOTOS.filter(p => idSet.has(p.id));
    PHOTOS = PHOTOS.filter(p => !idSet.has(p.id));
    ids.forEach(id => { state.selected.delete(id); zoomMap.delete(id); panMap.delete(id); });
    compareIds = compareIds.filter(x => !idSet.has(x));
    render();
    renderFolderNav();
    if (compareOverlay.classList.contains('open')) {
      if (compareIds.length === 0) compareOverlay.classList.remove('open');
      else renderCompare();
    }
    const entry = { committed: false };
    entry.commit = async () => {
      if (entry.committed) return;
      entry.committed = true;
      try {
        const res = await window.pywebview.api.delete_photos(ids);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    };
    entry.timer = setTimeout(entry.commit, 5000);
    window.__pendingDeletes.push(entry);
    showToast(label, {
      undo: () => {
        if (entry.committed) return;
        entry.committed = true;   // 撤销：标记已处理，防止之后被flush或超时再误删
        clearTimeout(entry.timer);
        PHOTOS = PHOTOS.concat(removed).sort((a, b) => b.id - a.id);
        render();
        renderFolderNav();
      },
    });
  }""",
    "退出前flush-统一删除注册清单",
)

# X2. 堆叠内删除同样注册进清单
once(
    """    render();
    // 乐观删除已更新UI；5秒后真正调后端把这张送回收站+删库记录，撤销则取消、后端从未被调。
    let committed = false;
    const timer = setTimeout(async () => {
      committed = true;
      try {
        const res = await window.pywebview.api.delete_photos([photoId]);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    }, 5000);
    showToast(`已删除 ${removedPhoto ? removedPhoto.name : '该照片'}`, {
      undo: () => {
        if (committed) return;
        clearTimeout(timer);
        stack.memberIds.splice(memberIdx, 0, photoId);""",
    """    render();
    // 乐观删除已更新UI；5秒后真正调后端把这张送回收站+删库记录，撤销则取消、后端从未被调；
    // 退出软件前会被 flushPendingDeletes 强制提前执行，不会因为关软件而"从未真删"。
    const stackEntry = { committed: false };
    stackEntry.commit = async () => {
      if (stackEntry.committed) return;
      stackEntry.committed = true;
      try {
        const res = await window.pywebview.api.delete_photos([photoId]);
        if (res && res.error) showToast('删除失败：' + res.error);
        else { await refreshFolders(); renderFolderNav(); }
      } catch (e) { showToast('删除失败：' + e); }
    };
    stackEntry.timer = setTimeout(stackEntry.commit, 5000);
    window.__pendingDeletes.push(stackEntry);
    showToast(`已删除 ${removedPhoto ? removedPhoto.name : '该照片'}`, {
      undo: () => {
        if (stackEntry.committed) return;
        stackEntry.committed = true;
        clearTimeout(stackEntry.timer);
        stack.memberIds.splice(memberIdx, 0, photoId);""",
    "退出前flush-堆叠删除注册清单",
)

# X3. 文件夹拖拽删除(forget_photos)同样注册进清单
once(
    """    render();
    renderFolderNav();
    // 延迟真删库：5秒 undo 窗口内不撤销，才真的从数据库移除该文件夹的照片记录+清缓存
    // (不删原始照片文件，见后端 forget_folder 说明)。撤销则清掉这个定时器。
    const forgetIds = [...removedIds];   // 锁定当时这批id，避免延迟提交误删期间新导入的同名文件夹照片
    const forgetTimer = setTimeout(() => {
      window.pywebview.api.forget_photos(forgetIds).then(() => refreshFolders());
    }, 5000);
    showToast(`已从相册移除文件夹「${f}」及其 ${removedPhotos.length} 张照片`, {
      undo: () => {
        clearTimeout(forgetTimer);
        importedFolders.splice(folderIdx, 0, f);
        PHOTOS.push(...removedPhotos);
        prevState.selected.forEach(id => state.selected.add(id));
        if (prevState.wasStagedForCombine) selectedFolderSet.add(f);
        state.folder = prevState.folder;
        isCombinedView = prevState.isCombinedView;
        previousFolderView = prevState.previousFolderView;
        render();
        renderFolderNav();
      },
    });""",
    """    render();
    renderFolderNav();
    // 延迟真删库：5秒 undo 窗口内不撤销，才真的从数据库移除该文件夹的照片记录+清缓存
    // (不删原始照片文件，见后端 forget_folder 说明)。撤销则清掉这个定时器；退出软件前会被
    // flushPendingDeletes 强制提前执行，不会因为关软件而"从未真删"。
    const forgetIds = [...removedIds];   // 锁定当时这批id，避免延迟提交误删期间新导入的同名文件夹照片
    const forgetEntry = { committed: false };
    forgetEntry.commit = () => {
      if (forgetEntry.committed) return;
      forgetEntry.committed = true;
      return window.pywebview.api.forget_photos(forgetIds).then(() => refreshFolders());
    };
    forgetEntry.timer = setTimeout(forgetEntry.commit, 5000);
    window.__pendingDeletes.push(forgetEntry);
    showToast(`已从相册移除文件夹「${f}」及其 ${removedPhotos.length} 张照片`, {
      undo: () => {
        if (forgetEntry.committed) return;
        forgetEntry.committed = true;
        clearTimeout(forgetEntry.timer);
        importedFolders.splice(folderIdx, 0, f);
        PHOTOS.push(...removedPhotos);
        prevState.selected.forEach(id => state.selected.add(id));
        if (prevState.wasStagedForCombine) selectedFolderSet.add(f);
        state.folder = prevState.folder;
        isCombinedView = prevState.isCombinedView;
        previousFolderView = prevState.previousFolderView;
        render();
        renderFolderNav();
      },
    });""",
    "退出前flush-文件夹删除注册清单",
)

# ══════════ Y. 2026-10 体验大修（用户授权：审美与优化全权交给我；参考苹果相册的交互与动效）══════════
# 真机反馈的问题与对应改法：
#  · 展开/收起堆叠整屏闪白、页面被推着往下滑 → 展开/收起只改这一堆自己的 DOM；关掉滚动锚定；
#    被挤开的卡片用弹簧平滑让位(FLIP，只动视口附近的)；发牌/飞回动画改成弹簧物理。
#  · 快速滑动大片空白 → 缩略图加载引擎(已加载的重绘直接贴、离视口近的优先、最多6并发、
#    划走的作废) + 后端后台预生成(warm_thumbnails)。
#  · 堆叠只在"全部"里能用 → 任何视图都按"本组里可见的成员"成堆。
#  · 日期组头加勾选圈(整组/这段时间全选)；分类视图里每个档位再按天分组。
#  · 工具栏太挤 → 删除/对比/取消选择挪进底部浮动选择栏(新增批量标档)；机型筛选改下拉菜单。
#  · 全屏：从缩略图飞出/飞回、滚轮按光标位置缩放、双击放大、翻页滑入、删除后直接看下一张。
# 大段新代码在 scripts/wiring/*.css|js，这里只负责按锚点拼接。

# Y0. 偏好设置持久化：pywebview 默认每次启动都是全新无痕浏览器配置，localStorage 关掉就丢
#     (深色模式、网格密度、"记住我的选择"、一键全选档位每次重开都被忘)。改走 sgPrefs：值存后端
#     prefs.json，启动时 app.py 写出 prefs.js 供 <head> 同步加载。要在 Y2 注入 sgPrefs 之前替换，
#     免得把 sgPrefs 自己内部对 localStorage 的兜底调用也换掉。
once("<title>拾光 ShiGuang · RAW 照片质量筛选</title>",
     "<title>拾光 ShiGuang · RAW 照片质量筛选</title>\n<script src=\"prefs.js\"></script>",
     "Y0a 启动同步加载偏好")
times("localStorage.getItem(", "sgPrefs.getItem(", 4, "Y0b 偏好读取走 sgPrefs")
times("localStorage.setItem(", "sgPrefs.setItem(", 4, "Y0c 偏好写入走 sgPrefs")

# Y1. 样式：追加到样式表末尾(同名规则后写者胜，覆盖工作台原样式)
once("</style>\n</head>", wiring("ux_style.css") + wiring("ux_scrub.css") + "</style>\n</head>", "Y1 体验大修样式")

# Y2. 基础设施(弹簧动画/缩略图加载引擎/FLIP)：紧跟 contentEl 定义之后
once(
    "  const contentEl = el('#content');\n",
    "  const contentEl = el('#content');\n" + wiring("ux_core.js"),
    "Y2 动效与加载基础设施",
)

# Y3. 选择：旧 refreshToolbar(只刷工具栏计数) → 选中状态/组头/选择栏统一刷新
block("  function refreshToolbar() {", "  function renderFolderNav() {", wiring("ux_selection.js"), "Y3 选择状态与选择栏")

# Y4. 网格渲染：cardHTML…applyStackExpandSpans 整段换成新渲染(按天分组+组头勾选+任意视图堆叠)
block("  function cardHTML(p) {", "  // disabled + explains why when there's nothing left to fold",
      wiring("ux_render.js"), "Y4 网格渲染重写")

# Y5. 网格交互：旧的堆叠增删/整屏FLIP/发牌收回/单击双击 整段换成新交互(只改这一堆的 DOM)
block("  // expand/collapse a stack, reassign which member is \"keep\", or delete",
      "  el('#tier-nav').addEventListener('click', (e) => {", wiring("ux_interact.js"), "Y5 网格交互重写")

# Y6. 视图切换类操作：内容区淡入+回到顶部(而不是硬切、停在随机位置)
once(
    """  el('#toolbar-stack-toggle').addEventListener('click', () => {
    state.stackMode = !state.stackMode;
    render();
  });""",
    """  el('#toolbar-stack-toggle').addEventListener('click', () => {
    state.stackMode = !state.stackMode;
    renderWithFade();
  });""",
    "Y6a 折叠开关淡入",
)
once("    state.filter = btn.dataset.filter;\n    render();\n  });",
     "    state.filter = btn.dataset.filter;\n    renderWithFade({ toTop: true });\n  });", "Y6b 档位切换淡入")
once("    isCombinedView = false; // navigating directly always leaves combine mode\n    render();\n  });",
     "    isCombinedView = false; // navigating directly always leaves combine mode\n    renderWithFade({ toTop: true });\n  });",
     "Y6c 文件夹切换淡入")
once("      render();\n      return;\n    }\n    if (e.target.closest('[data-multi-folder]')) return;",
     "      renderWithFade({ toTop: true });\n      return;\n    }\n    if (e.target.closest('[data-multi-folder]')) return;",
     "Y6d 合并显示淡入")
# Y6e. (第二轮)"分类视图"去掉：左侧 废片/可修/精选 本身就是按档位看，分类视图与之重复(用户反馈)
once("  const viewSeg = initSlidingSegmented(el('#view-toggle'), (item) => {\n    state.view = item.dataset.view;\n    render();\n  });\n",
     "", "Y6e 去掉时间/分类视图切换")

# Y7. 一键全选：只选"当前范围"(文件夹/搜索/机型)里的该档——以前会把别的文件夹里看不见的也选上
once(
    """    PHOTOS.filter(p => p.tier === state.selectAllTier).forEach(p => state.selected.add(p.id));
    render();
    showToast(`已选中全部「${TIER_LABEL[state.selectAllTier]}」照片`);""",
    """    const ids = scopeList().filter(p => p.tier === state.selectAllTier).map(p => p.id);
    ids.forEach(id => state.selected.add(id));
    refreshSelectionUI();
    showToast(ids.length ? `已选中当前范围内的「${TIER_LABEL[state.selectAllTier]}」${ids.length} 张`
                         : `当前范围内没有「${TIER_LABEL[state.selectAllTier]}」照片`);""",
    "Y7 一键全选限当前范围",
)

# Y8. 工具栏瘦身：取消选择/对比/删除 挪进底部选择栏；机型筛选显示为下拉
block('        <button class="btn btn-sm" id="btn-clear-sel"', '        <button class="theme-dip" id="btn-theme"', "",
      "Y8a 工具栏移除选择类按钮")
block("  el('#btn-delete').addEventListener('click', () => {", "  // ── import modal ─", "",
      "Y8b 移除旧删除/取消选择监听")
once("  el('#btn-compare').addEventListener('click', openCompare);",
     "  el('#sel-compare').addEventListener('click', openCompare);", "Y8c 对比改由选择栏触发")
once(
    '      <div class="content" id="content" data-od-id="gallery-grid"></div>',
    '''      <div class="content" id="content" data-od-id="gallery-grid"></div>
      <div class="sel-bar" id="sel-bar" role="toolbar" aria-label="已选照片操作" aria-hidden="true">
        <button class="sel-bar-btn sel-bar-close" id="sel-clear" title="取消选择 (Esc)" aria-label="取消选择">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
        <span class="sel-bar-count">已选 <b id="sel-num">0</b> 张</span>
        <span class="sel-bar-sep"></span>
        <span class="sel-bar-label">标为</span>
        <button class="sel-bar-btn" data-set-tier="bad" title="标为废片 (1)"><i class="dot bad"></i>废片</button>
        <button class="sel-bar-btn" data-set-tier="fix" title="标为可修 (2)"><i class="dot fix"></i>可修</button>
        <button class="sel-bar-btn" data-set-tier="good" title="标为精选 (3)"><i class="dot good"></i>精选</button>
        <span class="sel-bar-sep"></span>
        <button class="sel-bar-btn" id="sel-compare" title="同屏对比所选照片">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="7" height="14" rx="1"/><rect x="14" y="5" width="7" height="14" rx="1"/></svg>对比
        </button>
        <button class="sel-bar-btn sel-danger" id="sel-delete" title="删除所选 (Delete)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0 1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/></svg>删除
        </button>
      </div>''',
    "Y8d 底部浮动选择栏",
)
once(
    '<span id="filter-label">筛选 · 全部机型</span>\n',
    '<span id="filter-label">全部机型</span>\n          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:11px;height:11px;margin-left:-2px;"><path d="M6 9l6 6 6-6"/></svg>\n',
    "Y8e 机型按钮显示为下拉",
)
block(
    "  // 按机型筛选：点击循环切换 全部机型→各机型→全部",
    "  document.querySelectorAll('#density-toggle .seg-item')",
    """  // 按机型筛选：下拉菜单列出图库里出现过的机型(带张数)，选中即筛选(以前要一下下循环点)
  (function () {
    const bf = document.getElementById('btn-filter');
    if (!bf) return;
    const menu = document.createElement('div');
    menu.className = 'sg-menu';
    menu.id = 'camera-menu';
    document.body.appendChild(menu);
    const close = () => menu.classList.remove('open');
    function open() {
      const counts = new Map();
      PHOTOS.forEach(p => { if (p.cam) counts.set(p.cam, (counts.get(p.cam) || 0) + 1); });
      const rows = [['all', '全部机型', PHOTOS.length]].concat(
        [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => [c, c, n]));
      menu.innerHTML = rows.map(([v, label, n]) =>
        `<button class="sg-menu-item${state.camera === v ? ' selected' : ''}" data-cam="${sgEsc(v)}">${sgEsc(label)}<span class="n">${n}</span></button>`).join('');
      const r = bf.getBoundingClientRect();
      menu.style.left = r.left + 'px';
      menu.style.top = (r.bottom + 6) + 'px';
      menu.classList.add('open');
    }
    bf.addEventListener('click', (e) => { e.stopPropagation(); menu.classList.contains('open') ? close() : open(); });
    menu.addEventListener('click', (e) => {
      e.stopPropagation();
      const it = e.target.closest('[data-cam]');
      if (!it) return;
      state.camera = it.dataset.cam;
      const label = document.getElementById('filter-label');
      if (label) label.textContent = state.camera === 'all' ? '全部机型' : state.camera;
      close();
      renderWithFade({ toTop: true });
    });
    document.addEventListener('click', close);
    window.addEventListener('resize', close);
  })();
""",
    "Y8f 机型筛选下拉菜单",
)

# Y9. 删除/撤销：消失的照片原地缩小淡出、其余平滑补位；撤销后按拍摄时间放回原位(以前按导入顺序乱插)
once("    compareIds = compareIds.filter(x => !idSet.has(x));\n    render();\n    renderFolderNav();",
     "    compareIds = compareIds.filter(x => !idSet.has(x));\n    animateLayoutChange(render);", "Y9a 删除带离场动画")
once("        PHOTOS = PHOTOS.concat(removed).sort((a, b) => b.id - a.id);\n        render();\n        renderFolderNav();",
     "        PHOTOS = PHOTOS.concat(removed);\n        sortPhotos();\n        animateLayoutChange(render);",
     "Y9b 撤销删除按时间放回")
once("        PHOTOS.push(...removedPhotos);\n", "        PHOTOS.push(...removedPhotos);\n        sortPhotos();\n",
     "Y9c 撤销移除文件夹按时间放回")
# Y9d. 删除提交时有文件删不掉(写保护卡/被占用)：后端会保留这些记录并在 failed 里返回——前端
#      提示原因并重新拉照片，让没删掉的照片回到界面上(而不是看着像删了，下次插卡又冒出来)
once(
    "        const res = await window.pywebview.api.delete_photos(ids);\n"
    "        if (res && res.error) showToast('删除失败：' + res.error);",
    "        const res = await window.pywebview.api.delete_photos(ids);\n"
    "        if (res && res.failed && res.failed.length) { showToast(res.error || '部分照片无法删除，已保留'); await window.reloadPhotos(); }\n"
    "        else if (res && res.error) showToast('删除失败：' + res.error);",
    "Y9d 删不掉的照片回到界面并提示",
)

# Y10. 进度：底部白条 → 顶部毛玻璃进度胶囊(不和底部提示/选择栏抢位置)
block(
    "  function sgProgress(done, total, label) {",
    "  window.sgProgress = sgProgress;",
    """  function sgProgress(done, total, label) {
    let bar = document.getElementById('sg-progress');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'sg-progress';
      bar.className = 'sg-progress';
      bar.innerHTML = '<div class="row"><span class="lbl"></span><span class="num"></span></div><div class="bar"><i></i></div>';
      (document.querySelector('.main') || document.body).appendChild(bar);
    }
    const tb = document.querySelector('.toolbar');
    bar.style.top = ((tb ? tb.offsetHeight : 56) + 12) + 'px';
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    bar.querySelector('.lbl').textContent = label;
    bar.querySelector('.num').textContent = `${done}/${total} · ${pct}%`;
    bar.querySelector('.bar > i').style.width = pct + '%';
    bar.classList.add('show');
    clearTimeout(bar._t);
    if (done >= total) bar._t = setTimeout(() => bar.classList.remove('show'), 1200);
  }
""",
    "Y10 顶部进度胶囊",
)

# Y11. 启动时插着的卡：原来这段在页面解析时就立刻调 popup_cards_now——可 pywebview 的 JS 桥要等
#      页面加载完才注入，那一刻 window.pywebview 还不存在，调用直接抛错被吞掉：开软件时卡已插着，
#      既不弹导入小窗、也不同步卡上新照片(潜伏bug)。改成函数，等桥就绪后由 initFromBackend 调用；
#      已记忆文件夹里新拍的照片同步进来后刷新+提示。
once(
    """  (async () => {
    try { await window.pywebview.api.popup_cards_now(); } catch (e) {}
  })();""",
    """  async function startupCardCheck() {
    try {
      const r = await window.pywebview.api.popup_cards_now();
      if (r && r.synced > 0) {
        await window.reloadPhotos();
        showToast(`已从存储卡同步 ${r.synced} 张新照片`);
      }
    } catch (e) {}
  }""",
    "Y11a 启动查卡改为桥就绪后调用",
)
once(
    "      renderFolderNav();\n      // 后台给存量照片补读EXIF拍摄时间",
    "      renderFolderNav();\n      startupCardCheck();   // JS 桥已就绪：查启动时就插着的卡(新文件夹弹窗+同步新照片)\n      // 后台给存量照片补读EXIF拍摄时间",
    "Y11b 初始化后查卡",
)

# Y12. 分析跑完：堆叠可能新成形，整页淡入刷新
once("    await refreshStacks();\n    render();\n    showToast(`已完成 ${result.analyzed} 张照片的分析`);",
     "    await refreshStacks();\n    renderWithFade();\n    showToast(`已完成 ${result.analyzed} 张照片的分析`);",
     "Y12 分析完成淡入刷新")

# Y13. 全屏：从缩略图飞出/飞回、缩放跟手、翻页滑入、删除后看下一张、快捷键
once(
    """  function openFullscreenPreview(id) {
    const p = PHOTOS.find(p => p.id === id);
    if (!p) return;
    fpPhotoId = id;
    fpZoom = 1;
    fpPan = { x: 0, y: 0 };""",
    """  function openFullscreenPreview(id, fromThumb) {
    const p = PHOTOS.find(p => p.id === id);
    if (!p) return;
    fpPhotoId = id;
    fpCancelAnim();
    fpZoom = 1;
    fpPan = { x: 0, y: 0 };
    fpZoomTarget = 1;
    fpPanTarget = { x: 0, y: 0 };""",
    "Y13a 全屏打开复位缩放目标",
)
once(
    "    applyFpInfo();   // 按当前 fpInfoOpen 决定详情面板开合(默认关)\n    fpOverlay.classList.add('open');\n  }",
    """    applyFpInfo();   // 按当前 fpInfoOpen 决定详情面板开合(默认关)
    const wasOpen = fpOverlay.classList.contains('open');
    fpOverlay.classList.add('open');
    if (!wasOpen && fromThumb) heroOpen(fromThumb, p);   // 从缩略图位置放大飞出
  }""",
    "Y13b 全屏从缩略图飞出",
)
once(
    """  function closeFullscreenPreview() {
    fpOverlay.classList.remove('open');
    fpPhotoId = null;
  }""",
    """  function closeFullscreenPreview() {
    if (!fpOverlay.classList.contains('open')) return;
    heroClose(PHOTOS.find(x => x.id === fpPhotoId));   // 网格里那张可见时飞回原位
    fpOverlay.classList.remove('open');
    fpPhotoId = null;
    fpCancelAnim();
  }""",
    "Y13c 关闭全屏飞回缩略图",
)
once(
    """  if (fpDelete) fpDelete.addEventListener('click', () => {
    const id = fpPhotoId;
    if (id == null) return;
    closeFullscreenPreview();
    trashPhoto(id);   // 复用单张删除(送回收站+5秒可撤销)
  });""",
    "  if (fpDelete) fpDelete.addEventListener('click', () => fpDeleteCurrent());   // 删完直接看下一张",
    "Y13d 全屏删除后看下一张",
)
once("    if (e.key === 'Escape') { closeFullscreenPreview(); return; }",
     "    if (e.key === 'Escape') { e.preventDefault(); closeFullscreenPreview(); return; }", "Y13e Esc只关全屏不清选择")
once(
    "    if (e.key === 'ArrowLeft') { el('#fp-prev').click(); return; }\n    if (e.key === 'ArrowRight') { el('#fp-next').click(); return; }",
    "    if (e.key === 'ArrowLeft') { fpGo(-1); return; }\n    if (e.key === 'ArrowRight') { fpGo(1); return; }",
    "Y13f 方向键翻页带过渡",
)
once(
    "    if (/^(INPUT|TEXTAREA)$/.test((e.target && e.target.tagName) || '')) return;\n",
    """    if (/^(INPUT|TEXTAREA)$/.test((e.target && e.target.tagName) || '')) return;
    // 空格=关闭(QuickLook 习惯)，Delete=删这张并看下一张，I=开关详情面板
    if (e.key === ' ') { e.preventDefault(); closeFullscreenPreview(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); fpDeleteCurrent(); return; }
    if (e.key === 'i' || e.key === 'I') { fpToggleInfo.click(); return; }
""",
    "Y13g 全屏快捷键",
)
once(
    """  el('#fp-prev').addEventListener('click', () => {
    const idx = currentVisibleIds.indexOf(fpPhotoId);
    if (idx > 0) openFullscreenPreview(currentVisibleIds[idx - 1]);
  });
  el('#fp-next').addEventListener('click', () => {
    const idx = currentVisibleIds.indexOf(fpPhotoId);
    if (idx !== -1 && idx < currentVisibleIds.length - 1) openFullscreenPreview(currentVisibleIds[idx + 1]);
  });""",
    "  el('#fp-prev').addEventListener('click', () => fpGo(-1));\n  el('#fp-next').addEventListener('click', () => fpGo(1));",
    "Y13h 翻页按钮带过渡",
)
block("  // wheel over the big image zooms it; once zoomed, drag to pan.",
      "  // 放大到高倍时按需加载原图(全分辨率)替掉2560预览", wiring("ux_fullscreen.js"), "Y13i 全屏缩放跟手+飞出飞回")
once("  fpImage.addEventListener('mousedown', (e) => {\n    if (fpZoom <= 1) return;",
     "  fpImage.addEventListener('mousedown', (e) => {\n    fpCancelAnim();\n    if (fpZoom <= 1) return;",
     "Y13j 拖动时停掉缩放动画")

# Y14. 关闭确认框：淡出缩小再移除(以前瞬间消失)
once("      back.remove();\n      doCloseAction(action);", "      sgDismissModal(back);\n      doCloseAction(action);",
     "Y14a 关闭框退场动画")
once("    back.addEventListener('click', (e) => { if (e.target === back) back.remove(); });",
     "    back.addEventListener('click', (e) => { if (e.target === back) sgDismissModal(back); });",
     "Y14b 点遮罩取消也带动画")

# Y15. 选择栏/快捷键/流式分析/宿主提示：放在初始化之前
once(
    "  if (window.pywebview && window.pywebview.api) initFromBackend();",
    wiring("ux_misc.js") + wiring("ux_scroll.js") + wiring("ux_card.js") + "  if (window.pywebview && window.pywebview.api) initFromBackend();",
    "Y15 选择栏/快捷键/吸顶/日期标签/网格缩放",
)

# ══════════ Z. 2026-10 第二轮(用户实机反馈) ══════════
# Z1. 工具栏：去掉"时间视图/分类视图"切换；密度加一档"迷你"(手机相册那样一屏几十上百张)
once(
    '''        <div class="segmented" id="view-toggle" data-od-id="view-toggle">
          <button class="seg-item active" data-view="time">时间视图</button>
          <button class="seg-item" data-view="category">分类视图</button>
        </div>
''', "", "Z1a 去掉视图切换按钮")
once('          <button class="seg-item" data-density="compact">紧凑</button>',
     '          <button class="seg-item" data-density="mini" title="一屏几十上百张，像手机相册 (Ctrl+滚轮 / Ctrl+加减号 缩放网格)">迷你</button>\n'
     '          <button class="seg-item" data-density="compact">紧凑</button>', "Z1b 密度加迷你档")
# Z1c. 密度变了通知加载引擎：格子变小/变大时缩略图可能要换 256/512 档
once("""    document.documentElement.setAttribute('data-density', density);
    sgPrefs.setItem('shiguang-density', density);
  }""",
     """    document.documentElement.setAttribute('data-density', density);
    sgPrefs.setItem('shiguang-density', density);
    document.dispatchEvent(new CustomEvent('sg-density'));
  }""", "Z1c 密度变化通知")

# Z2. 全屏换图：缩略图 → 屏幕预览 → 原图 逐级换清、只升不降、失败重试(fpLoadImage 在 ux_fullscreen.js)
block("    fpImage.style.backgroundImage = `url('${p.thumbnail || ''}')`;\n    // 切到新照片时复位过曝开关",
      "    el('#dp-fname').textContent = p.name;",
      """    // 切到新照片时复位过曝开关（否则开关显示"开"但图是新照片的普通图，状态错位）
    el('#expo-switch').classList.remove('on');
    fpLoadImage(p);   // 缩略图 → 屏幕预览 → (放大时)原图，逐级换清
""", "Z2a 全屏逐级换清")
block("  // 放大到高倍时按需加载原图(全分辨率)替掉2560预览", "  let fpDrag = null;", "", "Z2b 旧的原图加载换成逐级加载器")

# Z4. 文件夹左滑删除重做：红色胶囊从标签后面 Q 弹地挤出来，过 50% 涨满、桶盖掀开(ux_folder.js)
block("  // swipe-to-delete a folder row", "  // ── sliding segmented control", wiring("ux_folder.js"), "Z4 文件夹左滑胶囊")

# Z5. 点工具栏切换密度：带方向的滑动过渡(sgSwitchDensity 在 ux_scroll.js)
once("  const densitySeg = initSlidingSegmented(el('#density-toggle'), (item) => applyDensity(item.dataset.density));",
     "  const densitySeg = initSlidingSegmented(el('#density-toggle'), (item) => sgSwitchDensity(item.dataset.density));",
     "Z5 切换密度带滑动过渡")

# Z6. 详情面板：过曝/欠曝改用专业叫法(Adobe 中文界面的"高光修剪/阴影修剪")，图例加"部分通道饱和"
once("<h4>过曝 / 欠曝标注</h4>", "<h4>高光 / 阴影修剪</h4>", "Z6a 面板标题")
once('<span class="legend-chip"><span class="legend-dot" style="background:var(--danger)"></span>过曝区域</span>',
     '<span class="legend-chip"><span class="legend-dot" style="background:var(--danger)"></span>高光修剪</span>'
     '<span class="legend-chip"><span class="legend-dot" style="background:#ffb020"></span>部分通道饱和</span>', "Z6b 图例高光")
once('<span class="legend-chip"><span class="legend-dot" style="background:var(--chan-b)"></span>欠曝区域</span>',
     '<span class="legend-chip"><span class="legend-dot" style="background:var(--chan-b)"></span>阴影修剪</span>', "Z6c 图例阴影")
once('aria-label="显示过曝/欠曝区域"', 'aria-label="显示高光/阴影修剪区域"', "Z6d 开关说明")
once("开启后在大图上高亮标注过曝 / 欠曝像素区域。", "开启后在大图上标出细节已经丢失的高光修剪 / 阴影修剪区域。", "Z6e 面板默认说明")

# Z3. 评分算法升级后，旧版评过的照片也算进「开始分析」的张数——按钮上说明为什么(侧栏"待分析"仍是 0)
once("""    el('#analyze-count').textContent = needs;
    el('#btn-analyze').disabled = needs === 0;""",
     """    el('#analyze-count').textContent = needs;
    el('#btn-analyze').disabled = needs === 0;
    el('#btn-analyze').title = needs > pending
      ? `评分算法已更新：其中 ${needs - pending} 张是用旧算法分的档，点一下用新算法重评(你手动改过的档不会变)`
      : '';""", "Z3 分析按钮说明重评")

DST.write_text(html, encoding="utf-8")
print(f"[成功] 共套用 {len(applied)} 处接线改动，已写出 {DST}")
for a in applied:
    print("   -", a)
