# 01 — 当前耦合审计

> 阶段一交付物。只做设计，不写实现代码。本文所有结论都能落到「文件:行 + 字面量」。
>
> 引用约定：
> - **PJOS:** 本仓库 `PJOS-LINUX`，`main` `dc99d574c9e0bd9c3cf87cd1008ea02db4bd56ac`。
> - **RNX:** `rocknix` 工作副本，本地 `main` = `e484b261d2c3d9c8732be613a670ff0dc7431f51`。**注意：该工作副本落后 `origin/main` 41 个提交**（`git rev-list --left-right --count HEAD...origin/main` → `0 41`），所以 RNX 引用只对 `e484b26` 成立，不对 `origin/main` 成立。
> - **PKT:** RNX 里的预编译 PocketJS 源码树 `build.ROCKNIX-H700.aarch64/build/pocketjs-runtime-e6770376626a4de5c93eaa6fb048e7e9ffb81f9f/`（pinned upstream `e6770376626a4de5c93eaa6fb048e7e9ffb81f9f`），下文简称 `PKT/`。

---

## 0. 一句话结论

PocketShell 今天不是「运行在平台上」，而是**被编译进平台**：它的 UI 源码、PTY/ANSI 模型、桥接命令、systemd 单元、启动脚本、字体资产、甚至 profile 哈希，全部由 `pocketjs-runtime` 这一个 Rocknix 包产出，而 BaseOS 侧靠 `frontend-session` 按**文件名**挑选启动器。平台上没有一层「PocketShell 可以查询的接口」，只有一套**留给 Shell 自己解析的宿主细节**：`/sys` 节点、`/dev` 节点、外部命令名、systemd 单元名、`/storage` 目录布局。

---

## 1. 依赖清单：PocketShell 边界在哪里

判定「这是 PocketShell」的口径：会随 Shell/UI 发版而变化的代码与资产。

| 组件 | 位置 | 归属证据 |
|---|---|---|
| Shell UI（工作区、卡片、设置页、系统页） | `RNX projects/ROCKNIX/packages/apps/pocketjs-runtime/hello/main.tsx`（350 行，tracked）、`hello/launcher-catalog.ts`、`hello/pages/*.tsx`（untracked） | `package.mk:24-27` 把 `hello/` 拷成 guest app 目录并 `bun tools/pocket.ts compile` |
| Library 工作区 | `hello/library.tsx`、`hello/library-model.ts`、`library-pocket.json` | `package.mk:38-44` 编译成 `library.pocket` |
| 终端/ANSI/PTY 模型 | `scripts/pocketshell-terminal.rs`（1625 行） | `patch-runtime.py:9` 拷进 pinned 运行时 `engine/guest-rquickjs/src/` |
| 宿主桥（3 个） | `scripts/pocketshell-launcher.rs`、`scripts/pocketshell-library.rs`、`pocketshell-terminal.rs` 的 `PocketShell::command` | `patch-runtime.py:9-11`、`:34-52` 注入 `ui.__launcher` / `ui.__library` / `ui.__pocketshell` |
| 启动/会话脚本 | `scripts/pocket`、`pocketjs-session`、`pocket-session-run`、`pocketjs-native-launch`、`pocketjs-legacy-settings` | `package.mk:68-71`、`:65` 安装到 `/usr/bin`、`/usr/libexec` |
| 休眠守护 | `scripts/pocketjs-sleep`（Python3） | `package.mk:91-92` |
| 热键守护 | `scripts/rocknix-hotkeys` | `package.mk:85-87` |
| 远程开发宿主 | `tools/pocketshell-dev/**`（Rust，含 OTA 模拟器、镜像中继在 `tools/pocketshell-mirror/**`） | `package.mk:61`、`:88-90` |
| systemd 单元 | `system.d/pocketjs-kms.service`、`pocketjs-recovery.service`、`pocketshell-dev.service`、`pocketjs-sleep.service`、`rocknix-hotkeys.service` | `package.mk:81-90` |
| profile（编译进运行时的设备事实） | `config/profile.ts`（**实际参与编译的那份**）、`profile.ts`（包根同名副本） | `package.mk:24` 拷 `config/`；`PKT/generated/pocket_profile.rs:3-19` 证明 density=2、单一逻辑视口 |

---

## 2. 依赖类型 A：绝对路径（`/sys` / `/proc` / `/dev` / `/storage` / `/run`）

### 2.1 Shell 桥接层（真正在 guest 渲染线程上执行的代码）

| 文件:行 | 字面量 | 语义 | 平台泄漏后果 |
|---|---|---|---|
| `RNX .../scripts/pocketshell-launcher.rs:7` | `/sys/class/backlight` | 亮度百分比 = `brightness*100/max_brightness` | 无背光节点的设备恒返回 `"unknown"` |
| `RNX .../scripts/pocketshell-launcher.rs:18-24` | `amixer get Master` / `pactl get-sink-volume @DEFAULT_SINK@` | 音量百分比 | 两个工具都不存在的平台只能 `"unknown"` |
| `RNX .../scripts/pocketshell-launcher.rs:53-88`（`path` 在 `:54`） | `/storage/.config/pocketjs/runtime.conf` | `SLEEP` 改写 `[sleep] timeout` | 目录布局是 Rocknix 事实 |
| `RNX .../scripts/pocketshell-library.rs:7` | `["/storage/docs","/storage/books","/storage/reports","/storage/library"]` | Library 根目录 | BaseOS 上没有 `/storage`（挂的是 `/mnt/sdcard`） |
| `RNX .../scripts/pocketshell-library.rs:8` | `/storage/pocketshell/library` | 阅读状态目录 | 同上 |
| `RNX .../scripts/pocketshell-library.rs:12,15` | `POCKETSHELL_LIBRARY_ROOTS`、`POCKETSHELL_LIBRARY_DATA_ROOT` | 唯一的路径覆盖手段（环境变量） | 需要平台预先注入环境变量才能重定位 |
| `RNX .../scripts/pocketshell-terminal.rs:955-979` | `/bin/sh`、`/usr/bin/ranger`、`/usr/bin/lf`、`/usr/bin/vim`、`/bin/vi`、`/usr/bin/htop`、`/usr/bin/top` | 五个工作区各自 spawn 什么 | 「工作区 2 = 文件管理器」这个产品语义被写死成路径探测 |

**PKT 中实际被编译的那份更重**（`PKT/engine/guest-rquickjs/src/pocketshell_launcher.rs`，324 行）：

| 行 | 字面量 |
|---|---|
| `:25` | `/etc/os-release` |
| `:32` | `/proc/stat`（CPU 使用率） |
| `:55-58` | `/sys/class/thermal/*/temp` |
| `:67-68` | `/sys/devices/system/cpu/cpufreq`、`/sys/devices/system/cpu/cpu0/cpufreq` 的 `scaling_cur_freq` |
| `:100` | `/sys/class/graphics/fb0/virtual_size` |
| `:104-112` | `/sys/class/drm/*/modes`（按名字含 `DSI`/`HDMI` 过滤） |
| `:117` | `/proc/meminfo` |
| `:127-129` | `statvfs("/storage")` |
| `:136` | `/proc/device-tree/model` |
| `:138` | `/proc/sys/kernel/osrelease` |
| `:150` | `/usr/share/bootloader/H700_DDR4_u-boot-sunxi-with-spl.bin` |
| `:202` | `/sys/class/power_supply/{battery,BAT0,BAT1,rk817-battery,cw2015-battery}/capacity` |
| `:239-241` | `/sys/class/net/*/wireless` + `operstate` |

### 2.2 启动/会话脚本

| 文件:行 | 字面量 | 依赖类型 |
|---|---|---|
| `RNX .../scripts/pocketjs-session:4-6` | `/usr/share/pocketjs/apps/boot.pocket`、`/usr/libexec/pocket-linux-kms` | 路径 |
| `RNX .../scripts/pocketjs-session:7` | `/storage/pocketjs/{apps,data,cache,logs}` | 路径 |
| `RNX .../scripts/pocketjs-session:16-27` | `POCKETJS_CARD`、`/sys/class/drm/card*-*/status`、`/dev/dri/${connector%%-*}`、兜底 `/dev/dri/card0` | 路径 + 环境变量 |
| `RNX .../scripts/pocket-session-run:9-11` | `/run/lock/pocketjs-display.lock`、`flock -n 9` | 路径 + IPC（文件锁） |
| `RNX .../scripts/pocket-session-run:14,16,21,27,29` | `systemctl is-active|stop|start pocketjs-kms.service|pocketjs-recovery.service|pocketjs-foreground.service` | 工具 + **服务管理器语义** |
| `RNX .../scripts/pocket-session-run:38-45` | `/sys/class/drm/card*-*/status` → `drm_index` | 路径 |
| `RNX .../scripts/pocket-session-run:47-57` | `systemd-run --unit=pocketjs-foreground`、`TTYPath=/dev/tty7`、`chvt 7`、`SDL_KMSDRM_DEVICE_INDEX`、`SDL_VIDEODRIVER=kmsdrm`、`SDL_AUDIODRIVER=pulseaudio`、`XDG_RUNTIME_DIR=/run/0-runtime-dir`、`SDL_GAMECONTROLLERCONFIG_FILE` | 工具 + 环境变量（把 **SDL 后端选择**塞进了 Shell 的启动路径） |
| `RNX .../scripts/pocketshell-dev:3` | `--bind ${POCKETSHELL_DEV_BIND:-127.0.0.1} --port 8080` | 端口 |
| `RNX .../scripts/pocketjs-sleep:17-19` | `/sys/class/backlight`、`/storage/.config/pocketjs/runtime.conf`、`/storage/.config/pocketjs/sleep-state` | 路径 |
| `RNX .../scripts/pocketjs-sleep:92-95` | `os.listdir("/dev/input")`，取 `event*` | 路径 |
| `RNX .../scripts/rocknix-hotkeys:12-16` | `/sys/class/input/js*/device/name` 匹配 `"H700 Gamepad"` → `/dev/input/jsN` | 路径 + **按设备名匹配** |
| `RNX .../scripts/rocknix-hotkeys:10,25-26` | `HOTKEY_DEVICE`、`HOTKEY_SELECT_BTN=8`、`HOTKEY_START_BTN=9`、`HOTKEY_HOLD_MS=1000` | 环境变量 + 硬编码按钮编号 |
| `RNX .../scripts/rocknix-hotkeys:39-40` | `systemctl stop pocketjs-foreground.service` / `restart pocketjs-kms.service` | 工具 |
| `RNX .../scripts/pocketjs-native-launch:2-12` | `/usr/bin/disk-browser`、`/usr/bin/heya-tool`、`/usr/bin/xmplayer` | 工具（应用启动被写成 Shell 的职责） |
| `RNX .../scripts/pocketjs-legacy-settings:3-25` | `dialog`、`nmcli`、`bluetoothctl`、`usbgadget`、`ip -4 addr`、`less -R` | 工具 |
| `RNX .../system.d/pocketjs-kms.service:12-19,26` | `HOME=/storage`、`EnvironmentFile=-/storage/.config/pocketjs/runtime.conf`、`TTYPath=/dev/tty7`、`ExecStartPre=/usr/bin/chvt 7`、`WantedBy=rocknix.target` | 环境变量 + 设备节点 + target 名 |
| `RNX .../system.d/pocketshell-dev.service:8-16` | `ProtectSystem=strict`、`ReadWritePaths=/storage`、`SupplementaryGroups=video input` | 沙箱 + 组名 |
| `RNX .../system.d/pocketjs-sleep.service:9-10` | `ExecStart=/usr/libexec/pocketjs-sleep` | 路径 |

---

## 3. 依赖类型 B：外部工具（Shell 直接 fork 的子进程）

PKT 版本把**每一次**外部调用都包进 `/usr/bin/timeout 2`（`PKT/.../pocketshell_launcher.rs:7-19`），注释说明理由是 `pactl` 在设备上阻塞导致整屏冻结（`:3-6`）——这条注释本身就是「在渲染线程上跑平台查询」的失败证据。

| 工具 | 调用点 | 用途 | 在 BaseOS 上是否存在 |
|---|---|---|---|
| `amixer` / `pactl` | `launcher.rs:18-24`（RNX）/`:254-262`（PKT） | 音量 | `amixer` 有（`docs/13` 实测表），`pactl` 无 |
| `heya-control` | `launcher.rs:37-46` | 音量/亮度/Wi-Fi/蓝牙写操作 | **无**（`heya` 是 Rocknix 包） |
| `rocknix-services` | `launcher.rs:47-51`（RNX）/`PKT:184-186,280-284` | 服务开关与状态 | **无** |
| `systemd-run` | `launcher.rs:29-35`（`LAUNCH`）；`PKT/scripts/pocketshell-launcher.rs:87-88`（`--unit=pocketshell-game`，仅 V2 有此动词） | 起应用 / 起游戏 | **无**（无 systemd） |
| `systemctl` | `launcher.rs:83`（`try-restart pocketjs-sleep.service`）、`PKT/.../pocketshell_launcher.rs:316`（V3） | 重启休眠守护 | BaseOS 有 **shim**（`PJOS overlay/usr/sbin/systemctl:1-9` 注释列出只支持 `stop NetworkManager`/`wpa_supplicant`/`bluetooth`，其余静默成功） |
| `ip` | `PKT:224` | `LEVEL\tip` | 有 |
| `usbgadget` | `PKT:186,253` | `STATUS\tusb` | **无** |
| `nmcli` / `bluetoothctl` | `pocketjs-legacy-settings:3-25` | 网络/USB 控制台 | `bluetoothctl` 有、`nmcli` 无 |
| `ranger`/`lf`/`vim`/`htop`/`top` | `pocketshell-terminal.rs:955-979` | 工作区程序 | 部分（BusyBox 只有 `vi`/`top`） |

`docs/13-pocketjs-on-baseos.md:20` 已记录这条差异的实测结果：BaseOS 上「`amixer`、`aplay`、`wpa_cli`、`bluetoothctl` 有；**无 `rocknix-*`、无 `python3`**」。

---

## 4. 依赖类型 C：环境变量

| 变量 | 读取点 | 谁写 |
|---|---|---|
| `POCKETJS_APP` | `pocketjs-session:5`、`pocket:4` | 单元 `EnvironmentFile`（`pocketjs-kms.service:13`） |
| `POCKETJS_CARD` | `pocketjs-session:16` | 同上 |
| `POCKETSHELL_LIBRARY_ROOTS` / `_DATA_ROOT` | `pocketshell-library.rs:12,15` | **无人写**（全仓 grep 只有定义处；BaseOS 侧需自行注入） |
| `POCKETSHELL_DEV_BIND` | `pocketshell-dev:3` | 无人写 |
| `HOTKEY_DEVICE` / `_HOLD_MS` / `_START_BTN` / `_SELECT_BTN` | `rocknix-hotkeys:10,23-26` | 无人写 |
| `HOME=/storage` | `pocketjs-kms.service:12`、`pocketshell-dev.service:10`、`pocketjs-sleep.service:9` | 单元文件 |
| `SDL_*` / `XDG_RUNTIME_DIR` / `LOVE_GRAPHICS_USE_OPENGLES` | `pocket-session-run:52-56` | 脚本 |
| `POCKETSHELL_OTA_*` / `RECORD_MS` | `tools/pocketshell-dev/src/main.rs:66-90,638-640` | 开发者 |
| `KEYBOARDD_ADDR` / `KEYBOARDD_BIN` / `KEYBOARDD_DB` | `PJOS overlay/usr/sbin/keyboardd-launch.sh:13-15,21-22`、`runtime/keyboardd/cmd/keyboardd/main.go:24-26` | `frontend-session`（默认 `127.0.0.1:8787`） |

`SDL_VIDEODRIVER=kmsdrm` 与 `SDL_AUDIODRIVER=pulseaudio` 是最刺眼的一对：**显示后端与音频后端的选择被写进了 Shell 的启动脚本**，而 Shell 的职责本应只是「画 UI」。

---

## 5. 依赖类型 D：IPC / 服务契约

| 通道 | 端点 | 提供者/消费者 | 证据 |
|---|---|---|---|
| 进程内 JS 桥（同步字符串命令） | `ui.__launcher(cmd)` | Shell → 宿主 Rust | `patch-runtime.py:45`；`PKT/.../lib.rs:103` |
| 同上 | `ui.__pocketshell(cmd)` | Shell → PTY 模型 | `patch-runtime.py:41-44`；上限 16384 字节 |
| 同上 | `ui.__library(cmd)` | Library → 文件桥 | `patch-runtime.py:46` |
| 同上 | `globalThis.__pocketshellOutput` | PTY 模型 → Shell（每帧写一次） | `PKT/.../lib.rs:130-136` |
| 同上 | `ui.__pocketshellFrame()` | 定义存在，**无任何 guest 调用者** | `patch-runtime.py:48-50`；`grep -r __pocketshellFrame PKT/apps PKT/framework` 无命中 |
| HTTP（loopback） | `127.0.0.1:8787` Input API（keyboardd） | 所有前端 | `PJOS docs/16-keyboardd-input-framework.md` 表；`runtime/keyboardd/cmd/keyboardd/main.go:26` |
| HTTP + WS | `:8080` dev host（`/ws`、`/api/frame`、`/device/key`、`/api/ota/*`） | 浏览器 → 设备 | `tools/pocketshell-dev/src/main.rs:275-278,323-520` |
| HTTP | `:8081` 镜像中继 | 浏览器 → HX90 → adb | `tools/pocketshell-mirror/server.py:133` |
| HTTP | `:8137` Library 浏览器 harness | 浏览器 → fixture | `tools/pocketshell-dev/library-harness.js:73` |
| PTY | `libc::openpty` + `TIOCSCTTY` | 终端工作区 | `pocketshell-terminal.rs:990,1018-1025` |
| 文件锁 | `/run/lock/pocketjs-display.lock` | 前台独占 | `pocket-session-run:10-11` |
| 外部命令（时间序列） | `systemd-run --unit=pocketjs-launcher` / `pocketshell-game` / `pocketjs-foreground` | 应用/游戏/前台 | `launcher.rs:29-35`；`PKT/scripts/pocketshell-launcher.rs:87-88`；`pocket-session-run:47` |

**没有任何 D-Bus，没有任何 unix socket**（scout 对 `dbus|DBus|sd_bus`、`AF_UNIX|UnixListener|sockaddr_un` 全量 grep，范围 = 包 + dev host + mirror，结果为空）。也就是说：Shell 现有的「系统接口」其实是**字符串命令 + 子进程 + sysfs 文本解析**。

---

## 6. 依赖类型 E：BaseOS 侧（PJOS-LINUX）如何把 Shell 装进来

BaseOS 不「提供接口」，它提供**约定俗成的名字**：

| 位置 | 事实 | 后果 |
|---|---|---|
| `PJOS overlay/etc/inittab:4` | `::respawn:/sbin/frontend-session` | 任何前端都从这一个脚本启动 |
| `PJOS overlay/usr/sbin/frontend-session:7-11` | `set -a; . /etc/baseos-release; set +a` | 把 `BASEOS_PLATFORM=h700`（`build-rootfs.sh:121`）、`BASEOS_TARGET`、`BASEOS_PANEL_ROTATION_CCW`（`:128`）、`BASEOS_WIFI`/`BASEOS_BLUETOOTH`（`:129`）灌进**前端的进程环境** |
| `PJOS overlay/usr/sbin/frontend-session:164-183` | 按存在性依次选 `$SD/System/frontend` → `launch_frontend.sh` → `$SD/System/slot` → `MinUI.pak/launch.sh` → `spruce/scripts/runtime.sh` | **没有版本、没有能力、没有 API 版本协商**，只有文件名 |
| `:191-197` | 等 `/dev/mali0` 存在（≤30×0.1s） | 显示后端细节泄漏进启动序 |
| `:238-240` | `keyboardd-launch.sh > /tmp/keyboardd.log`（失败不阻塞） | 输入框架是「可选外挂」 |
| `:245` | `exec /lib/ld-linux-aarch64.so.1 "$LAUNCH" > /tmp/$FRONTEND.log` | 二进制前端通过 **glibc 动态加载器**直接 exec；`docs/13` 实测 BaseOS 1.4.0 只有 `GLIBC_2.35`，而 Rocknix 编出的运行时需要 2.39/2.44 → 换平台即换 ABI |
| `:99-114` | 挂载重试写死 `/dev/mmcblk1p1`、`/dev/mmcblk0p7` | 分区号进脚本 |
| `:32-39`、`:47-48`、`:62-66`、`:68-71` | `baseos-boot-migrate`、`baseos-update confirm`、`baseos-diag`、`baseos-splash` | BaseOS 私有工具；Shell 侧只能通过 `important_splash` 这类间接方式影响画面 |
| `PJOS overlay/etc/init.d/rcS:11-12` | `os_sleep=/sys/class/power_supply/axp2202-battery/os_sleep`，写 `16` | PMIC 型号进「通用」rcS |
| `:115` | `insmod /lib/modules/h700_late_usb.ko` | SoC 模块名 |
| `:120` | `/bin/mount -t ext4 /dev/mmcblk0p6 /data` | 分区号 |
| `:380-381` | `/usr/sbin/h700-speaker-amp-load` | SoC 专有音频修复 |
| `PJOS build-rootfs.sh:52-53,117-130` | 生成 `/etc/baseos-release`（含 `BASEOS_PLATFORM`、`BASEOS_MODEL`、旋转、无线开关） | 唯一一份「设备事实」，但**只给脚本用**，没有给应用的查询接口 |
| `PJOS devices.json:12-14` | `panel_rotation_ccw`、`wifi`、`bluetooth` 是**构建期**字段 | 应用侧拿不到，只能去 `/sys` 猜 |
| `PJOS docs/15-bsp-architecture.md:59` | 已自评：「PocketJS 在应用侧探测硬件（fb 路径、evdev 名、电源节点）…换设备要改应用仓库，违背分层」 | 与本审计结论一致 |

`docs/13-pocketjs-on-baseos.md:40` 把这条差异记为差距 G3（「`__launcher` bridge 依赖 `rocknix-services`/`heya-control`/`systemctl` 等，BaseOS 没有」），`:57` 给出的对策是写 **compat shim** 去「提供 `rocknix-services`、`heya-control`、`systemctl`(仅查询子集)、`pocketshell-games`、`pocketshell-play` 的等价实现」。也就是说：**换一个平台 = 在平台侧重新实现另一个平台的命令名**。这不是适配，是模仿。

---

## 7. 契约漂移（审计中发现的、必须先修掉的事实）

这一节不是「风格问题」，是**同一份代码存在多个互不相同的契约版本**，任何迁移都必须先选定基准。

### 7.1 `__launcher` 存在四份实现，动词集互不相同

这四份文件我逐个数过行、逐个 grep 过动词（命令与计数见本节末）：

| # | 文件 | 行数 | 独有动词 | 说明 |
|---|---|---:|---|---|
| V1 | `RNX projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts/pocketshell-launcher.rs`（tracked） | 91 | — | 只有 `LEVEL`/`LAUNCH`/`CONTROL`/`SERVICE`/`SLEEP`（`:6,18,29,37,47,53`）。`package.mk:56` 会把 V1 拷进 pinned 源码树 |
| V2 | `PKT/scripts/pocketshell-launcher.rs`（构建树里 `scripts/` 的副本） | 285 | `LANGUAGE`、`ROMS`、`ROMSCAN`、`ROMLAUNCH`、`STATE` | 有 `run()` 的 `/usr/bin/timeout 2` 包装；**没有** `STATUS`/`SYSTEM` |
| V3 | `PKT/engine/guest-rquickjs/src/pocketshell_launcher.rs`（**被 `lib.rs:103` 实际编译进产物**） | 324 | `STATUS{ssh,adb,usb}`（`:184-186`）、`SYSTEM`（`:187`）、`LEVEL{battery,ip,wifi}`（`:201,223,237`） | 同样有 `timeout 2` 包装（`:3-19`）；**没有** `LANGUAGE`/`ROMS*`/`STATE` |
| V4 | `PKT/engine/guest-rquickjs/src/pocketshell_launcher.rs.new`（上次构建残留） | 319 | 同 V3 | 未被 `lib.rs` 引用 |

调用侧同样分裂：

- tracked 的 `hello/main.tsx`（350 行）只调 `LEVEL`/`CONTROL`/`SERVICE`/`SLEEP`/`LAUNCH`（`:39,45-62`）；
- 预编译产物里的 `apps/rocknix-h700/main.tsx`（1033 行）额外调 `STATUS`（`:287-289`）与 `SYSTEM`（`:292`），而这两个动词**只有 V3/V4 实现**。

**结论**：`package.mk:24-27` 拷贝的是 tracked 的 `hello/`（350 行）与 `config/`，但构建树里的 UI（1033 行）与桥（V3，324 行）都不是这两份。也就是说**当前构建产物不由当前 tracked 源码产生**。移机基线必须由用户拍板（README 决策点 D1）。

复现命令：

```sh
B=<rocknix>/build.ROCKNIX-H700.aarch64/build/pocketjs-runtime-e6770376626a4de5c93eaa6fb048e7e9ffb81f9f
for f in "$B/scripts/pocketshell-launcher.rs" \
         "$B/engine/guest-rquickjs/src/pocketshell_launcher.rs" \
         "$B/engine/guest-rquickjs/src/pocketshell_launcher.rs.new" \
         <rocknix>/projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts/pocketshell-launcher.rs; do
  printf '%-70s %4s  LANG=%s STATUS=%s STATE=%s ROMS=%s\n' "$f" "$(wc -l <"$f")" \
    "$(grep -c '\["LANGUAGE"' "$f")" "$(grep -c '\["STATUS"' "$f")" \
    "$(grep -c '\["STATE"' "$f")" "$(grep -c '\["ROMS"' "$f")"
done
# 实测：91/0/0/0/0 与 285/3/0/6/1 与 324/0/6/0/0 与 319/0/6/0/0（顺序同上面 for 列表）
```

- 发出：`pocketshell-terminal.rs:715` → `{fg:06x}:{bg:06x}:{flags}:{start_col}:` + text；同文件 `:1213-1219` 的注释明确写「Wire shape is fg:bg:flags:col:text — skip the four numeric fields」。
- 解析：`hello/main.tsx:127` 与 `PKT/apps/rocknix-h700/main.tsx:426-431` 都执行 `parts.slice(3).join(":")` 当文本 → **列号被当成文字渲染**。

这条不改，UI 逐帧比对任何迁移都是噪声。

### 7.3 profile 有多份，显示事实互相矛盾

| 文件 | 逻辑视口 | density | 是否参与编译 | 是否入库 |
|---|---|---|---|---|
| `RNX .../pocketjs-runtime/profile.ts`（包根） | `[[360,240],[720,480]]` | 1 | 否 | **未入库**（`git status` 显示 `??`） |
| `RNX .../pocketjs-runtime/config/profile.ts` | `[[360,240]]` | 2 | **是**（`package.mk:24` 拷 `config/`） | 已入库 |
| `PKT/config/profile.ts` = `PKT/programs/rocknix-h700/profile.ts` | `[[360,240]]` | 2 | 构建树副本（两份 `diff` 相同） | 构建产物 |
| `PKT/generated/pocket_profile.rs:10-19` | `[[360,240]]` | 2 | 产物事实 | 生成物 |

profile 身份 = 七字段 SHA-256（`PKT/contracts/spec/profile.ts:29-31`），所以「包根那份」与「config 那份」是**两个不同的 target**：`[[360,240],[720,480]]`/density 1 与 `[[360,240]]`/density 2 的哈希不同。今天真正生效的是 `config/` 那份（`package.mk:24` 与 `PKT/generated/pocket_profile.rs:10-19` 双重证据）。Shell 侧任何按包根 profile 推导的视口/缩放数学都与真机不符。

### 7.4 其他已验证的契约级缺口

| 缺口 | 证据 |
|---|---|
| `SLEEP` 在 tracked 版里写的是字面反斜杠 | `launcher.rs:74` 比较 `'\\n'`、`:80` join `"\\n"`；PKT 的 V2/V3 用 `'\n'`/`"\n"` |
| `__pocketshellFrame` 定义了但没人用 | `patch-runtime.py:48-50`；`grep` 无 guest 调用者 |
| dev host 文档列了 `/api/ota/rollback`，路由里没有 | `tools/pocketshell-dev/src/main.rs:18` vs 路由 `:513-520` |
| `pocketshell-launcher.rs` 用 `timeout 2` 包每一次查询，说明查询会阻塞渲染线程 | `PKT/.../pocketshell_launcher.rs:3-19` |

---

## 8. 跨仓事实：应用侧（pocket-*）已经自己长出了一套「平台模型」

PocketShell 之外，`pocket-*` 每个仓库都自带一套 profile/capability/端口约定，彼此不一致：

| 仓库 | 自有的平台词汇 | 证据 |
|---|---|---|
| `pocket-launcher` | `capabilityIDs = wifi,bluetooth,battery,touch,storage,notifications,gamepad`；`profileIDs = handheld,dap,eink,desktop`；端口 `127.0.0.1:18788`；全部 `mock:true` | `apps/pocket-launcher/backend/launcherd/registry.go:21-33`、`main.go:21-24`；`README.md:9` 明示「尚未集成进 PJOS-LINUX」 |
| `pocket-settings` | `domains` 11 个、`profiles` 7 个（含 `M21`）、`requiredCapabilities` 16 个；端口 `127.0.0.1:8090`；`controllable` 永远 `false` | `apps/pocket-settings/backend/settingsd/main.go:25-35,206-210,387-395` |
| `pocket-files` | profile `desktop,handheld,reader,dap` + 视口→profile 映射表；**读真硬件** `/proc/self/mountinfo`、`/sys/class/block/*/removable`、`/dev/disk/by-uuid` | `frontend/scripts/check-profiles.ts:5-13`、`backend/storaged/discovery.go:28-46,117-119,185-192` |
| `pocket-music` | 无 profile，只有 `MUSICD_MOCK` provider 开关；`mpv` + `ffprobe` + `ffmpeg` | `backend/main.go:109-128`、`mpv.go:87-108`、`library.go:457-461` |
| `pocket-terminal` | `journalctl`、`systemctl list-units`、`/proc/*`、`/sys/class/thermal`、`/var/log/*` | `terminald/diagnostics.go:114-117,268-281,344-350`、`logs.go:30-34` |
| `pocket-web` | profile `desktop,handheld,dap,reader`；用 `exec.LookPath` 把 URL 交给兄弟二进制 | `backend/pjapps.go:44-78` |
| `pjos-keyboard` | capability 只有 `Touch|DPad|Gamepad|HardwareKeyboard`，**按能力选输入模式，不按设备名**（正确范式） | `src/keyboard/capability.ts:10-27`、`packaging/manifest.json:1-25` |

`pocket-settings` 与 `pjos-keyboard` 已经证明了正确形态：**能力用 `{available, enabled, controllable, source, reason}` 表达，未知给 reason 而不是隐藏**。这条应当直接成为 Platform API 的 Capability 语义基准（见 [04](04-capability-feature.md)）。

---

## 9. 耦合强度排序（决定迁移顺序）

| # | 耦合 | 强度 | 为什么排这个位置 |
|---|---|---|---|
| C1 | Shell 桥接层直接读 `/sys`、`/proc`、`/dev` 并 fork 平台工具 | **阻断** | 换平台必改 Shell 源码；且跑在渲染线程上 |
| C2 | 启动路径（`frontend-session` 按文件名选前端 + `ld-linux` exec + `SDL_*` 环境） | **阻断** | 没有版本/能力协商，Shell 无法声明「我需要什么」 |
| C3 | 应用启动与游戏启动由 Shell 用 `systemd-run`/`heya-tool` 拼命令行 | 高 | 应用模型（进程/包/会话）属于平台，不属于 Shell |
| C4 | 输入框架（keyboardd）通过 `127.0.0.1:8787` 旁挂，Shell 内还自带一套 OSK | 高 | 两套键盘并存 |
| C5 | 目录布局 `/storage/*`、`/usr/share/pocketjs/*` | 中高 | Shell 的 Library 状态目录写死 |
| C6 | 服务开关（`rocknix-services` 11 个 key + `systemd` 单元名） | 中高 | BaseOS 侧只能靠 shim 模仿 |
| C7 | profile 三份且互相矛盾 | 中 | 只影响编译期事实，可以用一条校验挡住 |
| C8 | 终端行格式/桥接语法在仓库内已漂移 | 中 | 不修则所有逐帧比对不可信 |

---

## 10. 本审计的边界（没做的事）

- 没有在真机上运行任何命令；硬件结论全部标注来源。
- 没有验证 `PKT/` 产物与 `RNX` tracked 源码的构建可重现性（只证明了二者**不同**，没证明谁先谁后）。
- 没有审计 `inua` 与其他 `pocket-*` 之外的仓库。
- `RNX` 本地落后 `origin/main` 41 个提交，`origin/main` 上是否有更新版本的桥接实现**未审计**（`git show origin/main:...paths...` 只用于 `hello/main.tsx` 行数对比：593 行，与本地 350 行仍不同）。
