# 06 — 本地开发模式

> 阶段一交付物。目标（issue 设计目标 1、2）：**无需构建完整 BaseOS，也无需设备，开发机直接跑 Shell**。
>
> 前提：[03](03-platform-api.md) 的接口；[05](05-adapters.md) 的 Adapter 契约。测试矩阵在 [07](07-mock-and-tests.md)。

---

## 1. 今天为什么做不到

| 障碍 | 证据 |
|---|---|
| Shell 源码只能在 pinned pocketjs 树里编（`bun tools/pocket.ts compile` 需要整棵 upstream + `bun install`） | `RNX .../pocketjs-runtime/package.mk:24-44` |
| 编出来的产物需要真实宿主：`pocket-linux-kms` 要 DRM 或 fbdev | `PKT/programs/linux-kms/src/main.rs:193-206` |
| 唯一的「无设备」路径是 `--headless`，但它**不渲染**（只跑逻辑 tick） | 同上 `:47` 帮助文本 |
| 想看到画面必须：adb push → 起运行时 → `cat /dev/fb0` 抓帧 | `PJOS docs/13-pocketjs-on-baseos.md` §8、`docs/evidence/2026-10-30-baseos-first-boot/README.md` |
| 唯一现成的浏览器 harness 用的是**真实设备源码的副本**，且明确不是 parity 证据 | `RNX .../hello/browser-preview.html`（审计引 `docs/pocketshell-platform/audit.md` §9 表：`hello/browser-preview.html` is explicitly demo data and does not prove parity at `:18-29`） |
| dev host 通过 `#[path]` 直接引入设备源码，因此只能活在 rocknix 仓里 | `RNX tools/pocketshell-dev/src/main.rs:21-22` |

结论：今天「开发机直接跑」只有在**桌面 Linux + 真实 X/Wayland + wgpu** 的 `programs/desktop` 宿主上才勉强成立（`PKT/docs/BACKENDS.md:34-50`），而它连截图都没有（scout 验证：`programs/desktop` 无 `--screenshot`，`tools/headless-chrome.ts:9` 硬编码 macOS Chrome 路径）。

---

## 2. 目标形态：四层可独立运行

```
L0 纯模型         Shell 的 reducer/布局/终端解析     bun test        ← 零依赖
L1 Mock 后端      Platform API 的假实现              bun test / node   ← 零设备
L2 无头渲染       真正的 pocketjs core + wasm         bun run         ← 出像素，不出窗口
L3 桌面窗口       winit/wgpu 或浏览器                bun run dev     ← 人看
```

每一层都能单独成为「完成一次改动」的验证手段。**L2 是新增的、也是最重要的一层**：它把「有像素」与「有窗口」解耦。

---

## 3. L0：纯模型

### 3.1 拆分原则

Shell 里可以「纯函数化」的部分必须纯函数化，且**不 import 任何 Platform API**：

| 模块 | 输入 → 输出 | 今天的位置 |
|---|---|---|
| 终端屏幕模型 | 字节流 → 行/光标/dirty rows | `RNX scripts/pocketshell-terminal.rs:673-732`（`L`/`C` 行生成）+ 解析器 |
| 列表/网格导航 | (选择索引, 方向, 条目数) → 新索引 | `hello/main.tsx` 的 `moveLauncher`/`moveInputSelection`（纯逻辑，无 IO） |
| 文案与本地化 | (locale, key) → 字符串 | `PKT/apps/rocknix-h700/launcher-localization.ts` |
| 阅读进度计算 | (文件大小, 行号) → 百分比 | `hello/library-model.ts` 的 `progressAt` |
| 时间/节流 | (now, last, interval) → 是否触发 | `hello/main.tsx` 的 `onChange` 轮询 |

### 3.2 约束

| 规则 | 判据 |
|---|---|
| L0 模块**不得** import `pocket.platform`、`getOps()`、`fetch`、`Date.now()`（时间从参数传入） | `grep -E` 上述四个符号，零命中 |
| L0 模块**不得**出现平台名/路径 | 03 §5 的 grep 同样适用 |
| 每个 L0 模块必须有测试，且测试不启动任何进程、不开任何端口 | `bun test` 只跑 `.test.ts` |

L0 的价值：终端解析器这类「今天必须上设备才能验」的逻辑（`docs/13` 的 M1/M2 里程碑全是设备步骤）变成 `bun test` 一秒钟的事。

---

## 4. L1：Mock 后端

### 4.1 形态

一份 `MockAdapter` 实现全部九个域，行为**由场景文件驱动**：

```
pocket-shell/
  dev/
    scenarios/
      handheld-min.json        # 只有 MUST 域，其余 unsupported
      handheld-full.json       # 全 yes/supported
      unknown-heavy.json       # 大量 unknown（验证 UI 不崩）
      android-m21.json         # 按 §5.4 的事实边界
      no-storage.json          # storage.user_content = no
      slow-io.json             # 每个调用 200ms 延迟（验证 loading 态）
      failing.json             # 指定方法返回各种 PlatformError
    inputs/
      dpad-nav.jsonl           # 输入脚本（见 §6）
      touch-scroll.jsonl
    frames/
      baseline/                # golden 帧（PNG）
```

场景 schema（与 `limits` 同源，便于互相校验）：

```jsonc
{
  "manifest": {
    "api": 1,
    "adapter": "mock",
    "capabilities": { "wifi": "yes", "touch": "no", "vibration": "no", "hdmi": "no" },
    "features": { "display.rotation": "unsupported", "power.suspend": "supported" },
    "limits": { "maxReadBytes": 16384, "maxScanEntries": 200, "maxTextSessions": 1, "maxSubscriptions": 32 }
  },
  "display": { "logical": [360, 240], "physical": [720, 480], "density": 2, "rotationDeg": 0,
               "presentations": ["native", "integer-fit"], "external": false },
  "battery": { "percent": 87, "charging": true, "source": "ac", "timeRemainingSec": null,
               "temperatureC": 41, "healthPercent": null },
  "audio": { "volume": 60, "muted": false, "output": "speaker", "volumeControllable": true },
  "network": { "wifi": { "enabled": true, "connected": true, "ssid": "lab", "ipv4": "203.0.113.10",
                          "signalPercent": 72 },
               "bluetooth": { "enabled": false, "pairedCount": 0, "connectedCount": 0 } },
  "storage": { "collections": ["documents","books"],
               "trees": { "documents": ["a.md","sub/b.txt"], "books": ["c.epub"] } },
  "power": { "idlePolicy": { "screenOffMs": 300000, "suspendMs": 1800000 },
             "suspend": "supported", "rtcAlarm": null },
  "input": { "mode": "dpad", "analogSticks": 0, "osk": "unsupported" },
  "faults": [ { "method": "audio.setVolume", "error": "unavailable", "retryable": true, "times": 2 } ]
}
```

### 4.2 三条硬要求

| # | 要求 | 理由 |
|---|---|---|
| M1 | Mock 必须能**模拟三态的全部组合**，包括「`wifi: yes` 但 `network.wifi_join: unsupported`」这类派生矛盾 | 真实设备上这种组合很常见（只有 BLE 无 A2DP） |
| M2 | Mock 的返回值必须过**同一套** Runtime 校验（§5.3 的六项） | 否则 mock 会放任 Shell 依赖非法数据 |
| M3 | Mock 的 `adapter` 字段必须是 `"mock"`，且 Shell 类型上不可见 | 防止 Shell 里出现 `if (mock) …` |

### 4.3 可复现性

- 所有值**确定**：无随机、无 `Date.now()`；时间由 Runtime 的单调时钟注入，起点固定为 0。
- 同一个场景 + 同一份输入脚本 → 逐字节相同的帧（这是 [07](07-mock-and-tests.md) 的 golden 前提）。
- 场景文件进版本控制；帧进版本控制（PNG，与 `PKT/tests/golden.ts:1-20,93-190` 的既有做法一致）。

---

## 5. L2：无头渲染（新增能力）

### 5.1 要解决的问题

pocketjs 已有两个无头路径，但都不满足「Shell 本地开发」：

| 现有路径 | 能力 | 缺什么 |
|---|---|---|
| `--headless`（`PKT/programs/linux-kms/src/main.rs:47`） | 跑 N 个逻辑 tick，不渲染 | 出不了像素 |
| `sim`（`PKT/programs/sim/sim.ts:1-25` 的宪章，`:99-108` 的 `fnv1a`，`:416-422` 的 `SimPixels`） | 虚拟时钟 + 逐帧 FNV 哈希 + 最终 RGBA | 需要构造 `script`，且没有「人看」的形态 |
| `tests/golden.ts`（`:93-190`） | 同 HostOps + 脚本输入 → 字节精确 PNG | 面向 CI golden，不是开发者循环 |
| web/wasm（`PKT/platforms/web/wasm-ops.js:20-26` 造实例，`:130-137` 的 `capture(scale,mode)`，`:198-199` 的 5 种 render 形态） | 软件栅格化，能 `capture` 出像素 | 需要浏览器或 wasm 宿主 |

结论：**L2 = 「wasm core + 文件系统里的帧」**，不需要浏览器：

```
bun run dev:headless --scenario handheld-full --script dpad-nav.jsonl --frames 120 --out /tmp/frames
→ /tmp/frames/0000.png … /tmp/frames/0119.png
→ /tmp/frames/trace.json      # 每帧的 FNV 哈希、当前焦点、可见节点数
```

实现要点（设计，不实现）：

1. 用 `platforms/web/pocketjs.wasm` + `wasm-ops.js` 的 `createWasmUi`（`PKT/apps/rocknix-h700/launcher-smoke.ts:5` 已有先例：直接 `Bun.file(...).arrayBuffer()` 载入 wasm，注入一个 `Proxy` 的 ops，再用 `eval` 跑编译产物）。
2. 注入的 ops 里，`__launcher` 一类的旧桥**替换为** Platform API 的 mock 后端（不再需要 `calls` 数组）。
3. 每帧 `wasm.render()` → `encodePNG`（`PKT/tools/png.ts:1-4`）。
4. 不引入窗口系统、不引入 GPU。

### 5.2 帧的可信度

| 保证 | 不保证 |
|---|---|
| 同一台机器上逐字节可复现 | 跨机器（float 差异）——用哈希比对时要限定范围 |
| 与真实设备**布局几何**一致（同一 profile、同一逻辑视口、同一字体 atlas） | 与设备**像素**一致（设备是 GPU 合成，桌面是软件栅格） |
| 能发现「少一个元素」「焦点落错」 | 能发现「设备上颜色偏了」 |

这与 pocketjs 自己的立场一致：软件栅格是 byte-deterministic，GPU 后端「preserve DrawList geometry and painter order; blending, filtering and triangle-edge rounding can differ」（`PKT/docs/BACKENDS.md:20-27`）。因此 **golden 只能订在 L2**，设备上只做抽样抓帧（见 07 §6）。

### 5.3 与真实 Adapter 的差距必须被显式记录

L2 用的是 mock 的 Display/Input，所以它**不能**证明：

- 设备上的触摸坐标换算（Android 的 surface 原点相减，`PocketActivity.java:153-184`）
- 设备上的按键映射（evdev → pad mask，`platforms/android/src/input.c:21-32`）
- 设备上的帧率（`PKT/docs/ANDROID.md:243-246` 记录了 Redmi 1S 的实测 `tick_us` 1600–2000、`render_us` 1500–1900、`interval_us` 16400–17700）

这些必须靠 07 §6 的「设备抽样」补，且写进验收报告。

---

## 6. 输入：假设备与录制回放

### 6.1 输入脚本格式（一次定义，三处复用）

```jsonl
{"frame":0,"buttons":0}
{"frame":10,"buttons":16}          // UP down
{"frame":13,"buttons":0}           // UP up
{"frame":20,"touches":[{"id":1,"x":180,"y":120}],"surfaces":[0]}
{"frame":24,"touches":[]}
{"frame":30,"text":{"kind":"commit","text":"hello"}}
{"frame":40,"analog":{"x":128,"y":40}}
{"expect":{"focus":"row-3"}}
```

- `buttons` 用 PocketJS 的 `BTN` 位（`PKT/contracts/spec/spec.ts:1549-1564`），不是平台键码。这是关键：**输入脚本与平台无关**。
- `text` 用 `TextEventRecord` 的形状（`PKT/framework/src/text-input.ts:27-33`），与真实宿主交付的第九个 frame 参数一致。
- `expect` 由 Shell 暴露一个可查询的「当前焦点/当前页」状态（设计上要求 Shell 有一个 `debugState()` 导出，仅测试构建启用）。

### 6.2 录制

三种来源都能产生同一种 `.jsonl`：

| 来源 | 方式 | 用途 |
|---|---|---|
| 手写 | 直接写 JSONL | 小场景 |
| 设备录制 | 在 Adapter 上加一个「按键/触摸 → JSONL」的旁路输出（仅调试构建） | 复现现场问题 |
| 既有资产 | `RNX tools/pocketshell-dev/recordings/*.log`（`ls-color.log`、`top-session.log`，格式为 `ms\thex`，见 `src/replay.rs:3-5,36-67`）转换 | 复用已有终端会话 |

**回放必须在 L1（mock）与 L2（无头）上产生相同结果**。若不同，说明某处依赖了真实时钟或真实 IO——这是一个应当修复的 bug，不是「mock 不精确」。

### 6.3 假显示帧（录制回放显示）

「录制回放显示帧」在 issue 里被列为本地开发目标之一。它的两个用途：

1. **回归**：golden 帧（L2）。
2. **演示/评审**：把设备抓帧串成动画，在没有设备时做 UI 评审。

设备抓帧的方法已有先例：BaseOS 上 `cat /dev/fb0` → PNG（`PJOS docs/evidence/2026-10-30-baseos-first-boot/README.md`，720×480×32）；Rocknix 上有 DRM plane 抓取（`RNX tools/pocketshell-mirror/capture.c:31-50`，输出 PPM `P6`）。两者产物都应是**同一份 PNG 序列格式**，并带一个 `manifest.json`（profile、设备、固件版本、抓帧命令），否则无法比较。

---

## 7. 开发者循环（目标：秒级）

| 改动类型 | 循环 | 目标耗时 | 今天的等价步骤 |
|---|---|---:|---|
| 纯模型 | `bun test dev/` | < 2s | 无（只能上设备） |
| Shell UI 布局 | L2 无头 → 看 PNG | < 10s | `package.mk` 整包构建 + adb push（`docs/13` §8） |
| Shell 交互 | L2 + 输入脚本 | < 10s | 同上 + 手工按键 |
| 桌面窗口目视 | L3（浏览器或 desktop 宿主） | < 15s | 无 |
| Adapter 变更 | 该 Adapter 的单测 + L1 场景 | < 30s | 重刷镜像 |
| 设备验证 | 真机 + 抓帧 | 分钟级 | 同 |

**「不需要构建完整 BaseOS」** 在操作上的含义：L0–L2 全部只需要 `bun` + 一份预编的 `pocketjs.wasm`（pinned，可缓存），不需要 docker、不需要 rocknix SDK、不需要 PJOS 的 `build-rootfs.sh`。

`pocketjs.wasm` 的获取方式必须在文档里写清（pinned 版本号 + 校验和），否则「开发机能不能跑」会变成「谁本地有没有缓存」。今天 `PKT/` 是 rocknix 的构建产物（`build.ROCKNIX-H700.aarch64/build/...`，被 `.gitignore:2 /build.*/` 忽略），**不是可分发的输入**。

---

## 8. 本地开发的边界声明（不声称的事）

| 不声称 | 原因 |
|---|---|
| L2 的像素等于设备像素 | 软件栅格 vs GPU 合成（`PKT/docs/BACKENDS.md:20-27`） |
| L2 证明触摸坐标正确 | mock 的触摸坐标是逻辑像素，不含 surface 原点换算 |
| L2 证明帧率可接受 | 无真实 vblank；Redmi 1S 的实测数据见 `PKT/docs/ANDROID.md:243-246` |
| L1 证明平台行为 | mock 是**我们**写的场景，不是设备 |
| 任何层证明音频可听 | 需要真实输出设备（`PKT/platforms/linux/README.md` 明示「These tests do not replace … audible-output validation」） |

这些边界必须出现在 `06` 的开头（本文 §1 已给），并在每次「本地通过」的汇报里复述，否则会重演「mock 通过即宣布可用」的错误。

---

## 9. 待定

| id | 问题 |
|---|---|
| L1 | `pocketjs.wasm` 的分发形态：随 `pocket-shell` 仓的 release 附件，还是 npm 包，还是要求开发者自建 |
| L2 | 帧输出是否需要附带「可见文本」的 dump（比 PNG 更容易 diff）——建议要 |
| L3 | 桌面窗口用浏览器 harness 还是 `programs/desktop`（后者无截图能力，见 §1） |
| L4 | `debugState()` 的契约：只给测试构建，还是也给设备诊断（后者能大幅降低现场排查成本） |
