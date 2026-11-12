# RG34XX 故障与修复进度

更新日期：2026-11-12（JST）。这是本次实机调试的统一记录，后续验证继续更新本文件。

## 验收规则与连接方式

- **已修改、已测试、已部署、实机验收通过是不同状态**；未完成的环节不算关闭问题。
- 优先 USB ADB：`adb -s <device-serial> shell 'hostname; id'`。ADB 不可用或正在测试关闭时使用 Wi-Fi SSH，命令见 [AGENTS.md](../AGENTS.md)。
- 设备：RG34XX，hostname `rg34xx`，Wi-Fi `<device-lan-ip>`；PVE 将 USB `18d1:4e42` 直通一台 Debian 虚拟机。
- 当前自动关机和自动熄屏暂设为 `never`。这是调试缓解措施，不能作为功能验收通过的证据。
- 子智能体已按用户要求统一改用 `gpt-6-luna`；原智能体停止，已有代码保留。
- 运行时、前端包和辅助脚本的设备备份在 `/storage/pjs/debug-backup-20261112/`；系统脚本备份在 `/data/settings-repair-backup/`。调试截图、日志、构建产物保存在控制机 `/tmp/pjos-debug/` 和项目忽略目录 `work/`，不作为源码提交。

## 问题总表

| ID | 问题 | 已确认原因或证据 | 当前进度 | 尚需完成 |
| --- | --- | --- | --- | --- |
| V01 | 音量每滚一格先显示 100% | 单独 raw cset 和 SPK 开关无跳满；`aplay beep.wav` 触发 codec 电源渐变，原始读数 `25 → 63 → 25` | 稳定用户音量 getter、缓存、滚轮和桥接读取已改并部署；候选实机 30 次读取均为 40 | 最终界面连续滚轮验收；硬件瞬态仍存在，不宣称消除硬件渐变 |
| P01 | 自动熄屏后无法正常唤醒，看似死机 | 自动关屏也写 `panel.off`，旧 loop 误当手动关屏，跳过自身唤醒分支 | 代码/回归/部署及实机 10 秒关屏→输入唤醒通过，关屏期间 ADB 存活 | 最终系统信息版本整合后保持此行为；无需以关机代替熄屏 |
| P02 | 设置熄屏后约一分钟断线/关机 | 原配置 runtime `[power] timeout = 1m`；同时 BaseOS override 熄屏为 `1m`，与界面不一致 | 已禁用自动关机与关屏，设备持续可访问 | 不能仅凭旧 USB 断开断定死机；需在受控条件下分别验证关屏和关机 |
| P03 | 自动关机显示 `Unknown launcher action` | 设备 dispatcher 缺少对应统一/旧协议处理 | `SETTING autoPoweroff`、`STATE power_timeout`、`POWER` 已补齐；Rust 回归通过；运行时已部署 | 最终设置页显示与修改验收；真正关机/重开保存恢复流程尚未做 |
| P04 | 界面修改时间不生效 | `/storage/.config/baseos/screen-idle.conf` 覆盖 runtime 配置，UI 未同步 override | 新桥接读取有效值，写入同步已有 override；修复 INI 非最后段缺键时写错段；已部署 | 设置修改与守护实际超时保持一致的实机验证 |
| P05 | 畸形自动关机时间可能触发意外关机 | 旧 parser 对非法值可能退到 30 秒或算术错误退出 | 非法 power 时间安全回退禁用；回归通过；脚本已部署 | 随最终版本复核 |
| S01 | Wi-Fi 已连但右侧显示 `--` | 查询 ROCKNIX `wifi.enabled`，BaseOS shim 未实现 | 状态读取已修并部署；截图已见 Wi-Fi“开启”和 IP；后续统一 helper 已接线 | 最终开关功能复核；调试通道使用中不直接关闭 Wi-Fi |
| S02 | Wi-Fi 关闭后仍显示开启 | 只执行 `wpa_cli disconnect`，无线接口仍开启 | helper 改为接口 down/up 配合 reconnect；fixture 测试通过，已部署 | 真实 off/on 尚未测试，需保留 USB ADB 备援 |
| S03 | 蓝牙没有状态/开关，启动失败 | 缺 `SETTING` 接口；实机 rfkill blocked、无 hci0、H5 同步超时；旧锁阻止重试 | helper/桥接、rfkill unblock、失败锁恢复、异步启动与提示已修；启动脚本及 helper 已部署 | 蓝牙真实上电、扫描、连接验收；不能把可见开关当成蓝牙可用 |
| S04 | “蓝牙音频”显示 `--` | 原运行时无该设置接口 | helper 支持 bluealsa 状态/启停、启动确认和持久偏好；本轮 UI 实测显示真实值“关闭” | 实际蓝牙音频连接播放与重启保持状态待验收 |
| S05 | “耳机爆音修复”显示 `--` | 缺接口；驱动参数 `headphone_pop_fix` 为启动时参数，当前只读 | 本轮 UI 实测显示真实值“关闭”；修改保存启动配置并提示“重启后生效” | 重启后参数生效和耳机声音验收；用户此前说的是设置项名称，未据此确认真实耳机爆音已复现 |
| S06 | 主机名显示 `--` | 缺统一设置查询；实机真实值 `rg34xx` | 本轮 UI 实测显示 `rg34xx` | 已关闭显示项；未承诺主机名编辑功能 |
| S07 | 时间同步显示 `--` | 缺设置接口 | 本轮 UI 实测显示真实值“关闭”（当前未启用），无 `--` | 开关与真实同步成功、重启保持状态待验收 |
| I01 | 系统信息三页内容缺失 | 最新概览截图 CPU/内存/存储/系统/内核为 `--`，SSH/ADB 状态正常；Luna 已定位新版 dispatcher 缺少共用 `SYSTEM` arm | 已补全/测试/部署并逐页截图，三个页面已显示真实数据；本轮网络补丁版重新截图复核通过 | 无需继续；数据随负载变化属正常 |
| I02 | 系统网络页接口名显示 FOREVER | 基础 `LEVEL ip` 将 `ip -o` 最后一列当接口名，实际是地址 lifetime 的 forever | 接口列解析修复已并入本轮运行时；实机网络页显示 `WLAN0`、地址 `<device-lan-ip>` | 已关闭；与设备 `ip -o link` 输出一致 |
| U01 | 插线后 ADB 列表为空 | adbd 存在但 configfs UDC 未绑定；手动重跑 setup 恢复 | 已确认原智能体恢复有效；ADB 当前在线，root shell 正常 | 真实物理拔插验证 |
| U02 | ADB 开关拒绝关闭，也不能用来重新激活 | 原 `rocknix-services` 拒绝切换活动 ADB | 新 status/enable/disable、持久 `/data/no-adb`、统一设置和 legacy 适配已部署；SSH 下实测 off 后列表空，on 后 UDC configured，几秒后 ADB device 恢复 | 最终界面按钮端到端操作；快速多次切换与重启保持状态 |
| U03 | ADB 开启时插数据线应自动连接 | 原仅启动时 setup，无事件恢复；内核 hotplug 路径原缺 handler | 新内核事件 handler 已部署，受开关、设备角色、USB online、既有 ADB composition 控制；8 项 fixture 测试通过 | 真实拔插验证未做；vendor OTG 若选 host role，不能承诺强制转设备角色 |
| D01 | SD 写入失败、更新不落盘 | 内核 `FAT-fs: fat_free_clusters: deleting FAT entry beyond EOF`，mmcblk0p7 自动只读 | 已停前端、卸载两个挂载点、离线 `fsck.fat -a` 修复，再 `-n` 检查无待修错误，重新挂载 rw | 持续观察是否复发；恢复原挂载参数并在最终停止写入后再检查 |
| B01 | 新运行时部署后被旧版本覆盖 | `frontend-session` 每次启动会将 SYSTEM 配套运行时覆盖回卡上 | 本版同时更新 SYSTEM 与卡侧运行时，`sha256sum` 双双为 `140b465dcedb1458383e1561b92c9747cf222aa0dac074f9a8d92dcfef9fae7e`；替换前的旧运行时备份在 `/storage/pjs/debug-backup-net-e8ec6595/` | 已关闭 |
| B02 | 旧构建默认路径不存在 | 原 musl 脚本引用已不存在 worktree tar/profile；另外 `patch-runtime.py` 注入 `libc` 依赖却不更新 `Cargo.lock`，staging 每次从源码复制旧锁文件 | 已使用现有源码 staging 和 GNU 静态 arm64 交叉编译；本地构建入口在补丁后离线刷新锁文件再 `--locked` 构建，设备 `--check` 接受新旧包 | 固化可重现 musl 构建入口；静态 glibc 链接的 DNS/NSS 警告不能当完整兼容验收 |
| B03 | KANADE 桥接补丁生成 Rust 编译错误 | raw Python helper 对 Rust 字符串重复转义 | 两行转义修复，完整 helper Rust 编译与 JSON round-trip 回归通过；已整合运行时 | 随完整构建验证，不扩展 KANADE 功能范围 |
| B04 | 新运行时缺少旧网络/状态命令，可能使已有连接页和 USB 状态退化 | 对照前端调用发现新版基础 dispatcher 没有 `WIFI`、`BLUETOOTH` 和 `STATUS usb`，设置截图 USB 文件传输出现 `--` | 协议已并入本轮运行时并实机复核：设置页 USB 文件传输显示“关闭”、局域网发现“开启”、蓝牙音频“关闭”、耳机爆音修复“关闭”、主机名 `rg34xx`、时间同步“关闭”，无 `--` | 已关闭 UI 退化项；真实开关行为仍按 S02/S03/S04/S07 单独验收 |

## 已执行的关键实机验证

### 音量

1. 直接设置数字音量后连续采样保持目标值。
2. 单独播放提示音时捕获原始寄存器 `25 → 63 → 25`。
3. 候选稳定 getter 在同一播放过程中 30 次返回 40；硬件原始值仍短暂跳满。
4. 首轮 UI 截图已显示音量 40%，连续滚轮最终验收尚未完成。

### ADB

1. SSH 备用连接可用时调用 `usb-gadget-adb disable`；状态 off，adbd 停止，主机列表为空。
2. 通过 SSH 调用 `enable`；状态 on，adbd 重启，UDC 绑定 `5100000.udc-controller` 并 configured。
3. 主机经过重新枚举延迟后再次列出 serial `<device-serial>`，transport id 更新。
4. **这证明软件关闭/重新开启能恢复连接，不等同真实物理拔插已验收。**

### 自动熄屏与配置同步

1. 用与运行时同源的设备桥接探针执行 `SETTING timeout 10s`，读回 10s，确认 override 同步改为 10s，自动关机仍为 never。
2. 不输入等待 12 秒：panel level 为 0，日志 `panel off after 10s idle`；ADB 命令和 uptime 仍可读取，未挂起/关机。
3. 向输入设备注入按键后：panel level 恢复 50，`panel.off` 消失，日志 `panel on after input`。
4. 测试后通过同一桥接将 timeout 恢复 never，并确认两类自动策略均为 never。

### Luna 复核

- ADB 子智能体复核无明确阻塞问题；USB gadget 测试及 hotplug/service/settings 合计 18 项通过，未将物理拔插写为已验证。
- 音量/电源/settings 子智能体复核通过相关 Python 和 Go 测试；提醒真实硬件的蓝牙、NTP、Wi-Fi 启停不能由 fixture 测试替代。
- 已部署音量桥接探针再次采样：设置 45 时最初一次读到旧硬件值 44，之后连续返回 45，无瞬态 100；连续界面滚轮仍需最终验收。

### 后续开关与事件恢复实测

- 蓝牙：通过设置桥接请求开启后出现 hci0，日志 `Changing power on succeeded`，查询返回 on；测试后恢复 off。这不等于蓝牙耳机连接/音频播放已验收。
- 蓝牙音频：bluealsa 启动并有 PID；请求关闭后进程退出，持久偏好为 no。停止信号后短时间仍可能读到进程，需等实际退出再判断；真实蓝牙播放未测试。
- NTP：桥接 on 后持久状态 yes，supervisor 与 ntpd PID 存在；off 后恢复 no。已验证启停，不宣称外部服务器同步已经完成。
- ADB 事件路径：通过备用 SSH 解除 UDC 绑定并触发 power_supply change handler，等待 3 秒后重新绑定且 configured，主机 ADB device 恢复；未执行手动 enable 救援。这验证软件丢绑定事件恢复，仍不替代真实拔插。

### 系统信息三页实测

- 最终运行时 `sha256 140b465dcedb1458383e1561b92c9747cf222aa0dac074f9a8d92dcfef9fae7e` 已部署到
  `/usr/share/baseos/pocketjs/pocket-linux-kms` 与 `/storage/System/pocketjs/bin/pocket-linux-kms`，两处一致，
  设备 `--check` 准入通过。
- 概览页：CPU 使用率可读、内存约 127/997 MB、存储约 713 MB/27.5 GB，PJOS 1.5.3、内核 4.9.170 可见。
- 设备页：4 cores、1512 MHz、温度随负载变化（52.5 → 54.5C）、1.0 GB、720×480 可见。运行环境一行原为
  `PocketJS 0.15.0 ABI 12 build 1d166e1`，超出字段宽度把构建号截掉；改为 `0.15.0 · ABI 12 · 1d166e1`
  后完整显示，行标签已表明是运行环境。`tests/test-system-info-bridge.py` 的 fixture 期望同步更新。
- 网络页：状态“已连接”、接口 `WLAN0`、地址 `<device-lan-ip>`，I02 修复生效。
- Framebuffer 原始文件是 720×960 双缓冲，实际屏幕 720×480；`fb0/pan` 当前 `0,480`，另一半保留的旧游戏画面不是 UI 分屏。应按 pan 截取活动帧。

### 本轮构建入口修复

- `patch-runtime.py` 会给 `engine/guest-rquickjs/Cargo.toml` 注入 `libc` 依赖但不更新 `Cargo.lock`，
  而 staging 每次 rsync 又从源 checkout 复制旧锁文件，`cargo build --locked` 因此失败。
  `build-pocketjs-runtime-local.sh` 已在补丁后加入离线 `cargo metadata` 刷新锁文件，再执行 `--locked` 构建。
- `build-pocketjs-runtime-musl.sh` 与本地 GNU 构建入口的补丁列表一致（settings、system-info、network-bridge 都在）。

### 文件系统

- 修复前备份 `content_history.lpl` 和 `.config/pocketjs/last-active` 到控制机 `/tmp/pjos-debug/`。
- 检查发现这两个历史/活动记录的 cluster chain 已损坏，另有孤立簇及 dirty bit；修复会清空损坏记录并回收孤立簇，未据此声称游戏存档受损或已验证所有文件内容。
- 临时从 inittab 移除前端 respawn，停止卡上进程，卸载 `/storage` 和 `/mnt/sdcard` 后离线修复；随后恢复原 inittab 和前端启动。
- `fsck.fat -n` 修复后检查无额外修复报告；两处挂载当前均为 rw。

## 自动化验证入口

```sh
python3 tests/test-volume-state.py
(cd src/pjos-dpad && /usr/local/go/bin/go test ./...)
python3 tests/test-power-bridge.py
python3 tests/test-screen-idle.py
python3 tests/test-wifi-settings.py
python3 tests/test-baseos-settings.py
python3 tests/test-bluetooth-attach.py
python3 tests/test-kanade-bridge.py
python3 tests/test-usb-adb-hotplug.py
python3 tests/test-system-info-bridge.py
python3 tests/test-network-bridge.py
python3 tests/test-adb-service.py
sh tests/test-usb-gadget-adb.sh
git diff --check
```

前端仓 `~/development/pocketshell`：`bun test tests/setting-bridge.test.ts` 已通过 4 项；前端包与新运行时的设备 `--check` 已通过。2026-11-12 复核：上列 Python/Go/shell 测试全部 PASS，`git diff --check` 干净。

### 本轮可用的运行时构建路径

原 musl 构建的默认 worktree 已不存在。本轮新增 `build-pocketjs-runtime-local.sh` 支持显式指定现有源码和正式导出的 profile；不修改源码 checkout、不猜测 profile，也不重编 SYSTEM 镜像。

```sh
# 在 SDK 目录，使用与当前 pocketshell 相同的配置导出 profile。
bun tools/pocket.ts profile export \
  --config programs/pocketshell/pocket.runtime-config.ts \
  --target rocknix-h700-kms \
  --out ~/development/PJOS-LINUX/work/runtime-profile

# 回到 PJOS-LINUX。需已安装 Rust 1.98.1 arm64 GNU target、交叉 GCC、libclang，
# 并具备锁文件对应的 Cargo 缓存。产物为静态 GNU arm64，非 musl。
PJOS_RUNTIME_SOURCE="$HOME/development/rocknix/.runtime/pocketjs-kms/source" \
PJOS_PROFILE_RS="$PWD/work/runtime-profile/pocket_profile.rs" \
  ./build-pocketjs-runtime-local.sh
```

本轮正式导出 profile 与已安装包的 hash 相符。部署必须更新 `/usr/share/baseos/pocketjs/pocket-linux-kms` 和卡上 `System/pocketjs/bin/pocket-linux-kms`，并在重启前做设备 `--check`；只换卡上版本会被 `frontend-session` 覆盖。部署前备份两处文件，随后核对 hash；静态链接警告及真实设备验收仍单独记录。

## 下一步与关闭条件

1. 系统信息三页缺失数据修复已整合运行时并实机逐页截图复核（见上）。
2. 最终版本截图已完成：设置页 7/16、14/16 与系统信息 1–3 页，逐项对照真实设备值；网络页接口名与运行环境行已修正。
3. 受控验证自动关屏后 ADB/SSH 仍存活、按键可唤醒；再选择是否进行真实自动关机测试。
4. 验证 Wi-Fi、蓝牙、蓝牙音频、NTP、耳机修复各自真实行为，区分立即生效与重启生效。
5. 验证 ADB 界面开关和真实数据线拔插，保留 SSH 恢复通道。
6. 更新本表为实际结果，固定源码和构建命令；未验证项保留开放，不以测试通过代替硬件验收。当前固定哈希为 `140b465dcedb1458383e1561b92c9747cf222aa0dac074f9a8d92dcfef9fae7e`。

相关记录：[USB/OTG 设计](08-usb-adb-and-otg.md)、[ADB 恢复记录](24-rg34xx-adb-recovery.md)、[音频与空闲策略历史记录](23-rg34xx-gba-audio-and-idle-notes.md)。
