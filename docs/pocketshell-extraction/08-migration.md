# 08 — 分步迁移计划

> 阶段一交付物。每一步都能**单独合并**、**单独回滚**，并写明「对现有 launcher 行为零影响」的验证命令。
>
> 约束（issue）：「本阶段只允许新增 docs（+ 图表/schema 文件）。不改源码、不改 build、不改 overlay。」→ 本文描述的是**后续**阶段的步骤，本阶段不执行。
>
> 依赖：[01](01-audit.md) 的耦合清单、[02](02-repo-boundaries.md) 的边界、[03](03-platform-api.md)–[05](05-adapters.md) 的契约。

---

## 1. 迁移原则

| # | 原则 | 判据 |
|---|---|---|
| P1 | **先建契约，再动代码** | 任何一步若需要改 Shell 源码来「让契约成立」，说明契约还没定对 |
| P2 | **每一步都是双向可逆** | 回滚 = revert 该 PR；不允许「需要第二步才能撤销第一步」 |
| P3 | **零行为变化有可执行证据** | 每步给出命令 + 期望输出，不接受「看起来一样」 |
| P4 | **影子模式优先** | 新增路径与旧路径并存，用同一次运行对比两者结果，再切换 |
| P5 | **一次只动一个平台** | BaseOS → Rocknix → Android，前一个稳定后才动下一个 |
| P6 | **删干净** | 切换后旧路径、旧 shim、旧桥必须删除，不留双写（issue 的 clean cutover） |

P4 是本次迁移的核心手法：因为 Shell 今天已经能跑（BaseOS 上已验证，`PJOS docs/evidence/2026-10-30-baseos-first-boot/`），所以新路径可以**与旧路径同时运行**并比对输出。

---

## 2. 步骤总览

| 步 | 内容 | 仓库 | 风险 | 可独立合并 |
|---|---|---|---|---|
| M0 | 本设计文档集 | PJOS-LINUX（本 worktree） | 无 | ✓（已完成） |
| M1 | 契约仓骨架 + 词表 + 反泄漏 CI | 新仓 `pocket-platform-api` | 无（无消费者） | ✓ |
| M2 | Mock Adapter + L2 无头渲染 + Shell 在 mock 上跑通 | `pocket-shell`（新仓，从 rocknix 迁入 Shell 源码）+ api | 低 | ✓ |
| M3 | BaseOS Adapter（只读域）+ 影子对比 | PJOS-LINUX | 中（碰启动序） | ✓ |
| M4 | Rocknix Adapter（只读域）+ 影子对比 | rocknix | 中 | ✓ |
| M5 | Shell 切换到 Platform API（删旧桥） | `pocket-shell` | **高**（行为变化） | ✓ |
| M6 | Android Adapter（只读 + 触摸）→ M21 验证 | 新仓 / pocketjs 内 | 中 | ✓ |
| M7 | 写域（亮度/音量/无线/休眠/电源）逐域切换 | 三平台 | 中 | 逐域独立 |
| M8 | 删除旧物（`patch-runtime.py` 桥注入、compat shim、`pocketjs-sleep`） | 全部 | 中 | 逐项独立 |

**M1 与 M2 可以并行**（M2 依赖 M1 的类型，但可以先写 mock 再用 `any` 过渡——不推荐；建议 M1 先合）。

---

## 3. 每一步的详细设计

### M0 — 设计文档集（本阶段）

| 项 | 内容 |
|---|---|
| 产出 | `docs/pocketshell-extraction/01..08 + README.md` |
| 不碰 | 源码、build、overlay、任何其他仓 |
| 验证 | `git status --short` 为空；`git show --stat HEAD` 只含 `docs/pocketshell-extraction/` |
| 回滚 | revert 即可，无运行时影响 |

---

### M1 — 契约仓骨架

| 项 | 内容 |
|---|---|
| 新增 | `pocket-platform-api` 仓：`capabilities.ts`、`features.ts`、`errors.ts`、`types/*.ts`（九域）、`schema/*.json`、`fixtures/*.json`、`CAPABILITY_TO_POCKETJS` |
| 不碰 | 任何现有仓 |
| 已完成判据 | `bun test` 全绿；反泄漏 grep 零命中；每个错误码有 fixture |
| 验证命令 | `bun test`；`sh scripts/leak-check.sh`（应 exit 0） |
| 零影响依据 | 无消费者；不由任何构建引用 |

**风险**：词表设计错了要改主版本。缓解：M1 之后故意**不**发 1.0，先发 `0.x` 并在 M2 中允许破坏性调整；M5 之前冻结为 `api: 1`。

---

### M2 — Mock + L2 + Shell 上桌

| 项 | 内容 |
|---|---|
| 新增 | `pocket-shell` 仓：从 `RNX .../pocketjs-runtime/hello/**` 迁入 UI 源码（**保持逐字节相同**，先不改成调用 Platform API）；`dev/scenarios/*.json`；`MockAdapter`；L2 无头 runner |
| 关键手法 | 第一步**只搬不改**：Shell 仍在调用 `ui.__launcher`/`__pocketshell`/`__library`，但 mock 后端实现这三个桥（返回与真实平台一致的字符串） |
| 不碰 | rocknix、PJOS |
| 已完成判据 | 同一份 `hello/main.tsx`（搬迁后）在 L2 上渲染出的帧与「搬迁前构建产物」在**语义快照**上一致 |
| 验证命令 | 见 §4.1 |
| 零影响依据 | 所有产物只在 `pocket-shell` 仓内；rocknix 构建不引用它 |

**为什么先搬不改**：直接改成 Platform API 会同时引入「迁移」与「重构」两类风险，无法定位失败原因。这一步先证明「同一份源码可以离开 rocknix 构建并渲染」，再谈接口。

**这一小步必须解决的现实问题**：Shell 源码现在依赖 `bun tools/pocket.ts compile`（pinned 整棵 upstream）。搬出后需要：
- 一个 `pocketjs` 的 pin（版本 + 校验和）；
- 一个最小的本地编译路径（不需要 `bun install` 整棵树）；
- `pocket-shell` 只声明它真正 required 的 capability（现在是 `text.glyphs.baked` + `input.buttons`，见 `RNX .../hello/pocket.json:9-14`）。

---

### M3 — BaseOS Adapter（只读）

| 项 | 内容 |
|---|---|
| 新增 | `PJOS overlay/usr/sbin/baseos-adapter`（形态待定，见 05 §8 A3）+ 一个 `--probe` 模式：打印 `AdapterManifest` JSON 后退出 |
| 不碰 | `frontend-session` 的现有启动路径（**影子模式**：Adapter 只在被显式调用时运行） |
| 已完成判据 | 在真机上 `baseos-adapter --probe` 输出的 manifest 通过 Runtime 的六项校验；每个三态都有证据 |
| 验证命令 | 见 §4.2 |
| 零影响依据 | `frontend-session` 未改动一行；`inittab` 未改 |

**影子对比**（P4 的具体用法）：

```
旧路径：Shell 通过 __launcher("LEVEL\tbrightness") 得到 50
新路径：Adapter 的 display.getBrightness() 得到 50
断言：两者在 20 次采样里一致（或都明确失败）
```

这条对比必须在真机上做，因为 mock 无法证明 Adapter 正确。

**已知不确定项**：BaseOS 的亮度节点未确认（`docs/13` 实测无 `/sys/class/backlight`，有 `/sys/class/disp/disp/attr`）。Adapter 必须先把 `display.brightness` 报成 `unknown`，实测确认后再改 `yes`。**不允许先写 `yes` 再验证。**

---

### M4 — Rocknix Adapter（只读）

| 项 | 内容 |
|---|---|
| 新增 | `RNX projects/ROCKNIX/packages/apps/pocketjs-runtime/adapters/rocknix/**`（或独立包），实现只读域 |
| 复用 | `pocketshell-launcher.rs` 的**取值逻辑**（`/sys/class/backlight`、`/sys/class/power_supply`、`ip -o -4 addr`、`amixer`），搬进 Adapter，**Shell 侧的那份删除**（在 M5） |
| 不碰 | `pocketjs-kms.service`、`pocketjs-session` |
| 已完成判据 | 同 M3 的探针输出 + 一致性校验 |
| 验证命令 | 见 §4.3 |
| 零影响依据 | 新增目录；`package.mk` 未引用它 |

**关键决策点**：`pocketshell-launcher.rs` 在四个位置有四份不同实现（[01](01-audit.md) §7.1 的 V1–V4，动词集各不相同）。Adapter 必须选定一套（建议：以被编译进产物的 V3，324 行版本为行为基准），并在 `capability-evidence.md` 里写明其余三份的处置。

---

### M5 — Shell 切换到 Platform API

| 项 | 内容 |
|---|---|
| 改动 | `pocket-shell` 里所有 `ui.__launcher` / `ui.__library` / `ui.__pocketshell` 的调用点，改为 `pocket.platform.*` |
| 删除 | Shell 内的旧桥调用；`SERVICE`（服务开关，九域无此域——按 [05](05-adapters.md) §4.3 的判断删掉该 UI 区）；`LAUNCH`（改用 PocketJS 的 app 切换，或在九域之外另行设计） |
| 不碰 | 终端模型的字节语义（只改「谁持有 PTY」） |
| 已完成判据 | T2 全部三态矩阵通过；T3 golden 更新且差异逐条登记；调用记录断言证明「不可用时零调用」 |
| 验证命令 | 见 §4.4 |
| 零影响依据 | **没有了**——这是唯一一步**故意改变行为**的步骤（删掉服务开关等）。因此必须在 PR 描述里逐项列出「用户可见变化」 |

这一步是全局最危险的一步，因为它同时改变 Shell 与平台两侧。缓解：

1. 先只切**一个域**（建议 Display 的只读部分），合并、验证、再切下一个；
2. 每个域的切换都带「旧桥仍在」的兼容层，但兼容层只允许存在一个 PR 的周期；
3. 每切一域，跑一次 M3/M4 的影子对比。

---

### M6 — Android Adapter

| 项 | 内容 |
|---|---|
| 新增 | Android Adapter（Java），实现 Display/Input(facts)/Storage/Battery/Capability/Feature 的 MUST 部分；其余 `unsupported` |
| 构建 | 复用 `PKT/tools/android.ts` 的既有链路（`compileActivity`、`build-app`），**不新增构建系统** |
| 不碰 | `PocketActivity.java` 的渲染/输入路径（除新增 Adapter 的初始化调用） |
| 已完成判据 | 同一份 `pocket-shell.pocket` 在设备上启动，完成：进入主界面 → 点开一个 App 卡片 → 进设置页 → 返回 |
| 验证命令 | 见 §4.5 |
| 零影响依据 | 新的 profile（`m21-dev` 之类）与既有 `moto-g-play-dev`/`redmi-1s-dev` 并列，不改它们 |

**M21 的特别约束**（来自 `m21-baseos-assessment/README.md` 的事实边界）：

- 前提是设备已有可用 Android + 能安装 APK。**不需要**解锁、不需要 `fastboot boot`、不需要 Linux BSP。
- 如果连「安装并启动一个 APK」都做不到，M6 阻塞。这是**唯一**的 M21 前置条件，必须先确认。
- 屏幕旋转：`AndroidManifest.xml:27` 固定 `portrait`。M21 是竖屏设备，需确认 750×1334 的 plan 视口（不能用 360×800 假设）。

---

### M7 — 写域逐域切换

每个写操作独立成一个 PR，顺序按风险从低到高：

| 子步 | 域方法 | 风险 | 理由 |
|---|---|---|---|
| M7a | `display.setBrightness` | 低 | 失败只影响亮度 |
| M7b | `audio.setVolume` / `setMuted` | 低 | |
| M7c | `display.setOn` / `power.screenOff` | 中 | 屏幕黑了要有恢复路径 |
| M7d | `network.setWifiEnabled` | 中 | 断网后无法远程调试 |
| M7e | `power.setIdlePolicy` | 中 | 影响 `pocketjs-sleep` 的存废 |
| M7f | `power.suspend` / `reboot` / `shutdown` | 高 | 不可逆动作 |

每个子步的验证：**先旧后新**——旧实现执行一次，读回值；新实现执行一次，读回值；两者一致才算通过。对不可逆动作（M7f），先只做 `setAlarm/clearAlarm`（可逆），再单独评估 `suspend`。

---

### M8 — 删除旧物

| 删除项 | 前置条件 | 证据 |
|---|---|---|
| `scripts/patch-runtime.py` 的桥注入（`:34-52`） | M5 完成且 Shell 不再调 `__launcher`/`__library`/`__pocketshell` | `grep -r '__launcher\|__library\|__pocketshell' pocket-shell/` 零命中 |
| `pocketshell-launcher.rs` | M4/M5 | 同上 |
| `pocketshell-library.rs` | M5（Storage 域接管） | 同上 |
| BaseOS 的 compat shim（`docs/13` §3 提到的 `rocknix-services`/`heya-control`/`systemctl` 等价物） | M3 + M5 | `grep -r 'rocknix-' <shell>` 零命中 |
| `pocketjs-sleep`（Python） | M7e | Power 域的 `setIdlePolicy` 有真机证据 |
| `pocketshell-dev` 的 `#[path]` 引入（`tools/pocketshell-dev/src/main.rs:21-22`） | M2（dev host 改用 mock/API） | `grep '#\[path' tools/pocketshell-dev/src` 零命中 |
| `hello/` 的旧副本（`RNX .../pocketjs-runtime/hello/`） | M2（源码已在 `pocket-shell`） | rocknix 侧只剩包配方与 Adapter |

**每删除一项都要能回答**：「如果现在必须回滚到删除前的版本，怎么做？」——答案是 `git revert`，因此删除必须独立成 PR，不能与功能改动混在一起。

---

## 4. 验证命令

> 说明：本节命令是为**后续阶段**准备的。本阶段（M0）不执行它们；`[待建]` 标记的路径在 M1–M6 完成后才存在。凡引用现有路径的命令，已在本 worktree 里核对过文件存在性。

### 4.1 M2：Shell 在 mock 上渲染

**搬迁前后的一致性**（核心断言）：

```sh
# 基准：搬迁前，现有构建产物里已编译的 guest 源（存在性已核对）
ls build.ROCKNIX-H700.aarch64/build/pocketjs-runtime-*/apps/rocknix-h700/main.tsx   # [rocknix 仓]

# 新：搬迁后，pocket-shell 的同一份源码
# [待建] pocket-shell/src/main.tsx

# 语义快照对比（不是像素）
bun run dev:headless --scenario handheld-full --script dpad-nav.jsonl --frames 120 \
    --out /tmp/new --trace-only
bun run compat diff-trace /tmp/base-trace.json /tmp/new/trace.json
```

**期望**：`D1 = 100%`（纯状态）；可见元素差异必须空或逐条登记。

**单元层**：

```sh
cd pocket-shell && bun test          # T1
cd pocket-platform-api && bun test   # T0
```

**反泄漏**：

```sh
# [待建] pocket-shell/scripts/leak-check.sh
sh scripts/leak-check.sh   # 期望 exit 0，输出 0 命中
```

### 4.2 M3：BaseOS Adapter 探针（真机）

```sh
# 1. 推送到卡上（不刷镜像，沿用 docs/13 §8 的迭代方式）
adb push baseos-adapter /mnt/sdcard/System/bin/
adb shell chmod +x /mnt/sdcard/System/bin/baseos-adapter

# 2. 打印 manifest 并校验（校验器由 M1 提供）
adb shell /mnt/sdcard/System/bin/baseos-adapter --probe > /tmp/baseos-manifest.json
bun run -e 'import {validateManifest} from "pocket-platform-api"; console.log(validateManifest(await Bun.file("/tmp/baseos-manifest.json").json()))'

# 3. 三态证据（逐项对照 capability-evidence.md）
adb shell /mnt/sdcard/System/bin/baseos-adapter --probe --explain display.brightness
#   期望：value=unknown, reason="no /sys/class/backlight; /sys/class/disp/disp/attr present but unverified"

# 4. 影子对比：旧桥 vs 新 API（同一台机，同一时刻）
adb shell 'for i in 1 2 3 4 5; do echo "old=$(...)"; echo "new=$(...)"; sleep 1; done'
```

**零影响验证**（这一步最要紧）：

```sh
# 启动序未被触碰：inittab 与 frontend-session 的 git blob 必须与迁移前相同
git -C <pjos> diff --stat <base>..<head> -- overlay/etc/inittab overlay/usr/sbin/frontend-session
#   期望：无输出
# 真机行为：重启后仍进现有 launcher，抓帧与迁移前一致
adb shell 'cat /dev/fb0' > /tmp/after.raw   # docs/13 §3 M2 的抓帧法
```

### 4.3 M4：Rocknix Adapter 探针

```sh
# 包内构建（不整镜像）
cd <rocknix> && ./scripts/build pocketjs-runtime     # Makefile:107-108 的 package 目标
# 设备上
ssh <rocknix-device> '/storage/pocketshell/rocknix-adapter --probe' > /tmp/rnx-manifest.json
bun run -e '... validateManifest ...'

# 影子对比：与 Shell 现有桥相同的取值
ssh <rocknix-device> '/storage/pocketshell/rocknix-adapter --probe --explain battery.percent'
# 期望：与 PKT 版本 LEVEL\tbattery 的读数一致（同一时刻采样）
```

**零影响验证**：

```sh
# 只新增文件：package.mk 与 unit 文件必须无 diff
git -C <rocknix> diff --stat -- projects/ROCKNIX/packages/apps/pocketjs-runtime/package.mk \
                            projects/ROCKNIX/packages/apps/pocketjs-runtime/system.d/
#   期望：无输出
```

### 4.4 M5：Shell 切换后的回归

```sh
cd pocket-shell
bun test                       # T1 + T2（含三态矩阵）
bun run dev:headless --scenario unknown-heavy --script dpad-nav.jsonl --frames 60 --out /tmp/u
#   期望：无崩溃；PNG 中不出现 "unknown"/"--" 当数值
bun run dev:gate --assert-no-calls audio.setVolume --scenario handheld-min
#   期望：audio.output=no 时该方法从未被调用（T2 §4.3）
```

**行为变化清单**（PR 描述里必须逐项列出）：

| 变化 | 原因 | 用户可见 |
|---|---|---|
| 设置页不再有「服务开关」区 | 九域无服务管理 | 是 |
| 「打开应用」不再经 Shell 拼命令行 | 应用切换归 Runtime | 是（实现方式变，行为不变） |
| 亮度行在无背光设备上消失而非显示 `unknown` | [04](04-capability-feature.md) §6.2 | 是（更好的行为） |

### 4.5 M6：Android / M21

```sh
# 构建（复用既有链路，不新增构建系统）
bun tools/android.ts --profile=<m21-profile> build-app --pocket=pocket-shell.pocket --out=shell.apk
# 安装并启动
adb install -r shell.apk
adb shell am start -n <pkg>/dev.pocketnexus.android.PocketActivity
# 取回运行时回执（既有机制）
adb shell run-as <pkg> cat files/runtime.txt
# 抓帧（既有能力：GLES2 表面 + 帧计数）
adb exec-out screencap -p > /tmp/m21-home.png
```

**最小验收**（issue 的目标）：UI / 触摸 / 硬件按键 / Library / Music 可验证。

| 项 | 命令 | 期望 |
|---|---|---|
| UI | 上述 screencap | 主界面可见，布局与 360×800 golden 一致 |
| 触摸 | `adb shell input tap <x> <y>` | 卡片焦点移动 |
| 硬件按键 | `adb shell input keyevent 19/20/22/21/23` | 对应 `UP/DOWN/RIGHT/LEFT/CIRCLE`（`platforms/android/src/input.c:21-32`） |
| Library | 进入 Library 页 | 列出 MediaStore 内容（或明确「本平台无内容区」） |
| Music | 进入媒体卡 | 打开对应 App（见下方未完成项） |

**已知缺口（不假装完成）**：Android 上没有 `audio.pcm`（scout 全量 grep 零命中），所以「Music App 播放音频」在 Android 上需要 `AudioTrack` 实现，属于 M6 之后的独立任务，不在本迁移的壳层范围内。Design 上应把这条写进「未完成」，而不是标成已支持。

### 4.6 跨平台一致性

```sh
# [待建]
bun run compat gen --out /tmp/compat
# 三台设备各跑一次，产出 trace + 抓帧
bun run compat diff /tmp/compat/baseos /tmp/compat/rocknix
bun run compat diff /tmp/compat/rocknix /tmp/compat/android
#   期望：D1 = 100%；差异逐条落台账
```

---

## 5. 每步的「零影响」总表

| 步 | 不碰的文件 | 验证 |
|---|---|---|
| M1 | 所有现有仓 | `git -C <每个仓> status --short` 为空 |
| M2 | `RNX package.mk`、`system.d/`、`hello/` | `git diff --stat` 无输出 |
| M3 | `PJOS overlay/etc/inittab`、`overlay/usr/sbin/frontend-session`、`overlay/etc/init.d/rcS` | 同上；真机重启后抓帧对比 |
| M4 | `RNX package.mk`、`system.d/` | 同上 |
| M5 | 三个平台的启动序与单元 | 只在 `pocket-shell` 内改；平台侧零 diff |
| M6 | `PKT/programs/android/app/src/.../PocketActivity.java` 的渲染/输入路径 | `git diff` 只含 Adapter 初始化调用 |
| M7 | 逐域 | 每域一次读回对比 |
| M8 | — | 每项独立 PR，可 revert |

---

## 6. 风险与缓解

| 风险 | 触发信号 | 缓解 |
|---|---|---|
| Shell 源码搬出后无法在开发机构建（缺 pocketjs 工具链） | M2 卡住 | 先做「pinned wasm + 最小编译器」；见 [06](06-local-dev.md) §7 |
| `hello/` 与产物不一致导致「零行为变化」基线错 | M2 的 D1 不为 100% | 先拍板 D1（README §5），把 baseline 钉死在**产物**上 |
| BaseOS 亮度节点未确认 | M3 的三态只能给 `unknown` | 不允许先写 `yes`；保留 `unknown` 直到真机实测 |
| Rocknix 桥有四份实现（V1–V4） | Adapter 与 Shell 取值不一致 | M4 的探针逐项对比；`capability-evidence.md` 写明基准 |
| M5 删掉服务开关引发现有用户抱怨 | PR 评审 | 先在一个 release 里把它移到 PocketApps（`pocket-settings` 已有能力模型），再删 |
| Android 上音频不可用被误报为「Music 已支持」 | 验收表 | §4.5 末尾的「已知缺口」必须进 release notes |
| 跨仓 pin 漂移（pocketjs 升级） | `patch-runtime.py` 的 anchor 再次 `SystemExit` | M8 删除 patch；在此之前把 patch 面积压到 1 个注册点 |

---

## 7. 里程碑与顺序建议

```
M0 [已完成] 设计文档
      │
M1 契约仓 ──┐
      │      │
M2 Mock+L2 ──┴─► M3 BaseOS Adapter ─► M4 Rocknix Adapter ─► M5 Shell 切换 ─► M7 写域
                                                        └─► M6 Android Adapter（可并行）
                                                                              │
                                                                    M8 删除旧物
```

M6 与 M3/M4 无依赖，可并行——它是**唯一不依赖两个现网平台**的验证路径，因此建议**尽早开始**（issue 把 M21 列为重点目标）。

---

## 8. 待定

| id | 问题 |
|---|---|
| M-1 | M6 的 M21 前置（能否安装 APK）未确认。若不能，Android 分支整体阻塞，需要另一台 Android 设备做验证 |
| M-2 | M5 的服务开关 UI 移交给谁（`pocket-settings` 还是直接删除） |
| M-3 | M7e 的 `pocketjs-sleep` 删除时机（它与 BaseOS 无关，只在 Rocknix 上存在） |
| M-4 | 是否需要为每个 Adapter 单独的发版节奏（Rocknix Adapter 随 SYSTEM 走，BaseOS Adapter 随镜像走，Android Adapter 随 APK 走） |
