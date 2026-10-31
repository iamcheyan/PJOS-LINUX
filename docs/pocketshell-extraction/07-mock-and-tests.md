# 07 — Mock 策略与测试矩阵

> 阶段一交付物。回答：**怎么测、在哪测、跨平台差异怎么量化**。
> 前置：[06](06-local-dev.md) 的四层结构；[03](03-platform-api.md) 的错误语义；[05](05-adapters.md) 的 Adapter 验收清单。

---

## 1. 测试分层（与开发层一一对应）

| 层 | 测什么 | 运行环境 | 是否阻塞合并 |
|---|---|---|---|
| T0 契约 | Platform API 的类型/词表/fixture 自洽 | `bun test`，零依赖 | 是 |
| T1 模型 | Shell 的纯函数（终端解析、导航、进度） | `bun test` | 是 |
| T2 Mock | Shell × MockAdapter 的九域行为 + 三态组合 | `bun test` + L2 无头 | 是 |
| T3 视觉 | golden 帧逐字节 | L2 无头（软件栅格） | 是 |
| T4 Adapter 单测 | 每个 Adapter 的 MUST 方法 + 三态证据 | 宿主单测（Go/Rust/Java/shell） | 是 |
| T5 跨平台一致性 | 三份 Adapter 对同一 Shell 的行为差异 | 三台真机 + 统一脚本 | 是（发布门槛） |
| T6 设备抽样 | 像素/帧率/输入映射 | 真机 | 否（记录，不阻塞） |

**T3 只能订在 L2**：设备像素是 GPU 合成，不可跨设备逐字节比较（`PKT/docs/BACKENDS.md:20-27`）。把 golden 订在设备上会导致每次 GPU 驱动更新都要重录。

---

## 2. T0：契约测试

### 2.1 词表与类型自洽

| 测试 | 断言 |
|---|---|
| 每个 Capability id 都能被 `capability.get()` 查到 | 遍历 `CAPABILITIES` 常量，mock manifest 全给 `yes`，逐个 `get` 不为 `invalid` |
| 每个 Feature 的依赖都存在 | `FEATURE_DEPS` 的每个值 ⊆ `CAPABILITIES` |
| 依赖图无环 | 拓扑排序成功 |
| `ERROR_CODES` 与 TS 的 `ErrorCode` 联合类型一致 | 编译期 + 运行时双重（用一个 `satisfies` 与一个遍历） |
| 每个错误码至少有一个 fixture 用到 | 防止「定义了但从没被实现」的码 |
| Schema 与 TS 类型同构 | 用同一份 JSON Schema 校验所有 fixture |

### 2.2 反泄漏（03 §5 的可执行版）

```sh
# 必须在 pocket-shell 与 pocket-platform-api 两个仓的 CI 里跑
! grep -rInE '/sys/|/proc/|/dev/|/run/|/storage/|mmcblk|tty7|DRM|KMS|fbdev|evdev|amixer|pactl|nmcli|bluetoothctl|systemctl|systemd-run|rocknix|baseos|BaseOS|Android|android|H700|A133|RG34XX|RG35XX|RG40XX|CubeXX|M21|FiiO|bengal|sunxi|Snapdragon' \
    --include='*.ts' --include='*.tsx' --include='*.json' \
    src/ schema/ fixtures/ \
  || whitelist_check
```

白名单必须逐条登记（`tests/leak-allow.txt`），每条带理由。例如：

```
fixtures/storage/no-storage.json  | "storage" 出现在键名 "storage.user_content" 中，是 API 词表的一部分，不是路径
```

这条 grep 今天会大量命中——审计里每个泄漏点都在这份词表里。

---

## 3. T1：模型测试

### 3.1 终端模型（最值得单测的一环）

今天的终端解析器必须上设备才能验证（`PJOS docs/13` 的 M1/M2 都是设备步骤）。目标形态：**输入字节 → 期望的 `L`/`C` 行**，纯函数。

| 用例 | 输入 | 期望 |
|---|---|---|
| 基础输出 | `b"hi"` | 1 行，2 个 run，cursor (0,2) |
| 前景/背景色 | `b"\x1b[31mR\x1b[0m"` | fg 红，bg 默认 |
| 256 色 | `b"\x1b[38;5;82mX"` | 按 `color_256` 规则映射 |
| 反显 | `b"\x1b[7mX"` | flags 含反显位，`runColor` 交换前后景（`hello/main.tsx` 的 `runColor`） |
| 制表符 | `b"a\tb"` | 跳列，**`start_col` 正确** |
| 内联空白 | `b"a   b"` | 中间空白被跳过，`start_col` 指到 `b` |
| 宽字符 | `b"\xe6\x97\xa5"`（日） | 占 2 列 |
| 组合字符 | emoji + ZWJ | 不拆坏 |
| 换行滚动 | 25 行输出 | 24 行缓冲，顶部滚出 |
| 光标可见性 | `b"\x1b[?25l"` | `C` 行末位 0 |
| 超长行折行 | 100 字符 | 按 `cols` 折行 |
| 分片 | 一次一个字节喂入 `ESC [` 序列 | 状态机不产生部分序列 |

**必须包含一条「wire 格式」测试**，直接钉住 [01](01-audit.md) §7.2 的 bug：

```
发出 `${fg}:${bg}:${flags}:${col}:${text}`
解析必须把第 4 段当 col（不是文本）
```

今天两端不一致（发出 5 段、解析 `parts.slice(3)` 当文本）。这条测试一旦存在，任何新解析器都不会重犯。

### 3.2 导航与状态

| 用例 | 断言 |
|---|---|
| 环形移动（首→上→尾） | `(i + n - 1) % n` |
| 空列表移动不崩 | `n = 0` |
| 分页窗口跟随选择 | 选中第 9 项时窗口从 0 变 8 |
| 命令面板输入删除 | 空串时 backspace 不变 |
| 阅读进度 | 已知 `size`/`line` → 百分比；边界：第 1 行 0%、末行 100% |

---

## 4. T2：Mock × Shell

### 4.1 三态矩阵（核心）

Shell 必须在**每一种能力组合**下都不崩、不显示假值。矩阵至少覆盖：

| 场景 | 关键断言 |
|---|---|
| 全 `yes` / 全 `supported` | 所有入口可见，读数来自 mock |
| 全 `no` / 全 `unsupported` | 只有 MUST 域可用；状态栏不画电量/无线；设置页只剩通用项 |
| 全 `unknown` | 所有入口可见但标注「未确认」；**不得**出现 `0%`/`--`/`unknown` 字样当数值 |
| `wifi=yes` + `wifi_join=unsupported` | 显示状态、隐藏「连接」 |
| `bluetooth=yes` + `sink=unsupported` + `source=supported` | 只显示「发送」 |
| `battery=unknown` | 图标灰显 + 可解释 |
| `storage.user_content=no` | Library 显示「本平台无内容区」而非空列表 |
| `display.brightness=no` | 无亮度行，且**不出现** `CONTROL\tbrightness` 类调用 |

最后一条需要一个 **调用记录断言器**：mock 后端记录所有被调用的方法，测试断言「不可用时方法从未被调用」。这比断言 UI 文本更强，因为它直接钉住「不允许推断」。

### 4.2 错误路径

| 注入 | 断言 |
|---|---|
| `audio.setVolume` → `unavailable`（前 2 次），第 3 次成功 | UI 提示「暂时不可用」，第 3 次生效；提示消失 |
| `storage.list` → `not_found` | 显示空态 + 原因，不抛 |
| `storage.read` → `io` | 保留已读内容，标记该条不可读 |
| 任意调用 → `timeout` | 显示 loading → 超时提示；**不冻结**（用假时钟推进） |
| 任意调用 → `cancelled` | 无错误日志（E6） |
| `negotiate` → `api` 不匹配 | 进入「不兼容」界面，且**不**调用任何域方法 |

最后一条同样用调用记录断言。

### 4.3 「不允许推断」的可执行判据

对每个 `X=no` 的 Capability 与每个 `F=unsupported` 的 Feature：

1. 启动 Shell；
2. 交互到对应界面；
3. 断言 **mock 后端从未收到**该域方法调用（除 `capability.get`/`feature.get`）。

这条把 issue 的「PocketShell 不允许推断，必须查询」变成 CI 可执行项。

---

## 5. T3：视觉 golden

### 5.1 形态

```
dev/frames/baseline/<scenario>/<width>x<height>/<script>/<frame:04d>.png
dev/frames/baseline/<scenario>/<width>x<height>/<script>/trace.json
```

- `trace.json` 记录每帧 FNV 哈希（与 `PKT/tests/golden.ts` 的做法一致）、可见节点数、焦点节点 id。
- 比对：PNG 逐字节 + 哈希；失败时输出 diff 图（像素差热图）与「哪一帧第一次不同」。

### 5.2 什么改动需要更新 golden

| 改动 | 是否更新 | 判据 |
|---|---|---|
| 文案 | 是 | 明确的产品变更 |
| 布局像素 | 是 | 但必须在 PR 里附「before/after 并排图」 |
| 纯重构 | **否** | 若必须更新，说明重构改变了行为 |
| 字体子集/atlas | 是 | 但只影响字形，须核对 |
| 终端行 wire 格式修复（01 §7.2） | 是，**一次性** | 这是修 bug，必须在 PR 描述里说明旧 golden 是错的 |

### 5.3 分辨率矩阵

至少要跑 Shell 声明支持的每一个逻辑视口。今天的 profile 声明 `[[360,240]]`（`RNX config/profile.ts:10`，被编译进产物），但包根 profile 声明两个（`profile.ts:10`）。目标：**视口来自 `display.info()`**，因此 golden 必须覆盖：

| 逻辑视口 | 来源 | 用途 |
|---|---|---|
| 360×240 | 现有设备（720×480 @2×） | 回归 |
| 720×480 | 包根 profile 的第二档 | 验证 1× 布局 |
| 360×800 | Moto G Play（`PKT/profiles/moto-g-play-dev.ts`） | Android 竖屏 |
| 360×640 | Redmi 1S（`PKT/profiles/redmi-1s-dev.ts`） | Android 小屏 |
| 240×320 | 假想小屏 | 边界 |

**这不是「多设备支持」，是「同一份 Shell 在不同视口下不崩」**——正是 issue 的「接入多平台不改源码」的最小可验证形式。

---

## 6. T5：跨平台一致性（量化差异）

这是 issue 里「做平台兼容测试：比较不同输入系统 / 显示后端 / 音频实现」的落点。

### 6.1 方法：同一脚本，三台设备，三个指标

```
一次运行 = {
  shell:    同一份 pocket-shell.pocket（sha256 记录）
  script:   同一份 inputs/*.jsonl
  scenario: 设备自己的 Adapter（非 mock）
  outputs:  逐帧 PNG（设备抓帧） + trace.json（来自 debugState） + 时序日志
}
```

| 指标 | 定义 | 采集方式 |
|---|---|---|
| **D1 逻辑帧一致率** | 相同 frame index 下，`debugState()` 的语义快照（当前页、焦点 id、可见项数、文本行内容）相同的比例 | trace.json 比对；**这是主指标** |
| **D2 几何偏差** | 同一语义元素在两端的逻辑坐标差（px） | 元素包围盒；来自 debug dump，不是像素识别 |
| **D3 时序偏差** | 同一脚本的输入→可见响应帧数差 | 时序日志里的 `input_frame → state_change_frame` |
| **D4 像素差异率** | 仅在「同视口同密度」时可比：像素差 / 总像素 | 抓帧 PNG 比对（允许保护带） |

**主指标是 D1**：它才是「Shell 行为是否一致」的直接证据。D4 只作参考，因为设备是 GPU（色调/抗锯齿可差，见 `PKT/docs/BACKENDS.md:20-27`）。

### 6.2 D1 的判定门槛

| 类别 | 门槛 |
|---|---|
| 纯状态（页面、选择索引、焦点 id） | **必须 100% 一致**。不一致 = Shell 有平台依赖 → 阻断 |
| 文本内容（终端行、列表项） | 必须 100%；若字体导致换行差，允许「行内容一致但折行点不同」，需显式登记 |
| 可见元素集合 | 允许差异，但每个差异必须对应一个 Capability/Feature 差异（否则 = 推断） |

第三条是核心：**任何 UI 差异都必须能追溯到一次能力查询**。做不到就说明 Shell 在某处用了「平台事实」而非「查询结果」。

### 6.3 差异台账

每次跨平台运行产出一份台账：

| 字段 | 例 |
|---|---|
| 差异 id | `D-001` |
| 两端 | BaseOS / Rocknix |
| 指标 | D1-可见元素 |
| 现象 | Rocknix 显示「服务开关」区，BaseOS 不显示 |
| 归因 | BaseOS Adapter 无服务开关能力（九域无此域） |
| 判定 | **合法**（功能不属于平台契约） |
| 处置 | Shell 侧删除该区（迁移任务 M5） |

台账进版本控制。**没有台账的差异 = 缺陷。**

### 6.4 跑法（设计）

| 步骤 | 命令形态 | 备注 |
|---|---|---|
| 1. 生成统一脚本 | `bun run compat gen --out /tmp/compat` | 复用 T2 的 `.jsonl` |
| 2. 设备 A | 推送 Shell 包 + 脚本，跑完抓帧 + dump | 每平台一条命令（见 08 的验证命令） |
| 3. 设备 B | 同上 | |
| 4. 比对 | `bun run compat diff /tmp/compat/a /tmp/compat/b` | 输出 D1–D4 + 台账草案 |
| 5. 归档 | 结果进 `docs/compat/<date>/` | 含 shell sha256、adapter 版本、固件版本 |

---

## 7. T4：Adapter 单测（每个 Adapter 各一套，不共享代码）

| Adapter | 测试手段 | 关键用例 |
|---|---|---|
| BaseOS | shell 单测（假 `/sys` 树 + 假命令，沿用 `PJOS tests/*.sh` 的 docker 模式，`tests/test-keyboardd.sh:18`） | 无背光→`unsupported`；无卡→`storage.user_content=no`；keyboardd 未起→`unsupported` |
| Rocknix | Rust 单测 + 假 sysfs | `amixer` 缺失→`unknown`（不是 `no`）；DRM 无 connector→`display.info` 拒绝 `unavailable` |
| Android | JVM 单测 + `androidTest`（真机） | 无振动器→`input.haptics=unsupported`；`WifiManager` 无权限→`wifiState` 拒绝 `denied` |

**共同要求**：每个 Adapter 必须提交 `capability-evidence.md`，每个 `yes`/`no` 都要指到「哪条判定代码 + 哪次实测」。`unknown` 必须写明「为什么不知道」。这是 [05](05-adapters.md) A3 的可执行版。

---

## 8. 测试矩阵总表

| Shell 功能 | T1 | T2 | T3 | BaseOS | Rocknix | Android |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| 状态栏（电量/无线/音量/时间） | — | ✓ | ✓ | 真机 | 真机 | 真机 |
| 卡片/列表导航 | ✓ | ✓ | ✓ | 抽样 | 抽样 | 抽样 |
| 设置页（亮度/音量/无线/休眠） | — | ✓ | ✓ | 真机 | 真机 | 真机（部分 unsupported） |
| 系统信息页 | ✓ | ✓ | ✓ | 真机 | 真机 | 真机 |
| 终端工作区 | ✓ | ✓ | ✓ | 真机 | 真机 | **预期 unsupported**（无 PTY 契约） |
| Library 浏览/阅读 | ✓ | ✓ | ✓ | 真机 | 真机 | 真机（MediaStore） |
| 文本输入 | ✓ | ✓ | ✓ | 真机（keyboardd） | Shell 自绘 | Shell 自绘 |
| 语言切换 | ✓ | ✓ | ✓ | 抽样 | 抽样 | 抽样 |
| 输入法/IME | — | ✓ | — | `unsupported` | `unsupported` | 待定 |

「预期 unsupported」这一格必须写进矩阵：**Android 上终端不可用是设计结果，不是缺陷**。今天若强行支持，就要在 Android 上重新实现一套 PTY + shell 进程模型（`PKT` 里没有）。

---

## 9. 与现有测试资产的衔接（不重写）

| 现有 | 用途 | 处置 |
|---|---|---|
| `PJOS tests/test-frontend-session.sh`（700 行，docker + 假 `/sys`） | BaseOS 启动序回归 | 保留；Adapter 落地后改为验证「启动 Runtime + Adapter」 |
| `PJOS tests/test-keyboardd.sh` | Input API 契约 | 保留；Adapter 的 `openTextSession` 测试复用它 |
| `PKT/tests/golden.ts`（`:93-190`） | wasm 逐字节 golden | **直接作为 T3 的引擎**，不自造 |
| `PKT/tools/tape.ts`（`:30-53,195-232`） | 录制/回放 + 哈希断言 | 作为 `.jsonl` 回放的参考实现 |
| `PKT/apps/rocknix-h700/launcher-smoke.ts` | 「wasm + 注入 ops + eval 产物」的完整先例 | T2/T3 的起点 |
| `RNX tools/pocketshell-dev/tests/protocol.rs` | 远程协议集成测试 | 保留在 rocknix；不进 Shell 仓 |
| `PKT/tests/android-platform.test.ts` / `-integration.test.ts` | Android input 的 portable + JNI 测试 | 保留；Adapter 的 Input 测试基于它扩展 |

**一条纪律**：不新增「测试基础设施」。上表已经覆盖 wasm golden、录制回放、假 sysfs、协议集成四类；新架构只需要把它们接到新边界上。

---

## 10. 待定

| id | 问题 |
|---|---|
| T1 | D1 的语义快照需要 Shell 暴露 `debugState()`；是否允许在产品构建里保留（只读、无副作用）——建议保留，现场排查价值大 |
| T2 | D4 像素差异的保护带阈值需要一次实测才能定（建议先只记录不判定） |
| T3 | golden 是否随仓存 PNG（体积）还是只存哈希（无法人看）——建议 PNG + 哈希双存，PNG 可 LFS |
| T4 | 跨平台运行需要三台真机同时可用；是否需要一台「第二 Rocknix 设备」以防单机不可用 |
