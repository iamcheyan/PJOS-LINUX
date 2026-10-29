# 目标：在 BaseOS 上跑 PocketJS（RG34XX）

**一句话目标**：一张刷好的卡插进 RG34XX，开机直接进我们的 PocketJS 卡片启动器；之后改界面只靠 `adb push` 替换 `System/`，不再刷镜像。

**状态**：方案待用户拍板，拍板后作为 OMP goal 派发。

---

## 1. 已实测的现状（证据，不是推测）

设备当前跑的是我刷进去的 BaseOS **1.4.0**（`/etc/baseos-release`: `BASEOS=1`, `BASEOS_PLATFORM=h700`），内核 `4.9.170`，ADB 可用（`adb -s <device-serial>`），Wi‑Fi 未配（`wlan0` NO-CARRIER），SSH 不可达。

| 项目 | 实测结果 | 结论 |
|---|---|---|
| 显示设备 | 只有 `/dev/fb0`；`/dev/dri` 不存在；`/sys/class/drm` 为空 | 只能走 fbdev |
| 输入设备 | `/dev/input/event0..2`，`event1 = ANBERNIC-keys`，另有 `js0` | evdev 可用 |
| glibc | 最高符号版本 `GLIBC_2.35` | 我们二进制要求 2.39/2.44 |
| 现有运行时 | `pocket-linux-kms --help` 直接报 `GLIBC_2.44 not found` | 连加载都失败 |
| 前端日志 | `DRM card not found in /dev/dri/card0..card1`（failure streak 6） | 启动脚本先卡在 DRM 探测 |
| 亮度节点 | 无 `/sys/class/backlight`、无 `/sys/class/leds`；存在 `/sys/class/disp/disp/attr` | 亮度映射待查 |
| 音视频/网络工具 | `amixer`、`aplay`、`wpa_cli`、`bluetoothctl` 有；**无 `rocknix-*`、无 `python3`** | bridge 与扫描器都要重做 |
| 分区 | p1 ext4(2G)、p5 rootfs、p6 userdata、**p7 vfat `BASEOS` 已扩展到 28G** | 前端放 p7，`frontend-session` 挂它为 `/mnt/sdcard` |

**关键修正（重要）**：我先前说"PocketJS 没有 fbdev 后端"是**错的**。源码里 fbdev 是一等公民：

- `platforms/linux/fbdev/`（crate `pocket-linux-fbdev`）
- `programs/linux-kms/src/main.rs` 里有明确逻辑：**DRM 打开失败就回退 fbdev**，并且支持 `--fb /dev/fb0`、`--input /dev/input/eventN`
- 帮助文本原文：`DRM falls back to fbdev`

也就是说，**不需要新写输出后端**。真正卡住的是 ABI（glibc）和我写的启动脚本（强制要求 DRM 节点）。

---

## 2. 差距拆解（按依赖顺序）

| # | 差距 | 性质 | 影响 |
|---|---|---|---|
| G1 | 运行时二进制 ABI 太新（要 glibc 2.39/2.44，设备只有 2.35） | 构建/工具链 | 完全无法启动 |
| G2 | 启动脚本硬要求 `/dev/dri/card0..1`，没有就不启动 | 我的脚本缺陷，10 行改动 | 不显示画面 |
| G3 | `__launcher` bridge 依赖 `rocknix-services`/`heya-control`/`systemctl` 等，BaseOS 没有 | 兼容层（shim） | 状态栏/设置显示 `unknown` |
| G4 | 游戏扫描器是 Python3，BaseOS 无 python | 重写为 busybox sh/awk 或静态二进制 | Library 页空 |
| G5 | 首次开机 `expand-storage` 会 `mkfs` p7，抹掉预置 `System/` | 镜像构建顺序 | "一个镜像"必须把 `System/` 放在**扩展之后**能存活的位置（只能靠首启后再写入，或改 expand-storage 逻辑） |

G5 说明：单靠"把 System/ 烤进 p7"做不到，因为首启会格式化 p7。两条可行路径：

- **A（推荐）**：保持"镜像 + 卡上 System/"，首启后由我们（或一个首启钩子脚本）写入 `System/` —— 具体做法是在镜像里放一个 `overlay` 脚本，在 expand 之后、frontend-session 之前把内置的 `/usr/share/pocketshell/System` 拷到 `/mnt/sdcard/System`。这样仍是"一张卡开机即用"。
- **B**：改 `expand-storage`，扩展前先备份 `System/`，扩展后还原。

A 更干净，不动上游逻辑。

---

## 3. 方案（架构决策）

1. **输出**：复用现有 fbdev 后端，不做新后端。启动脚本改为：DRM 存在则用 DRM，否则 `--fb /dev/fb0`；输入 `--input /dev/input/event1`。
2. **ABI**：用 **musl 静态**编译 `pocket-linux-kms`（`aarch64-unknown-linux-musl`），一次性摆脱 glibc 版本问题；若某个 crate 依赖 glibc（如 alsa/libdrm 的系统库链接），退化为 **Debian bookworm 容器（glibc 2.36）交叉/原生编译**，并**不启用 alsa feature**（音量走 `amixer` 命令，不需要链接）。
3. **兼容层**：一组 busybox sh 脚本放进 `System/compat/bin`，`launch_frontend.sh` 启动前把它加到 `PATH` 最前，提供 `rocknix-services`、`heya-control`、`systemctl`(仅查询子集)、`pocketshell-games`、`pocketshell-play` 的等价实现，映射到 BaseOS 的真实能力（`/sys`、`amixer`、`wpa_cli`、`usb-storage-mode`）。
4. **扫描**：把 Python 扫描器重写为 **busybox sh + awk**（目录遍历 + 后缀匹配 + 生成同结构 `library.json`），或交叉编译成静态 aarch64 二进制。启动方式：由前端的 `ROMSCAN` 命令按需调用（不常驻，省内存）。
5. **游戏启动**：`pocketshell-play` 在 BaseOS 上只能拉起"另一个 PocketJS 包"或外部模拟器；BaseOS 上我们只有 PocketJS 运行时，所以一期先实现"包内切换"：`.pocket` → 用运行时 `--package` 重新执行（需先退出当前实例），其他 ROM → 明确提示 `No player configured`（不假装成功）。
6. **单镜像**：在 BaseOS 镜像里内置 `/usr/share/pocketshell/System`，并加一个首启 hook 在 `expand-storage` 之后把它同步到 `/mnt/sdcard/System`（对应 G5 方案 A）。
7. **迭代方式**：日常改动只 `adb push` 到 `/mnt/sdcard/System/...`，`adb shell kill $(pidof launch_frontend.sh)` 让 `frontend-session` 重拉，秒级验证。

---

## 4. 里程碑与验收（每个都要有可复现命令 + 证据）

### M1 — 运行时能在 BaseOS 上加载
- 产出：`pocket-linux-kms`（musl 静态或 bookworm glibc ≤2.36）
- 验收：`adb push` 到 `/mnt/sdcard/System/pocketjs/bin/`，执行
  `adb shell /mnt/sdcard/System/pocketjs/bin/pocket-linux-kms --headless --frames 60`
  期望：打印 `completed 60 logical ticks`，**没有** loader 报错
- 证据：命令输出原文 + `file`/`readelf -V` 结果

### M2 — 画面出现在面板上
- 验收：`adb shell /mnt/sdcard/System/pocketjs/bin/pocket-linux-kms --package .../boot.pocket --fb /dev/fb0 --input /dev/input/event1`
  期望：屏幕显示卡片启动器；`adb shell cat /dev/fb0` 抓帧（720×480×32）转 PNG 存档
- 证据：抓帧 PNG + 按键后第二张 PNG（证明 A/B/L/R 有效）

### M3 — 开机自动进启动器
- 改动：`launch_frontend.sh`（DRM 可选、fbdev 回退、输入路径、compat PATH）
- 验收：重启，`adb shell cat /tmp/pocketjs-frontend.log` 显示 `display: fbdev` 且无 failure streak
- 证据：日志 + 重启后抓帧

### M4 — 状态栏/设置显示真实值
- 改动：compat shims（LEVEL/STATE/CONTROL/SERVICE/SLEEP/LANGUAGE）
- 验收：逐条 `adb shell` 直接调用 shim，返回值与设备真实状态一致（电量=axp2202、音量=amixer、Wi‑Fi=wpa_cli、IP=`ip addr`）；UI 上对应字段同步
- 证据：命令/返回对照表 + UI 抓帧

### M5 — Library 能扫到并列出内容
- 改动：sh 版扫描器（`/storage` 或 `/mnt/sdcard` 下 `content/` 与旧 ROM 目录）+ `ROMS`/`ROMSCAN` 接线
- 验收：放测试文件 → `ROMSCAN` → `ROMS` 返回 JSON → Library 页列出分组与条目
- 证据：JSON 原文 + 抓帧

### M6 — 单镜像
- 改动：镜像内置 `System/` + 首启同步 hook
- 验收：空卡刷写 → 首启 → 直接进启动器（无需人工拷文件）
- 证据：刷卡日志 + 首启抓帧

---

## 5. 涉及文件（预估）

| 文件 | 仓库 | 动作 |
|---|---|---|
| `programs/linux-kms/src/main.rs` | pocketjs（pinned） | 只读参考；不改 |
| `platforms/linux/fbdev/*` | pocketjs（pinned） | 只读参考 |
| `scripts/pocketshell-launcher.rs` | rocknix/pocketjs-runtime | 增补 BaseOS 分支（或由 compat shim 承担） |
| `scripts/pocketshell-games` | rocknix/pocketjs-runtime | 新增 sh/awk 版本 |
| `hello/*.tsx` | rocknix/pocketjs-runtime | 按需微调（Library 文案/加载态） |
| `dist/sdcard-payload/System/launch_frontend.sh` | pocketjs-baseos-frontend | 重写探测与 PATH |
| `dist/compat/*` | pocketjs-baseos-frontend | 新增 shim 集 |
| `overlay/` + `build-image.sh` | PJOS-LINUX | 内置 System/ + 首启同步 |

---

## 6. 风险与回退

- **musl 编译可能被 alsa/libdrm 拖累** → 直接关 alsa feature；libdrm 若为纯 Rust ioctl 则无碍；不行就换 bookworm 容器
- **fbdev 双缓冲/撕裂**：`pocket-linux-fbdev` 已实现，但要在真机确认帧率与撕裂；必要时用 `FBIOPAN_DISPLAY`（若驱动支持）或写两页轮换
- **性能**：RG34XX 单核较弱，卡片动画可能掉帧 → 先保功能，再谈动画
- **回退**：ROCKNIX/PJOS 卡保持不动，任何阶段都能插回去得到一台完整可用的机器；BaseOS 侧失败不影响它

---

## 7. 复用 ROCKNIX 的实现（用户要求：两边都是 Linux，能搬就搬）

ROCKNIX 上已经跑通的东西**不要重写**，逐项搬，只改"宿主差异"那一层。

参考树（只读）：ROCKNIX 仓库 `rocknix`，分支 `feat/pocketshell-cards`；最新整合工作在它的 worktree
`pocketshell-cards-integrate`（`db8afd74a3`，已含日文字体/语言/设置/资料库页）。
包内路径统一为 `projects/ROCKNIX/packages/apps/pocketjs-runtime/`（下称 `<pkg>`）。

| 组件 | ROCKNIX 路径 | BaseOS 上怎么用 |
|---|---|---|
| 启动器 UI（卡片、工作区、设置页、系统页） | `projects/ROCKNIX/packages/apps/pocketjs-runtime/hello/**` | **原样复用**，只调字体 fallback 与文案；不需要改渲染 |
| 终端（ANSI/PTY 五工作区） | `.../scripts/pocketshell-terminal.rs` | 原样复用；PTY 与 ANSI 解析与发行版无关，只需确认 `/dev/ptmx` 可写 |
| bridge 命令契约 | `.../scripts/pocketshell-launcher.rs` | 契约（`LEVEL`/`STATE`/`CONTROL`/`SERVICE`/`SLEEP`/`LANGUAGE`/`ROMS`/`ROMSCAN`/`ROMLAUNCH`）**保持一字不改**，只把"取值/执行"实现换成 BaseOS 能给的 |
| 运行时构建配方 | `.../package.mk` + `scripts/patch-runtime.py` | 复用 patch 与编译参数，把 `POCKETJS_FONT_*`、target、产物路径照抄；ABI 换成 musl |
| 扫描器 | `.../scripts/pocketshell-games`（Python） | **逻辑照抄、语言换成 busybox sh/awk**：同样的目录契约、同样的 `library.json` 结构（`sections/games|music|videos|books`、`{title,path,size,kind}`） |
| 扫描服务 | `.../system.d/pocketshell-games.service` | BaseOS 无 systemd → 改为前端按需调用（`ROMSCAN`）或 `rcS` 后台跑一次 |
| 打包/部署 | `.../package.mk` 的 `makeinstall_*` | 换成 `System/` 目录布局 + `adb push` |

判断原则：**凡是与"发行版服务管理/系统工具"有关的才需要适配（systemd→rcS、rocknix-services→shim、python3→sh）**；
渲染、布局、终端解析、bridge 契约这些与发行版无关，一律复用，不重写。

---

## 8. 执行环境（给 OMP 的硬性事实，避免它瞎试）

- **设备只能从构建机访问**：`ssh <build-host> 'adb -s <device-serial> shell "..."'`。本机没有 adb。
- **构建**：优先 `docker run --platform linux/arm64` 用 alpine/musl 原生编译（避免 qemu 之外再叠交叉工具链）；退化方案 bookworm 容器 + 关 alsa feature。
- **迭代**：`adb push` 到 `/mnt/sdcard/System/...` → `adb shell kill $(pidof launch_frontend.sh)` → `frontend-session` 自动重拉；日志 `/tmp/pocketjs-frontend.log`。
- **不要**依赖 `python3`、`systemctl`、`rocknix-*`、`heya-*`；这些在 BaseOS 上都不存在。
- **不要**再刷整卡做日常迭代；只在 M6 验证单镜像时刷卡。

---

## 9. 给 OMP 的 goal 文本（拍板后可直接用）

```
目标：让 PocketJS 卡片启动器在 BaseOS 1.4.0 / RG34XX（H700，内核 4.9.170）上开机自启并可用。

事实基线（已实测，不要重新推断）：
- 设备只有 /dev/fb0，没有 /dev/dri，/sys/class/drm 为空 → 只能用 fbdev
- glibc 最高 GLIBC_2.35；现有 runtime 要求 2.39/2.44，加载即失败
- 输入：/dev/input/event1 = ANBERNIC-keys（另有 js0）
- 无 rocknix-* 工具、无 python3；有 amixer / aplay / wpa_cli / bluetoothctl / busybox
- PocketJS 已有 fbdev 后端（platforms/linux/fbdev），linux-kms 支持 --fb / --input，且 DRM 失败会自动回退 fbdev
- 卡 p7（vfat BASEOS，已扩到 28G）挂载为 /mnt/sdcard；frontend-session 执行 /mnt/sdcard/System/launch_frontend.sh

按顺序完成并逐个提交证据（命令原文 + 抓帧 PNG，存进仓库 docs/）：
M1 产出可在设备加载的 pocket-linux-kms（优先 aarch64-unknown-linux-musl 静态；不行改用 Debian bookworm 容器、关闭 alsa feature），验收 `--headless --frames 60` 正常
M2 用 `--package .../boot.pocket --fb /dev/fb0 --input /dev/input/event1` 出画面，抓帧并存档
M3 改 launch_frontend.sh：DRM 可选、fbdev 回退、输入设备、compat PATH；重启后自动进启动器
M4 写 compat shims 并提供 LEVEL/STATE/CONTROL/SERVICE/SLEEP/LANGUAGE，逐条与设备真实状态核对
M5 用 busybox sh/awk 重写扫描器，ROMSCAN/ROMS 生效，Library 列出测试文件
M6 把 System/ 内置进 BaseOS 镜像，并加首启同步 hook（expand-storage 会 mkfs p7，不能直接预放）

约束：不改上游 PocketJS 的渲染语义；不假装未验证的功能可用；每步都在真机（adb）验证；ROCKNIX 卡与分支保持不动。
```
