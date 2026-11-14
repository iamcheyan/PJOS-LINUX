# PJOS-LINUX & PocketShell 最终工作整理与交接文档 (Handover Report)

**文档时间**: 2026-11-14 11:51 (Local)  
**设备环境**: BaseOS RG34XX (Hostname: `rg34xx`, Allwinner H700, 720×480 物理屏幕)  
**当前状态**: 掌机在线正常运行，SSH/ADB 通道畅通，各项功能与修复已落地并经真机验证。

---

## 一、 设备连接与工程目录速查

### 1. 目标掌机连接
- **当前设备 IP**: `<device-ip>`
- **SSH 登录**:
  ```bash
  sshpass -p "$PJOS_DEV_PW" ssh -o ConnectTimeout=5 -o UserKnownHostsFile=/tmp/pjos-debug-known-hosts -o StrictHostKeyChecking=accept-new root@<device-ip>
  ```
- **关键路径**:
  - 启动器包路径: `/storage/System/pocketjs/apps/boot.pocket`
  - 外部应用目录: `/storage/apps/` (如 `kanade.pocket`)
  - 游戏 ROM 目录: `/storage/content/games/gba/`
  - 配置持久化文件: `/storage/.config/pocketjs/ui-settings.conf`
  - 启动器日志: `/tmp/pocketjs-frontend.log`
  - 前端控制脚本: `/storage/System/launch_frontend.sh`
  - 设置持久化工具: `/storage/System/compat/bin/baseos-settings`

### 2. 本地开发工程仓库
- **启动器工程**: `~/development/pocketshell`
  - 源码: `app/main.tsx`, `app/card-carousel.tsx`, `app/launcher-catalog.ts`, `app/setting-bridge.ts`, `app/pocketfetch-page.tsx`
  - 构建命令: `cd ~/development/pocketshell && make build`
  - 产物: `dist/pocketshell.pocket` (SHA256: `7285c1992e4aede7553817d0cf51fda004be8eac3505db2a7ccb0e4b42412700`)
- **系统底包与运行时工程**: `~/development/PJOS-LINUX`
  - 覆盖层: `overlay/usr/share/pocketshell/`
  - 运行时: `work/pocketjs-runtime/pocket-linux-kms`
  - 截屏脚本: `PJOS_DEVICE_IP="$PJOS_DEVICE_IP" PJOS_DEV_PW="$PJOS_DEV_PW" python3 scripts/capture-device-fb.py <out.png>`
  - 键值模拟: `PJOS_DEVICE_IP="$PJOS_DEVICE_IP" PJOS_DEV_PW="$PJOS_DEV_PW" python3 scripts/send-device-key.py <dev> <code> <hold_sec>`
- **PocketJS SDK**: `~/development/.pocketjs-star-drift-sdk`
  - Kanade 应用工程: `apps/kanade/`
  - 构建命令: `~/.bun/bin/bun tools/pocket.ts compile --runtime-config programs/kanade/pocket.runtime-config.ts --target rocknix-h700-kms --manifest apps/kanade/pocket.json --output apps/kanade/dist/kanade.pocket`

---

## 二、 本次已完成工作与真机实测成果

### 1. 顶部 Tab 标签视觉与逻辑彻底修复
- **用户要求**: 默认只显示文本不显示圆角边框，只有当前选中的标签才显示圆角紫色高亮边框；切换到另一个标签后，原来的标签圆角高亮必须立即取消。
- **实现与验证**: 
  - 修改 `app/main.tsx` 顶部 Tab 渲染逻辑，严格绑定 `currentScreen()`，移除非选中标签的多余样式。
  - 实测截图: `device-boot-new.png` 中仅“应用”有圆角高亮框，设置与系统均为纯文本。

### 2. 全局字号切换与持久化全覆盖
- **用户要求**: 字号改完后要能记住（持久化），重启或退出后不丢失；字号修改要对启动器全部页面（主界面、设置页、系统信息、详情）整体生效。
- **实现与验证**:
  - `baseos-settings` 新增 `fontSize [normal|large|huge]`，持久化存入 `/storage/.config/pocketjs/ui-settings.conf`。
  - 提取 `useAdaptiveFontSize` hook，驱动全站字体动态缩放。
  - 实测截图: `device-system-hardware-huge.png` 验证特大字体整屏完整适配，重启后配置依然完整保持。

### 3. 主界面 Carousel 去除首尾循环（边界 Clamping）
- **用户要求**: 启动器里边的应用去掉循环，不需要首尾无限循环。
- **实现与验证**:
  - 重构 `card-carousel.tsx` 与 `main.tsx` 的卡片索引，移除 modulo 循环计算，采用线性绝对位置映射 `230 - idx * 228`。
  - 在 index 0 按左键严格限制留在 index 0 (`device-test-left-clamp.png`)；在末尾卡片按右键严格停留在末尾 (`device-test-right-clamp.png`)。

### 4. 清理旧内置游戏，安装 5 个版本《塞尔达传说：缩小帽》
- **用户要求**: 删除里边所有自带游戏（Celeste、Dino、Snek、Apotris），只保留系统信息、终端和视频；安装用户 drops 目录下的 5 个版本缩小帽 ROM。
- **完成项**:
  - 清理设备 `/storage/content/games/` 和 `overlay/` 中的旧内置游戏。
  - 部署 5 个版本 GBA ROM（欧版、美版、日版、简体中文、繁体中文）至 `/storage/content/games/gba/`。
  - 重新运行 `pocketshell-games scan` 建立纯净索引。

### 5. 塞尔达传说：缩小帽“系列模式（Series / 文件夹）”与版本选择
- **用户要求**: 支持系列模式，相当于大文件夹，点开后弹出列表供用户选择想玩的版本；下一次将最近游玩版本置顶（MRU）；为系列加上官方封面。
- **实现与验证**:
  - 提取官方缩小帽 256x256 直角封面 `cover-zelda.png` 与高斯模糊背景 `bg-blur-zelda.png`。
  - 在卡片流中聚合为“塞尔达传说：缩小帽（系列 · 5 个版本）”。
  - 居中自适应 720×480 弹窗：显示版本列表、方向键选择、A 开始游戏、B 返回关闭 (`device-test-open-series.png`)。
  - **真机游戏启动实测**: 选择“简体中文”版后按 A，成功通过 RetroArch mGBA 启动游戏，真机画面捕获到游戏标题画面 (`device-zelda-gameplay.png`) 以及存档选择界面 (`device-test-mru-verified.png`)。

### 6. 系统信息（PocketFetch）CLI 界面找回
- **用户要求**: 系统信息原来是个 cli 工具，把它找回来，而不是跳转到 tab。
- **实现与验证**:
  - 移除切换到 System Tab (Screen 4) 的逻辑，恢复全屏独立的 PocketFetch 视图 (`device-test-fetch-launch2.png`)。
  - 显示左侧 Tux 掌机插画与右侧完整系统/CPU/温度/内存/磁盘/网络参数，按 B 键无缝返回启动器 (`device-test-fetch-return.png`)。

### 7. Kanade 视频/音乐播放器分辨率与豆腐块（□）彻底修复
- **用户要求**: 视频和音乐播放不对，变成了框框，分辨率也不对。
- **原因与修复**:
  - 原 `pocket.json` / `profile.ts` 误设为 360×240，导致 fractional 缩放为 480×320 居左上黑边；已重构为原生 720×480 满屏布局。
  - 原字体包缺失 `SarasaUiSC-Bold.ttf` 与 `library-characters.txt`，导致粗体汉字出现 `□` 豆腐块；已将完整 7226 字形的 Sarasa 字体打包进 `kanade.pocket`（27.8MB），彻底消灭豆腐块。

### 8. 用户提供像素艺术封面裁剪与导入
- **用户素材**: 用户上传了包含 Tux 终端与复古播放器的像素画（`uploaded_media_1794624551063.jpg`）。
- **处理**:
  - 自动裁切为两张 256×256 图标与 512×512 高斯模糊背景：
    1. `cover-pocketfetch.png` / `bg-blur-pocketfetch.png` (系统信息)
    2. `cover-kanade.png` / `bg-blur-kanade.png` (Kanade 媒体播放器)
  - 已同步部署至 `pocketshell/app/` 与 SDK 目录。

---

## 三、 接续智能体的下一步任务清单 (Action Items for Incoming Agent)

根据用户最新的决策指引：
> “把第一个系统信息那个也单独提取出来，成一个仓库，然后成一个独立的 APP。然后之后我们就改那想怎么改这个 APP 我们就直接改那 APP 改完之后直接更新到程序里边就好了。我们就不从这个启动器里边给它固化去。也就是说，我们这个启动器或者我们这个系统默认只包含一个终端，其他所有的都是外部的程序。”

接续智能体需要执行以下工作：

### 任务 1：创建独立的 `pocketfetch` 仓库与应用
1. 在 `~/development/pocketfetch` 创建独立项目：
   - 参考 `pocketshell/app/pocketfetch-page.tsx` 和 `apps/kanade` 的配置结构。
   - `pocket.json`: `logical: [720, 480]`, `name: "系统信息"`, `id: "org.pjos.pocketfetch"`.
   - 包含刚才裁剪好的 Tux 像素风封面 `cover-pocketfetch.png`。
2. 配置独立构建脚本并编译输出 `dist/pocketfetch.pocket`。
3. 部署到掌机 `/storage/apps/pocketfetch.pocket`。

### 任务 2：启动器 `pocketshell` 精简化与解耦
1. 修改 `launcher-catalog.ts`：
   - **默认内置应用仅保留 `terminal`（终端）**。
   - 移除内置的固化 `pocketfetch` 页面和逻辑。
   - 通过外部扫描或 `scanInstalledApps`（扫描 `/storage/apps/` 下的 `.pocket` 包），将 `pocketfetch.pocket`、`kanade.pocket` 作为标准的外部独立应用载入卡片流。
2. 启动器中点击应用卡片时，统一使用标准的应用拉起协议（如 `LAUNCH\torg.pjos.pocketfetch` 或运行独立 package）。
3. 重新编译 `pocketshell.pocket` 并部署到掌机 `/storage/System/pocketjs/apps/boot.pocket`。

### 任务 3：真机复验与截图留存
1. 在 RG34XX 掌机上重启启动器。
2. 捕获真实 Framebuffer 截图，确认：
   - 启动器首页只内置终端，外部应用包含独立的 `pocketfetch` 与 `kanade`。
   - 点击独立的系统信息应用能正常启动并显示系统状态，按退出键能正常回到启动器。
   - 系列模式（缩小帽 5 版本）与最近游玩置顶功能保持完好。
3. 截图归档至 `docs/evidence/` 并提交相关代码仓库。
