# Phase 2E 剩余：SD 卡序列号识别 + 每卡文件夹记忆

日期：2026-07-19
状态：待实现（本文档待对抗审查）

## 目标（用户定案的行为规格）

1. 插卡时读卡的**卷序列号**当唯一编号，判断是否与库里已存的卡相同。
2. 序列号匹配已存的卡 → 调出这张卡记忆里导入过的文件夹：
   - 只显示卡上**当前仍存在**的文件夹（及其照片）；
   - 记忆里有、但卡上已被改名/删掉的 → **不显示**。
3. 即使是认得的卡，也扫一遍盘上**其他含照片、不在记忆里**的文件夹：
   - 这些**不自动导入**，弹小导入窗让用户确认是否载入。
4. 没插卡 → 侧边栏空（上一轮已实现的实时过滤保留）。

## 技术前提与已知局限

- 卷序列号（`GetVolumeInformationW`）不用装库、可读；但**卡被格式化后序列号会变**（相机常格式化卡）→ 格式化后同一物理卡会被当新卡。硬件 CID 普通程序读不到。此为方案固有局限，日常够用，需在记忆/文档标注。
- 盘符会漂移：同一张卡两次插入可能得到不同盘符（E:→F:）。存库的是导入当时的绝对路径，会失效。

## 数据模型

- `photos` 新增列 `card_serial TEXT`（migrate，默认 NULL）。一个文件夹内所有照片同属一张卡 → 序列号在文件夹内一致。**不另建表**，复用现有 folder 分组。
- 旧数据 `card_serial` 为 NULL：无法反推序列号，走"盘符 legacy 兜底"（见下）保持不回归。

## 改动清单

### db.py
- SCHEMA + `_migrate` 加 `card_serial TEXT`。
- `insert_photo(..., card_serial=None)` 写入该列。
- `list_folders`：SELECT 增加 `card_serial`（`MAX(card_serial)`，组内一致），返回每个文件夹的 serial，供 api 层实时过滤。
- 新增 `rebind_card_paths(conn, card_serial, new_drive_root)`：把该卡所有 photos 的 path/folder 盘符换成当前盘符。用 `UPDATE OR IGNORE`（碰撞的行跳过，不破坏 UNIQUE(path)）。只在 stored drive ≠ current drive 时调用。
- 新增 `folders_for_serial(conn, card_serial)`：返回该卡记忆里的文件夹路径集合（判断扫到的文件夹是不是"新"的）。

### device_watch.py
- 新增 `read_volume_serial(drive_root)`：ctypes 调 `GetVolumeInformationW` 取卷序列号，返回 8 位十六进制字符串；读不到返回 None（不抛）。带 `_serial_fn` 注入点便于单测。

### scanner.py
- `scan_folder(..., card_serial=None)` 透传给 `insert_photo`。

### api.py
- `_current_card_serials()`：遍历当前可移动盘，读序列号 → 返回 `{serial: drive_root}` 映射（读不到 serial 的盘跳过）。缓存到实例、卡事件时刷新。
- `list_folders` 改造：
  - 拿 `_current_card_serials()`。
  - 对每个 db 文件夹：
    - `card_serial` 在当前映射里 → 重建当前路径（当前盘符 + stored 路径去盘符尾部），`os.path.isdir` 存在才显示；
    - `card_serial` 为 NULL（legacy）→ 盘符兜底：该文件夹盘符当前是可移动盘且 `isdir` → 显示；
    - 否则不显示。
- 插卡入口（`present_card` / `popup_cards_now` / `on_card_inserted` 对应的 api 层）：
  1. 读该盘 serial。
  2. serial 匹配已存卡 且 stored drive ≠ current drive → `rebind_card_paths` 重绑到当前盘符。
  3. `find_photo_folders(drive)` 扫盘；与 `folders_for_serial` 比对（按"去盘符尾部"归一化比对）分成：已记忆 / 新发现。
  4. 只把**新发现**的文件夹交给小导入窗确认；若无新发现则不弹窗，只触发侧边栏刷新。
- `import_folders` 导入卡文件夹时，`card_serial` 一并写入（由 `_folder_is_card` 旁边新增 `_folder_card_serial(folder)` 提供）。

### 前端（走 apply_backend_wiring.py，方式C）
- 新增 `window.reloadFolders()` JS 钩子：重新拉 `list_folders` 重绘侧边栏（卡识别后即使不弹窗也要刷新）。
- app.py 插卡回调里，识别到卡后 `window.evaluate_js("window.reloadFolders && window.reloadFolders()")`。
- 小导入窗渲染逻辑不变（仍是 folders 列表），只是喂进去的是"新发现"子集。

## 测试（TDD，后端可 headless 测）
- `read_volume_serial` 用注入的假 GetVolumeInformation 返回固定 serial。
- `list_folders`：
  - 序列号匹配 + 文件夹存在 → 显示；
  - 序列号匹配 + 文件夹已删（isdir False）→ 不显示；
  - 序列号不匹配（换了张卡，同盘符）→ 不显示旧卡文件夹；
  - legacy NULL serial + 盘符可移动 + 存在 → 显示（不回归）。
- `rebind_card_paths`：E: 记录在 F: 插入后 path/folder 被改成 F:；碰撞行被跳过不报错。
- 扫新文件夹：记忆里已有的不进确认列表，新的进。

## 已知限制（写入记忆）
- 格式化改序列号 → 当新卡。
- `UNIQUE(path)` 跨卡潜在碰撞（两张卡同盘符同结构同时在库）：pre-existing，rebind 用 OR IGNORE 规避崩溃，极端场景该行不重绑。本轮不改 UNIQUE 约束。
- 多卡同插：仍只处理各自 serial，侧边栏合并显示所有当前插着的卡的文件夹。
