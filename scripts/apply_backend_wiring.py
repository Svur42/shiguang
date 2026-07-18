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


# ══════════ A. 数据接线（替代写死的假数据/假交互）══════════

# A1. 4处缩略图地址 → 真实http地址
times("assets/photos/${p.file}", "${p.thumbnail || ''}", 4, "缩略图地址")

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
    folders.forEach(f => { window.__folderNames[f.folder] = f.name; });
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
    """  window.onImportProgress = function (done, total) {
    showToast(`正在导入 ${done}/${total}`);
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
    // 先糊后清：缩略图(512)已铺上，去请求2560高清预览，加载完平滑换上、去模糊
    fpImage.classList.add('fp-loading');
    window.pywebview.api.get_preview(id).then(res => {
      if (res && res.url && fpPhotoId === id) {
        const hi = new Image();
        hi.onload = () => {
          if (fpPhotoId === id) {
            fpImage.style.backgroundImage = `url('${res.url}')`;
            fpImage.classList.remove('fp-loading');
            window.__previewShown = window.__previewShown || {};
            window.__previewShown[id] = res.url;  // 供过曝开关关闭时还原到高清
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
    """    // 真实直方图 + 过曝欠曝占比：异步拿真实数据填（fpPhotoId===id 防切走）
    window.pywebview.api.get_analysis(id).then(res => {
      if (fpPhotoId !== id || !res || res.histograms == null) return;
      buildHist('#hist-main', res.histograms.main, 'var(--fg-2)');
      buildHist('#hist-r', res.histograms.r, 'var(--chan-r)');
      buildHist('#hist-g', res.histograms.g, 'var(--chan-g)');
      buildHist('#hist-b', res.histograms.b, 'var(--chan-b)');
      window.__expoOverlay = window.__expoOverlay || {};
      window.__expoOverlay[id] = res.overlay_url;
      const note = document.getElementById('expo-note');
      if (note) note.textContent = (res.over_pct > 0 || res.under_pct > 0)
        ? `过曝像素约 ${res.over_pct}%，欠曝像素约 ${res.under_pct}%。开启开关在大图上高亮。`
        : '未检测到明显过曝或欠曝像素。';
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

DST.write_text(html, encoding="utf-8")
print(f"[成功] 共套用 {len(applied)} 处接线改动，已写出 {DST}")
for a in applied:
    print("   -", a)
