# RG34XX GBA 音频修复与电源/空闲行为说明（2026-11-08）

本文记录两件事：
1. 另一台电脑上已更新、在本机拉取并继续修复的 PJOS GBA/RetroArch 音频问题；
2. 当前 PJOS/BaseOS 代码里“自动休眠/自动关机/自动关屏”的实际设置结论。

## 1. 本机已拉取的 PJOS 仓库

以下仓库已执行 `git pull --ff-only origin <default-branch>` 并确认与远端一致：

| 仓库 | 分支 | 结果 |
|---|---|---|
| `~/development/PJOS-LINUX` | `main` | `eeeafa5..99e5637` 已拉取；随后本机提交并推送 `76e2f50` |
| `~/.cache/pjos-source` | `main` | `dc4a6ba..99e5637` 已拉取 |
| `~/pjos-website` | `main` | `8a040b0..914cb9c` 已拉取 |
| `~/development/pocket-verify/repos/pjos-keyboard` | `main` | 已最新 |
| `~/development/pocket-verify/repos/pjos-website` | `main` | 已最新 |
| `~/development/pocketjs-baseos-frontend` | `master` | 已最新 |

> 明天在另一台电脑上，至少对 `~/development/PJOS-LINUX`（或你实际使用的工作副本）执行 `git pull --ff-only` 即可拿到本次音频修复提交 `76e2f50`。

## 2. RG34XX GBA 模拟器无声：原因与修复

### 原因（修复前仓库状态）

`docs/22-retroarch-gba.md` 与 `overlay/.../retroarch/driver.cfg` 显示：首次设备运行中，同步 `alsa` 驱动曾报告异常的 ALSA period/buffer（如 `Buffer size: …548005464848 frames`），导致音频线程阻塞整帧循环，表现为 **RetroArch 0% CPU、画面冻结**。为避免卡死，`driver.cfg` 当时设置了：

- `audio_driver = "null"`（游戏可运行/渲染，但无声音）

### 参考

Rocknix 的 H700 RetroArch 配置使用线程化音频驱动，避免同步 ALSA 在渲染线程上阻塞：

- `~/development/rocknix/projects/ROCKNIX/packages/emulators/libretro/retroarch/sources/H700/retroarch.cfg`
  - `audio_driver = "alsathread"`
  - `audio_out_rate = "44100"`
  - `audio_sync = "true"`
  - rate control/resampler 等参数

### 本次修复（已提交并推送）

提交：`76e2f50 fix(retroarch): enable RG34XX GBA audio via alsathread`（`PJOS-LINUX/main`）

改动文件：
- `overlay/usr/share/pocketshell/System/compat/share/retroarch/driver.cfg`
- `overlay/usr/share/pocketshell/System/compat/share/retroarch/retroarch.cfg`
- `docs/22-retroarch-gba.md`

关键行为：
- `driver.cfg` 由 `pocket-game-play` 通过 `--appendconfig /storage/System/compat/share/retroarch/driver.cfg` 加载，**追加配置覆盖 base config**。
- 将 GBA/RetroArch 设备覆盖从 `audio_driver = "null"` 改为 `audio_driver = "alsathread"`，并加入 Rocknix H700 风格参数：
  - `audio_enable = "true"`
  - `audio_sync = "true"`
  - `audio_out_rate = "44100"`
  - `audio_latency = "64"`
  - `audio_block_frames = "0"`
  - `audio_max_timing_skew = "0.049999"`
  - `audio_rate_control = "true"`
  - `audio_rate_control_delta = "0.004999"`
  - `audio_resampler = "sinc"`
  - `audio_resampler_quality = "2"`

设计意图：音频处理移出渲染线程；即使 ALSA 报告异常 buffer/period，也不应再直接卡死画面循环。

### 已做的本地验证

本机为 Debian VM，**没有 RG34XX 真机、没有已生成的 `compat/lib/retroarch` 设备二进制、无可直接运行的 H700 mali-fbdev+SDL2+ALSA 模拟环境**，因此未做真实“模拟器内 GBA 有声播放”验证。已完成：
- `bash -n overlay/usr/share/pocketshell/System/compat/bin/pocket-game-play` 语法检查通过。
- 模拟 RetroArch `--config` + `--appendconfig` 合并（后者覆盖前者）确认最终生效值为 `audio_driver=alsathread` 且关键音频参数已覆盖。

### 设备侧验证建议（拉取 `76e2f50` 后）

1. 将更新后的 `System/compat/share/retroarch/driver.cfg`（及相关 compat 内容，按你的镜像/卡部署流程）部署到 RG34XX。
2. 启动 GBA ROM，确认：画面正常推进、CPU 非 0%、扬声器有声音。
3. 若再次出现“画面冻结 + 0% CPU”，用 `retroarch --verbose` 抓 ALSA 相关日志；再评估回退/调整为 `alsa`（带安全参数）或 `sdl2` 音频后端，但必须先确认不会阻塞渲染。

## 3. 电源/空闲设置检查结论（PJOS/BaseOS 代码）

### 有：自动关屏（只关背光）

存在自动关屏守护，不是休眠/关机：

- 脚本：`overlay/usr/sbin/baseos-screen-idle`
- 文档：`docs/18-screen-idle.md`、`docs/18-hotkeys-sleep-and-power.md`
- 启动：`overlay/etc/init.d/rcS` 在非 USB 存储维护模式下后台启动

行为：
- **无输入达到超时后关闭面板背光**；下一次任意按键/输入恢复亮度。
- **只动背光，不挂起、不停服务、不卸载存储、不降频**。播放、下载、前端渲染在黑屏期间理论上继续运行。
- 默认超时 **30 秒**（无配置时）。
- 可配置：`/storage/.config/baseos/screen-idle.conf` 的 `timeout = ...`，或 `/storage/.config/pocketjs/runtime.conf` `[sleep] timeout = ...`；支持 `never/off/none/10s/30s/1m/5m/15m/30m/1h`。
- 电源键短按由 `baseos-hotkeys`/`baseos-panel` 处理为屏幕关/开；长按（约 2s）触发显式关机动作（代码路径 `baseos-poweroff`）。`SELECT+START` 长按用于退出当前前端/模拟器回到启动器，不是系统关机。

### 没有：按空闲时间自动休眠 / 自动关机

在当前 `PJOS-LINUX` 代码中，**未发现“按空闲时间自动 suspend/hibernate/自动关机”的设置或守护逻辑**：

- 无 systemd/logind 自动睡眠策略（BaseOS 不是 systemd 体系；`baseos-hotkeys` 代码注释明确写明没有 logind，且内核 suspend 不可靠）。
- 无基于空闲时间调用关机/重启/suspend 的脚本或服务。
- 关机/重启是显式动作路径（电源键长按、维护/更新流程或手动调用），不是空闲定时器。

### 对“昨晚放一晚上，早上电影都没了”的排查含义

如果现象发生在 PJOS/RG34XX 设备上，按当前代码**不太像“自动进入休眠/自动关机”导致**（因为没有这类自动策略）。更可能的方向包括：
- 设备实际耗尽电池后断电（自动关屏仍在耗电；音频/播放/后台任务也可能继续耗电）。
- 手动/长按电源键触发关机、异常重启或崩溃。
- 播放器/前端状态未持久化，断电后“播放进度/正在看的电影状态”消失（看起来像“没了”）。
- 若是文件真的从存储消失，则需要单独检查存储/挂载/应用清理逻辑，不属于自动休眠设置。

建议在设备上复现前后收集：电源/充电状态、`/tmp/baseos-screen-idle.log`、`/tmp/baseos-hotkeys.log`、前端/播放器日志、是否存在意外 reboot/关机痕迹，以及存储挂载状态。


## 4. 自动关机 + 关机前保存状态（本次新增）

### 自动关机（按空闲时间，可在设置中选择）
- `overlay/usr/sbin/baseos-screen-idle` 新增自动关机逻辑：使用与息屏相同的输入空闲 stamp；达到配置的空闲时长后 `sync`，优先调用 `/usr/sbin/baseos-poweroff`（失败才回退到 `/sbin/poweroff`）。
- 默认 **Never**（不自动关机）。
- 配置优先级：
  - `/storage/.config/baseos/screen-idle.conf`：`auto_stop_timeout = never|1m|5m|10m|15m|30m|1h|2h`（兼容 `poweroff_timeout`）
  - `/storage/.config/pocketjs/runtime.conf`：`[power]` 段 `timeout = never|...`
- 启动器设置页（`pocketshell`）新增 “Auto Power Off/自动关机/自動電源オフ” 枚举行；通过 bridge `STATE	power_timeout` 读取、`POWER	<timeout>` 写入（兼容统一 `SETTING` 协议）。

### 关机前保存状态（best-effort）
- `overlay/usr/sbin/baseos-save-state`：在有意关机前记录恢复标记到 `/storage/.config/pocketjs/resume.state`（`kind=rom|app`, `target=...`）。若检测到 RetroArch 运行，尝试通过网络命令端口 `127.0.0.1:55355` 发送 `SAVE_STATE`（需 RetroArch 启用 network cmd）；失败不阻塞关机。
- `overlay/usr/sbin/baseos-poweroff` 在设置关机 marker 前调用 `baseos-save-state`（best-effort）。
- `pocket-game-play` 启动 ROM 时写 `/storage/.config/pocketjs/last-active` 与 `/tmp/pocketjs-current-rom`，供保存/恢复使用。
- `launch_frontend.sh`：启动安装的 `.pocket` app 时写 `last-active`；开机/前端启动时若存在 `resume.state` 且没有 `active` marker，则一次性转换为 `active` 并删除 `resume.state`，从而自动打开上次记录的 ROM/app。
- RetroArch 配置（`compat/share/retroarch/retroarch.cfg`）已启用 `savestate_auto_save=true`、`savestate_auto_load=true`、`network_cmd_enable=true`（localhost 55355），作为 ROM 进度恢复的基础能力。

### 验证状态
- 已做：shell/python 脚本语法检查、bridge/work 脚本补丁幂等应用检查、配置/脚本改动已纳入 `PJOS-LINUX` 待提交；`pocketshell` 设置/UI 变更已提交并推送 `1bac55a..46094af`。
- 未做（当前环境限制）：RG34XX 真机上的自动关机触发、RetroArch savestate 实际写入/恢复、关机后自动重开 ROM/app 的端到端验证（本机无 RG34XX 真机/可运行的 H700 模拟环境，且卡已拔下）。需要在设备上按“设置超时→空闲等待→关机/重启→确认自动恢复”流程实测。
