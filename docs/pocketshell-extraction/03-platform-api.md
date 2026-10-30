# 03 — Pocket Platform API 规格

> 阶段一交付物。**只写签名与语义，不写实现。** 本文所有接口都不得出现平台概念：没有 `/sys`、`/dev`、`/proc`，没有板名、SoC 名、分区号、单元名、命令名。
>
> 依赖：[01-audit.md](01-audit.md) 给出了今天每个泄漏点的位置；本文给出替代它们的接口。
> Capability / Feature 的词表与判定流程在 [04](04-capability-feature.md)；Adapter 契约在 [05](05-adapters.md)。

---

## 0. 设计约束（先定，再写签名）

| # | 约束 | 理由（来自审计） |
|---|---|---|
| A1 | **所有方法异步**，返回 `Promise`；渲染帧内不允许等待 | 今天的桥是同步字符串调用，跑在 guest 渲染线程上，因此每次外部查询都要 `/usr/bin/timeout 2` 包一层（`PKT/.../pocketshell_launcher.rs:3-19`），并留下「`pactl` 阻塞导致整屏黑」的事故记录 |
| A2 | **状态栏读缓存，不读设备**：提供 `snapshot()` 同步返回最近一次已知值 + 时间戳 + `stale` 标记 | UI 每帧要显示电量/音量/Wi-Fi，但设备查询不能进帧 |
| A3 | **缺失是一等答案**：`unsupported` / `unavailable` / `unknown` 三个不同含义，都用返回值表达，不用抛异常 | 今天无背光节点时把 `"unknown".into()` 与「读到了但解析失败」写成同一个字符串出口（`launcher.rs:6-16`），与「查询失败」不可区分 |
| A4 | **不做平台分支**：API 里没有 `platform` 字段可供 Shell 读取 | issue 要求「PocketShell 永远不知道自己运行在哪个平台」 |
| A5 | **不推断**：任何「有没有 / 能不能」都必须来自 Capability/Feature 查询 | issue 原文「PocketShell 不允许推断，必须查询」 |
| A6 | **超时与取消是契约的一部分** | 今天没有超时语义，只有外层的 `timeout 2` |
| A7 | **数值单位统一**：百分比 0–100 整数；时间毫秒；字节；坐标是**逻辑像素** | 今天的 `LEVEL\tip` 返回 `"iface\|addr"`、`SYSTEM` 返回 18 个制表符字段（`PKT/.../pocketshell_launcher.rs:135-187`），全靠 Shell 自己 `split` |

### 0.1 命名空间总览

```
pocket.platform
├── version       版本协商（§2）
├── capability    Capability 域（§3.8，词表见 04）
├── feature       Feature 域（§3.9，词表见 04）
├── display       Display 域（§3.1）
├── input         Input 域（§3.2）
├── audio         Audio 域（§3.3）
├── storage       Storage 域（§3.4）
├── battery       Battery 域（§3.5）
├── power         Power 域（§3.6）
└── network       Network 域（§3.7）
```

---

## 1. 通用类型

```ts
/** 三态。unknown ≠ 没有；它是「平台没回答」。 */
export type TriState = "yes" | "no" | "unknown";

/** 所有异步调用的统一失败形状。成功不返回它。 */
export interface PlatformError {
  readonly code: ErrorCode;
  /** 给人看的一句话，可本地化；Shell 不得用它做分支。 */
  readonly message: string;
  /** 同一请求在稍后重试是否可能成功。 */
  readonly retryable: boolean;
  /** 可选的机器可读细节（例如失败的具体子项）。Shell 只能用于展示。 */
  readonly detail?: Readonly<Record<string, string | number>>;
}

export const ERROR_CODES = [
  "unsupported",   // 平台明确声明没有这个能力/功能。retryable=false。终态。
  "unavailable",   // 声明有，但此刻不可用（无设备、无权限、被占用）。retryable 视情况。
  "timeout",       // 超过该方法的 deadline。retryable=true。
  "cancelled",     // 调用方取消。retryable=true。
  "denied",        // 平台策略拒绝（沙箱、家长控制、前台占用）。retryable=false。
  "invalid",       // 参数非法。retryable=false。调用方 bug。
  "not_found",     // 目标不存在（文件/条目/网络）。retryable=false。
  "io",            // 底层 IO 失败。retryable 视情况。
  "version",       // API 主版本不兼容。retryable=false。
] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

/** 每个调用可带超时与取消信号；省略时用该域的默认值（见 §1.2）。 */
export interface CallOptions {
  readonly timeoutMs?: number;
  readonly signal?: AbortSignal;
}

/** 带时间戳的读数。stale=true 表示「这是缓存，不是刚刚测的」。 */
export interface Reading<T> {
  readonly value: T;
  /** 单调时钟毫秒（来源由 Runtime 提供，Shell 只用来比较新鲜度）。 */
  readonly at: number;
  readonly stale: boolean;
}

/** 订阅句柄。dispose() 之后不再回调。 */
export interface Subscription {
  dispose(): void;
}
```

```ts
export function isPlatformError(value: unknown): value is PlatformError
```

### 1.1 「缺失」怎么表达（三种，不混用）

| 情形 | 返回值 | 例子 |
|---|---|---|
| 平台**根本没有**这项硬件/功能 | `capability.get("wifi") === "no"`，相关方法可省略或返回 `unsupported` | 没有背光的设备：`display.getBrightness()` → 拒绝 `unsupported`；`capability.get("display.brightness") === "no"` |
| 声明有，**此刻**不可用 | 拒绝 `unavailable` + `retryable` | Wi-Fi 有硬件但驱动未起 |
| 平台**没回答**（老 Adapter、查询超时） | `capability.get("wifi") === "unknown"` | 迁移期 |

**禁止**：把「不知道」写成 `0`、`-1`、`""`、`"--"`、`"unknown"` 字符串让 Shell 猜。今天 `LEVEL\tbattery` 无值时返回字符串 `"unknown"`、`LEVEL\tip` 无值时返回 `"--"`（`PKT/.../pocketshell_launcher.rs:202,236`），这就是被本规则废掉的形态。

### 1.2 默认超时

| 域 | 默认 `timeoutMs` | 说明 |
|---|---:|---|
| `capability` / `feature` | 200 | 本地查表，适配器应在启动时建好索引 |
| `display`（读） | 300 | |
| `display.setBrightness` | 1500 | 写设备可能慢 |
| `input.openTextSession` | 500 | |
| `audio`（读/写音量） | 1500 | |
| `storage`（list/stat/read） | 3000 | 大目录允许更久，调用方显式给 |
| `battery` | 300 | |
| `power`（reboot/shutdown） | 5000 | |
| `network`（wifi 关联） | 30000 | 关联是慢操作 |
| 任何域 | 0 / `undefined` | 用默认；`timeoutMs: 0` 表示不超时（**不推荐**，仅调试） |

---

## 2. 版本协商

### 2.1 版本模型

| 层 | 载体 | 语义 |
|---|---|---|
| **API 主版本** | `api: number`（从 1 开始，整数） | 不兼容变更才 +1。追加方法/追加 capability 值**不**升。 |
| **API 能力清单** | `capabilities` / `features` 的 map | 加键不升版本；Shell 必须容忍未知键（忽略）。 |
| **数值上限** | `limits` | 例如单次读取最大字节。带默认值，Adapter 可收紧。 |
| **Adapter 实现** | `adapter: string` | **不暴露给 Shell**；只用于诊断与日志。 |
| **PocketJS 绑定代次** | 由 pinned upstream 规定 | 与 API 版本**正交**，互不声称。 |

```ts
export interface PlatformInfo {
  /** 整数主版本。 */
  readonly api: number;
  /** Runtime 诊断用；Shell 类型上不暴露该字段。 */
  readonly runtimeVersion: string;
  /** Shell 只能看到这几项。 */
  readonly capabilities: Readonly<Record<string, TriState>>;
  readonly features: Readonly<Record<string, FeatureState>>;
  readonly limits: Limits;
}

export interface Limits {
  /** 单次 storage.read 的字节上限。 */
  readonly maxReadBytes: number;
  /** 默认 scan 返回的最大条目数。 */
  readonly maxScanEntries: number;
  /** 同时打开的键盘/输入法会话上限（通常 1）。 */
  readonly maxTextSessions: number;
  /** Runtime 支持的最大订阅数。 */
  readonly maxSubscriptions: number;
}
```

```ts
export interface ShellRequirement {
  /** Shell 编译时依赖的 API 主版本。 */
  readonly api: number;
  /** 缺任一项则 Shell 不能工作。 */
  readonly requiresCapabilities: readonly string[];
  /** 缺任一项则该功能入口隐藏（不是启动失败）。 */
  readonly requiresFeatures: readonly string[];
}

export interface NegotiationResult {
  /** false 时 Shell 必须进入只读的「不兼容」界面，不得尝试降级。 */
  readonly ok: boolean;
  readonly api: number;
  readonly missingCapabilities: readonly string[];
  readonly missingFeatures: readonly string[];
  /** 版本层面的原因（ok=false 时必有）。 */
  readonly error?: PlatformError;
}

export function negotiate(requirement: ShellRequirement): Promise<NegotiationResult>
```

### 2.2 协商规则（必须逐条实现）

1. **主版本相等才继续**。`requirement.api !== info.api` → `ok:false`，`error.code="version"`。**不做向前兼容猜测**：API 只有追加式演进，因此主版本不同就是不兼容。
2. `requiresCapabilities` 里任一项的值为 `"no"` → `ok:false`，列进 `missingCapabilities`。
3. `requiresCapabilities` 为 `"unknown"` → **不阻止启动**，但必须列入 `missingCapabilities` 并在 UI 明确标注「平台未确认」；Shell 不得据此假设它存在。
4. `requiresFeatures` 里任一项不为 `"supported"` → `ok:true`，但对应入口必须隐藏或禁用（`missingFeatures`）。功能缺失不等于 Shell 不能运行。
5. 协商**只发生一次**（启动时），结果缓存；`capability`/`feature` 的运行时变化走订阅，不允许重新协商。
6. 协商结果必须可序列化并落日志（便于现场取证）。

### 2.3 Shell 声明的形态（`pocket.json` 之外的一层）

```jsonc
// shell.requires.json —— 由 pocket-shell 自己维护，随包发布
{
  "api": 1,
  "requiresCapabilities": ["display.brightness", "audio.output"],
  "requiresFeatures": ["display.rotation", "power.suspend", "network.wifi_join"]
}
```

这段**不替代** PocketJS 的 `engine.capabilities.requires`（`PKT/contracts/spec/pocket-manifest.ts:79-80`）。两者关系：PocketJS 的 requires 是 guest↔host 的准入（缺则包被拒）；本文件是 Shell↔Platform 的能力协商（缺则功能降级）。映射见 [04](04-capability-feature.md) §5。

---

## 3. 九个域

### 3.1 Display

```ts
export interface Viewport {
  /** 逻辑像素。Shell 的所有布局都用这个坐标系。 */
  readonly width: number;
  readonly height: number;
}

export type Presentation = "native" | "integer-fit" | "fit" | "stretch";

export interface DisplayInfo {
  /** Shell 应当按这个逻辑视口布局。 */
  readonly logical: Viewport;
  /** 物理像素，仅用于「按硬件分辨率选择资源」这类展示性判断。 */
  readonly physical: Viewport;
  /** 逻辑像素对应的设备像素数（整数）。 */
  readonly density: number;
  /** 当前朝向，从设备默认朝向起算的顺时针角度。0/90/180/270。 */
  readonly rotationDeg: 0 | 90 | 180 | 270;
  /** Runtime 可用的呈现方式；至少含一项。 */
  readonly presentations: readonly Presentation[];
  /** 有外部显示输出时为 true（例如 HDMI）。 */
  readonly external: boolean;
}

export interface Display {
  info(options?: CallOptions): Promise<DisplayInfo>;

  /** 0–100。无背光时拒绝 `unsupported`。 */
  getBrightness(options?: CallOptions): Promise<number>;
  /** 0–100，超出范围拒绝 `invalid`。 */
  setBrightness(percent: number, options?: CallOptions): Promise<void>;

  /** 旋转。不支持的档位拒绝 `unsupported`；不需要 `Display.rotation` feature。 */
  setRotation(deg: 0 | 90 | 180 | 270, options?: CallOptions): Promise<void>;

  /** 屏幕开关（息屏/点亮），不影响系统是否休眠。 */
  setOn(on: boolean, options?: CallOptions): Promise<void>;

  /** 逻辑视口/朝向/外部显示变化。仅在 `display.viewport.live` 或旋转发生时触发。 */
  onChange(listener: (info: DisplayInfo) => void): Subscription;

  /** 同步缓存，供每帧渲染使用（见 A2）。 */
  snapshot(): Reading<{ brightness: number | null; on: boolean | null }>;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 无背光（`display.brightness` capability = `no`）、不支持旋转、不支持息屏 |
| `unavailable` | 有背光但通道被占用（例如前台应用独占） |
| `invalid` | `percent` 不在 0–100、`deg` 不在枚举内 |
| `timeout` | 写入超过 deadline |

**泄漏检查**：`DisplayInfo` 里**没有** fb/drm/bpp/panel 名/`/dev/fb0`。今天的等价物是 `display_mode()` 读 `/sys/class/graphics/fb0/virtual_size` 与 `/sys/class/drm/*/modes`（`PKT/.../pocketshell_launcher.rs:98-113`），这些全部沉到 Adapter。

### 3.2 Input

Input 域**不传递原始按键/触摸事件**——那些仍然由 Runtime 以 PocketJS 的 frame 参数交付（`PKT/contracts/spec/input.ts:21-27` 的 `LEGACY_FRAME_ARGUMENTS`）。本域只管三件事：**模式查询、文本会话（OSK/IME）、触觉反馈**。

```ts
export type InputMode = "touch" | "dpad" | "pointer" | "text";

export interface InputFacts {
  /** 与 PocketJS 的 input.* capability 对齐（映射见 04 §5）。 */
  readonly touch: boolean;
  readonly buttons: boolean;
  readonly pointer: boolean;
  /** 有实体键盘/硬件文本流。 */
  readonly text: boolean;
  /** 有系统输入法（组合/候选）。 */
  readonly ime: boolean;
  /** 平台建议的默认交互模式。Shell 必须用它，不得自行推断。 */
  readonly mode: InputMode;
  /** 拇指区/摇杆数量，0 表示没有。 */
  readonly analogSticks: 0 | 1 | 2;
}

export type TextLayout = "text" | "number" | "url";

export interface TextSessionRequest {
  readonly layout: TextLayout;
  /** 预填内容（重命名场景）。 */
  readonly value?: string;
  readonly placeholder?: string;
  /** 掩码显示。`number` 布局的口令/密码输入用它，而不是另造一个布局名。 */
  readonly secure?: boolean;
  /** 供平台侧做「同一字段保持焦点」的身份；Shell 自己生成，语义自定。 */
  readonly fieldId?: string;
}

export interface TextSessionResult {
  readonly value: string;
  /** 用户取消时为 true；此时 value 是进入会话前的值。 */
  readonly cancelled: boolean;
}

export interface Input {
  facts(options?: CallOptions): Promise<InputFacts>;

  /**
   * 打开平台输入会话（可能是系统 OSK、IME、或「不需要 UI，硬件键盘可用」）。
   * 有 `input.osk` feature 时必然可用；否则拒绝 `unsupported`，
   * Shell 才允许落地自己画的键盘。
   */
  openTextSession(request: TextSessionRequest, options?: CallOptions): Promise<TextSessionHandle>;

  /** 触觉反馈。feature `input.haptics`。 */
  feedback(effect: "tick" | "confirm" | "reject", options?: CallOptions): Promise<void>;

  onChange(listener: (facts: InputFacts) => void): Subscription;
}

export interface TextSessionHandle {
  /** 会话 id；用于日志与去重，Shell 不得解析。 */
  readonly id: string;
  /** 提交：返回合成值并关闭会话。 */
  submit(override?: string, options?: CallOptions): Promise<TextSessionResult>;
  /** 取消：关闭会话，返回进入前的值。 */
  cancel(options?: CallOptions): Promise<TextSessionResult>;
  /** 平台侧主动结束（用户点了系统返回键）。 */
  onEnd(listener: (result: TextSessionResult) => void): Subscription;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 无 `input.osk`、无 `input.haptics` |
| `unavailable` | 已有会话在使用（> `maxTextSessions`），或平台输入被前台占用 |
| `denied` | 策略禁止（例如安全策略禁用输入法） |
| `not_found` | `submit` 时会话已结束 |
| `invalid` | 布局名非法 |

**设计说明**：把「输入法所有权」收进平台，是为了消灭今天的两套键盘：Shell 自己画的 6 标签输入面板（`RNX hello/main.tsx:36-49`）与旁挂的 keyboardd HTTP 服务（`PJOS runtime/keyboardd/cmd/keyboardd/main.go:26` 监听 `127.0.0.1:8787`）。keyboardd 变成 BaseOS Adapter 的一个 `openTextSession` 实现，Shell 不再需要知道 `:8787`。

### 3.3 Audio

```ts
export type AudioOutput = "speaker" | "headphone" | "bluetooth" | "hdmi" | "usb" | "unknown";

export interface AudioState {
  /** 0–100 输出音量。 */
  readonly volume: number;
  readonly muted: boolean;
  /** 当前活动输出。多路同时输出时取主输出。 */
  readonly output: AudioOutput;
  /** 平台是否允许 Shell 改音量（`audio.hw_volume` feature）。 */
  readonly volumeControllable: boolean;
}

export interface Audio {
  state(options?: CallOptions): Promise<AudioState>;
  /** 0–100。不可控时拒绝 `unsupported`。 */
  setVolume(percent: number, options?: CallOptions): Promise<void>;
  setMuted(muted: boolean, options?: CallOptions): Promise<void>;
  /** 输出切换（耳机插入/拔出、蓝牙连接）时触发。 */
  onChange(listener: (state: AudioState) => void): Subscription;
  /** 同步缓存。 */
  snapshot(): Reading<AudioState | null>;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | `volumeControllable === false` 时写操作；无音频硬件时读也拒绝 |
| `unavailable` | 有硬件但路由未就绪（例如蓝牙已连但音频 profile 未激活） |
| `invalid` | `percent` 越界 |

**关于播放**：PCM 播放**不属于**本域。它由 PocketJS 的 `globalThis.audio` 命名空间承载（`PKT/framework/src/audio-api.ts:28-41` 的 `AudioOps`）。本域只回答「系统音量与输出路由」，因为那是 Shell 的状态栏和设置页需要的东西。这个区分必须写进 Adapter 契约，否则会出现两套音频控制。

### 3.4 Storage

两个不同概念，必须分开：

- **App 私有区**：Shell 自己的数据库/设置/缓存。路径不可见，只有逻辑名。
- **用户集合根**：用户的内容目录（文档/书籍/报告/音乐…），由平台声明，Shell 只能读，写入走 `write` 且受配额约束。

```ts
/** 用户集合的逻辑根。具体路径由平台决定，Shell 永远看不到。 */
export type CollectionId = "documents" | "books" | "reports" | "music" | "videos" | "screenshots" | "downloads";

export interface StorageEntry {
  /** 相对所在的集合根/目录的路径，段之间用 "/"。不含根名。 */
  readonly path: string;
  readonly name: string;
  readonly kind: "file" | "dir";
  readonly sizeBytes: number;
  /** 毫秒时间戳；平台不提供时为 null。 */
  readonly modifiedAt: number | null;
}

export interface ListPage {
  readonly entries: readonly StorageEntry[];
  /** 下一页的游标；null 表示结束。 */
  readonly next: string | null;
}

export interface StorageUsage {
  readonly usedBytes: number;
  /** 0 表示不限额。 */
  readonly quotaBytes: number;
  /** 平台整体剩余空间，用于提示（不是本应用配额）。 */
  readonly freeBytes: number;
}

export interface Storage {
  /** 平台声明了哪些用户集合。Shell 据此决定 Library 显示哪些分组。 */
  collections(options?: CallOptions): Promise<readonly CollectionId[]>;

  list(collection: CollectionId, path?: string, options?: CallOptions & { cursor?: string; limit?: number }): Promise<ListPage>;
  stat(collection: CollectionId, path: string, options?: CallOptions): Promise<StorageEntry>;
  read(collection: CollectionId, path: string, offsetBytes: number, maxBytes: number, options?: CallOptions): Promise<Uint8Array>;

  /** 写入只有两个位置：应用私有区，或可写的用户集合（平台声明）。 */
  writeAppFile(name: string, data: Uint8Array, options?: CallOptions): Promise<void>;
  readAppFile(name: string, options?: CallOptions): Promise<Uint8Array | null>;
  deleteAppFile(name: string, options?: CallOptions): Promise<void>;
  appUsage(options?: CallOptions): Promise<StorageUsage>;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 该集合不存在（`collections()` 未列出） |
| `not_found` | 路径不存在 |
| `invalid` | 路径含 `..`、绝对路径、或 `maxBytes` > `limits.maxReadBytes` |
| `denied` | 无写权限、越出配额 |
| `io` | 读失败（介质移除、坏块） |

**关键点**：今天 Library 直接扫 `/storage/docs|books|reports|library`（`RNX scripts/pocketshell-library.rs:7`），并通过 `POCKETSHELL_LIBRARY_ROOTS` 环境变量重定位（`:12`）。新模型下 Shell 调 `collections()` 拿到集合名，路径完全不可见；`read` 的分页/编码边界由 Runtime 保证（今天的 `MAX_READ = 16 * 1024` 与 UTF-8 边界修剪逻辑 `:57-67` 移进 Runtime）。

### 3.5 Battery

```ts
export interface BatteryStatus {
  /** 0–100 整数。 */
  readonly percent: number;
  /** 是否在充电。无法判定时 null。 */
  readonly charging: boolean | null;
  /** 交流/电池/无线，平台无法判定时 "unknown"。 */
  readonly source: "ac" | "battery" | "wireless" | "unknown";
  /** 秒；无法估算时 null。 */
  readonly timeRemainingSec: number | null;
  /** 温度摄氏度；无传感器时 null。 */
  readonly temperatureC: number | null;
  /** 健康度 0–100；无则 null。 */
  readonly healthPercent: number | null;
}

export interface Battery {
  status(options?: CallOptions): Promise<BatteryStatus>;
  onChange(listener: (status: BatteryStatus) => void): Subscription;
  snapshot(): Reading<BatteryStatus | null>;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 无电量计（`capability.get("battery") === "no"`） |
| `unavailable` | 有节点但读不出（驱动未就绪） |

**为什么 `charging` / `timeRemainingSec` / `temperatureC` 允许 `null`**：这三项在不同设备上可由完全不同的芯片提供。用 `null` 表示「这个平台不测这一项」，与 `unsupported`（整块没有）区分。今天 `LEVEL\tbattery` 只给一个百分比（`PKT/.../pocketshell_launcher.rs:201-221`），状态栏只能画一个数字。

### 3.6 Power

```ts
export type SleepReason = "user" | "idle" | "lid";

export interface IdlePolicy {
  /** 0 = 永不。单位毫秒。 */
  readonly screenOffMs: number;
  /** 0 = 永不。必须 ≥ screenOffMs（或同时为 0）。 */
  readonly suspendMs: number;
}

export interface Power {
  /** 当前空闲策略。 */
  idlePolicy(options?: CallOptions): Promise<IdlePolicy>;
  setIdlePolicy(policy: IdlePolicy, options?: CallOptions): Promise<void>;

  /** 立即息屏（不等于休眠）。 */
  screenOff(options?: CallOptions): Promise<void>;

  /** 进入睡眠。feature `power.suspend`。 */
  suspend(reason: SleepReason, options?: CallOptions): Promise<void>;

  /** 关机/重启。feature `power.shutdown` / `power.reboot`。 */
  shutdown(options?: CallOptions): Promise<void>;
  reboot(options?: CallOptions): Promise<void>;

  /** 唤醒闹钟。feature `power.rtc_alarm`。at 为绝对时间（毫秒）。 */
  setAlarm(at: number, options?: CallOptions): Promise<void>;
  clearAlarm(options?: CallOptions): Promise<void>;
  alarm(options?: CallOptions): Promise<number | null>;

  /** 睡眠/唤醒。Shell 用它暂停动画与轮询。 */
  onSleepState(listener: (state: { asleep: boolean; reason: SleepReason | null }) => void): Subscription;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 无进入该电源状态的能力（feature = `no`） |
| `denied` | 平台策略拒绝（例如充电中禁止关机、前台应用占用） |
| `unavailable` | 电源管理服务未就绪 |
| `invalid` | `suspendMs < screenOffMs`；`at` 早于现在 |

**为什么把「空闲策略」收进来**：今天它是两个不同实现的混合物——`pocketjs-sleep` 守护进程（Python，读 `/dev/input`，写 `/sys/class/backlight`，`RNX scripts/pocketjs-sleep:17-19,92-95`）与 Shell 写的 `runtime.conf` `[sleep] timeout`（`launcher.rs:53-86`）。平台化之后：Shell 只说「5 分钟息屏、30 分钟睡眠」，实现归 Adapter。

### 3.7 Network

```ts
export interface WifiState {
  /** 硬件存在且可用。 */
  readonly enabled: boolean;
  /** 已关联某个网络。 */
  readonly connected: boolean;
  /** 当前 SSID；未连接为 null。 */
  readonly ssid: string | null;
  /** IPv4 字符串；无则 null。Shell 不得自行拼接。 */
  readonly ipv4: string | null;
  /** 信号强度 0–100；无法判定为 null。 */
  readonly signalPercent: number | null;
}

export interface WifiNetwork {
  readonly ssid: string;
  readonly signalPercent: number;
  readonly secure: boolean;
}

export interface BluetoothState {
  readonly enabled: boolean;
  /** 已配对设备数。 */
  readonly pairedCount: number;
  /** 已连接设备数。 */
  readonly connectedCount: number;
}

export interface Network {
  wifiState(options?: CallOptions): Promise<WifiState>;
  setWifiEnabled(on: boolean, options?: CallOptions): Promise<void>;

  /** 扫描。feature `network.wifi_scan`。结果按信号强度降序。 */
  scanWifi(options?: CallOptions): Promise<readonly WifiNetwork[]>;

  /**
   * 加入网络。口令输入由 Shell 通过 `Input.openTextSession({layout:"number", secure:true})`
   * 取得后传入。feature `network.wifi_join`。
   */
  joinWifi(ssid: string, secret: string, options?: CallOptions): Promise<void>;
  forgetWifi(ssid: string, options?: CallOptions): Promise<void>;

  bluetoothState(options?: CallOptions): Promise<BluetoothState>;
  setBluetoothEnabled(on: boolean, options?: CallOptions): Promise<void>;

  onChange(listener: (state: { wifi: WifiState; bluetooth: BluetoothState }) => void): Subscription;
  snapshot(): Reading<{ wifi: WifiState | null; bluetooth: BluetoothState | null }>;
}
```

| 错误 | 何时 |
|---|---|
| `unsupported` | 无该无线硬件，或缺相应 feature |
| `unavailable` | 硬件在但未就绪（驱动、supplicant） |
| `not_found` | `forgetWifi` 的 SSID 未保存；`joinWifi` 的 SSID 扫描不到 |
| `denied` | 策略拒绝改无线状态 |
| `timeout` | 关联超时（默认 30s） |
| `invalid` | SSID 为空/超长 |

**关于「网络状态」的其他部分**：`ipv4` 只给字符串，因为 Shell 只显示。今天的等价物是解析 `ip -o -4 addr show` 的输出（`PKT/.../pocketshell_launcher.rs:223-236`，并按 `scope host`/`lo` 过滤），这套解析必须消失。

**蓝牙**：本域只回答「开没开、连了几个」。配对/发现流程属于平台设置界面（`pocket-settings` 的领域），不进 Shell 契约。这避免了把 `bluetoothctl` 的交互式会话塞进 API。

### 3.8 Capability

```ts
export interface Capability {
  /** 词表见 04 §2。未注册的 id 是 Shell bug。 */
  get(id: string, options?: CallOptions): Promise<TriState>;
  list(options?: CallOptions): Promise<Readonly<Record<string, TriState>>>;
  /** 便捷判定：仅 `"yes"` 为 true；`"unknown"` 必须当 false 用，且 UI 要能说明原因。 */
  has(id: string, options?: CallOptions): Promise<boolean>;
  onChange(listener: (changes: Readonly<Record<string, TriState>>) => void): Subscription;
  /** 同步快照，供首帧渲染（避免首帧闪「未知」）。 */
  snapshot(): Readonly<Record<string, TriState>>;
}
```

**为什么 `has()` 存在而 `get()` 不省略**：`has()` 是 `get() === "yes"` 的糖，但它强制调用点显式，并且不允许 Shell 写 `if (cap.wifi)` 这类隐式真值判断（`"unknown"` 是真值，会误判）。

| 错误 | 何时 |
|---|---|
| `invalid` | `id` 不在 API 词表内（拼写错误必须响亮失败，不能被当成 `unknown`） |
| `timeout` | 超过 deadline（正常情况下不会发生：来源是 Adapter 启动时建好的内存索引） |

本域**不允许** `unsupported`——三态本身就是回答，这是九个域里唯一不允许拒绝读操作的地方，因为 Shell 的首帧必须能问到「有没有」。它与 Feature 的联合一致性校验在 Runtime 加载 Adapter 时执行（[04](04-capability-feature.md) §3.8）。

### 3.9 Feature

```ts
export type FeatureState = "supported" | "unsupported" | "unknown";

export interface Feature {
  get(id: string, options?: CallOptions): Promise<FeatureState>;
  list(options?: CallOptions): Promise<Readonly<Record<string, FeatureState>>>;
  onChange(listener: (changes: Readonly<Record<string, FeatureState>>) => void): Subscription;
  snapshot(): Readonly<Record<string, FeatureState>>;
}
```

**与 Capability 的分工**（issue 原文）：Capability 回答「有没有」（wifi / bluetooth / touch / vibration / hdmi）；Feature 回答「能干什么」（bt_sink / bt_source / audio_hw_volume / display_rotation / suspend / rtc_alarm）。判定与降级流程见 [04](04-capability-feature.md)。

**关键约束**：Feature **可以**依赖 Capability（`bt_sink` 需要 `bluetooth`），但 Capability **绝不**能从 Feature 推导。因此：

- `capability.get("bluetooth") === "no"` ⇒ `feature.get("bluetooth.sink")` 必须为 `unsupported`（一致性由 Runtime 校验，不一致则拒绝启动 Adapter）。
- 反过来不成立：`bluetooth === "yes"` 而 `bluetooth.sink === "unsupported"`（只有 BLE，无 A2DP）是合法且常见的。

| 错误 | 何时 |
|---|---|
| `invalid` | `id` 不在 API 词表内 |
| `timeout` | 超过 deadline（与 Capability 同：内存索引，正常不会发生） |

与 Capability 一样，本域不允许 `unsupported`：`"unsupported"` 是**值**，不是异常。唯一的实现侧义务是加载期的一致性（见 04 §3.8）。

---

## 4. 错误语义总表

| 规则 | 内容 |
|---|---|
| E1 | **成功不返回错误**：不返回 `{ok:true}` 包装，直接返回值。失败一律 reject `PlatformError`。 |
| E2 | **禁止吞错**：Adapter 不得把内部失败映射为 `0`/`""`/`"--"`。今天 `LEVEL\tbrightness` 无节点时返回 `"unknown"`（`launcher.rs:17`）就是反面例子。 |
| E3 | **`unsupported` 是终态**：不得 retryable。Shell 收到后必须隐藏/禁用入口并记住（进程内缓存）。 |
| E4 | **`unknown` 不是错误**：只有 Capability/Feature 有 `unknown`，它们是**值**不是异常。 |
| E5 | **deadline 由 API 层强制**：Adapter 可以不看 `timeoutMs`，但 Runtime 必须在超时后 reject `timeout`，并允许 Adapter 稍后完成（结果丢弃）。 |
| E6 | **取消是正常路径**：`signal` 触发后 reject `cancelled`；不得记错误日志。 |
| E7 | **`message` 不参与逻辑**：可本地化、可变化；任何 `message` 内容匹配都是 bug。 |
| E8 | **一致性校验在 Runtime**：能力/功能/返回值三者矛盾时（如 `capability.battery === "no"` 却返回 `BatteryStatus`），Runtime 记 `io`/`invalid` 并拒绝该 Adapter 的后续调用（fail-fast，而不是让 Shell 面对矛盾状态）。 |

### 4.1 每个域的「必须实现 / 可以拒绝」矩阵

| 方法 | `unsupported` 允许 | `unavailable` 允许 | 说明 |
|---|:--:|:--:|---|
| `capability.get/list/has` | **否** | 否 | 永远返回三态，不 reject（除了 `invalid`：未注册 id） |
| `feature.get/list` | 否 | 否 | 同上 |
| `display.info` | 否 | 否 | Shell 没有它无法布局 |
| `display.getBrightness` | 是 | 是 | |
| `display.setBrightness` | 是 | 是 | |
| `display.setRotation` | 是 | 是 | |
| `display.setOn` | 是 | 是 | |
| `input.facts` | 否 | 否 | 至少能回答「全 false + mode=dpad」 |
| `input.openTextSession` | 是 | 是 | 拒绝时 Shell 可用自带键盘 |
| `input.feedback` | 是 | 是 | |
| `audio.state` | 是 | 是 | 无音频硬件的设备 |
| `audio.setVolume` | 是 | 是 | |
| `audio.setMuted` | 是 | 是 | |
| `storage.collections` | 否 | 否 | 可为空数组 |
| `storage.list/stat/read` | 是（集合不存在） | 是 | |
| `storage.writeAppFile` 等 | 否 | 是 | Shell 没有私有区就无法保存状态 |
| `battery.status` | 是 | 是 | |
| `power.idlePolicy/setIdlePolicy` | 是 | 是 | 无休眠的设备仍可有息屏 |
| `power.suspend` | 是 | 是 | |
| `power.shutdown/reboot` | 是 | 是 | |
| `power.setAlarm/clearAlarm/alarm` | 是 | 是 | |
| `network.wifiState` | 是 | 是 | |
| `network.setWifiEnabled` | 是 | 是 | |
| `network.scanWifi/joinWifi/forgetWifi` | 是 | 是 | |
| `network.bluetoothState/setBluetoothEnabled` | 是 | 是 | |

「不允许 `unsupported`」的那几行，是 Shell 布局与渲染的**最小依赖集**。这也是为什么 `display.info` 被列为必需：今天的 Shell 直接从 profile 常量里拿 360×240（`RNX hello/main.tsx` 的 `ROWS = 12`、`w-[360px] h-[240px]` 布局），一旦平台分辨率不同就必须改 Shell 源码——这正是要消除的耦合。

---

## 5. 反泄漏审计（可执行）

在 `pocket-shell` 与 `pocket-platform-api` 两个仓里，以下模式**必须零命中**（CI 一条 `grep`）：

```
/sys/        /proc/        /dev/        /run/        /storage/
/dev/dri     /dev/fb      /dev/input   /dev/tty
mmcblk       tty7         DRM          KMS          fbdev        evdev
amixer       pactl        wpactl       nmcli        bluetoothctl
systemctl    systemd-run  rocknix-services           heya-control
usbgadget    dialog       htop         ranger       vim
H700         A133         RG34XX       RG35XX       RG40XX      CubeXX
M21          FiiO         bengal       sunxi        Allwinner    Snapdragon
rocknix      Rocknix      BaseOS       baseos       Android      android
```

三点说明：

1. `android` 出现在 `pocket-platform-api` 里**也必须为零**——Adapter 的名字可以由使用者自取，但契约类型名、枚举值、错误码里不得出现。
2. 例外只有两类，且必须在 CI 白名单里逐条登记：`pocket-shell/tests/fixtures/**`（假路径由 mock 后端解释）、以及注释中引用本仓外的 issue/PR 编号。
3. 平台名出现在**日志字符串**里可以，但只能在 Runtime 层（Adapter 自报的 `adapter` 字段），不得进 Shell 类型。

---

## 6. 与 PocketJS 现有能力的重叠与处置

| PocketJS 已有 | 本文档的做法 | 理由 |
|---|---|---|
| `hasFeature()` / `platform.features`（`PKT/framework/src/platform.ts:35`） | **保留**，但它表达的是**构建期**的 guest API 可用性，不是设备能力 | 它是编译期常量；设备能力是运行期值 |
| `contracts/spec/platform-types.ts` 的 `POCKET_CAPABILITIES`（`:155-280`） | **保留**，通过映射表与本文 Capability 词表对应（04 §5） | admission 依赖它，不能改 |
| `framework/src/service-client.ts`（`:30-131`） | 不作为 Platform API 的传输 | 它是 JSON 服务协议，面向 companion；与本 API 的「域方法」语义不同 |
| `framework/src/wifi.ts`（`:15-22` 的 `WifiOps`） | 作为 `Network` 域的**对照**：`status/setEnabled/connect/scan/join/forget` 的形状被沿用，但语义改为三态 + `PlatformError` | 避免发明第二套词汇 |
| `framework/src/fs-api.ts`（`:46-57` 的 `FsOps`） | 作为 `Storage` 域的对照：`read/write/list/stat` 的**分页与上限思想**沿用；但根目录从「应用沙箱」扩展为「集合根 + 应用私有区」 | 今天 Library 用的是 `__library` 原始路径桥，比 `FsOps` 更弱 |
| `framework/src/audio-api.ts`（`:28-41`） | 明确**不**由本域接管 | 播放属于 guest 命名空间 |
| `framework/src/launcher.ts`（`:36-56` 的 `appTable/appLaunch/appShot/appClose`） | 明确**不**由本域接管（第九个域里没有 App） | 应用切换是 Runtime/PocketJS 的既有能力；本阶段不扩域 |

这条边界很重要：**本阶段的九个域就是 issue 列出的九个**，不借机扩大范围。

---

## 7. 未决

| id | 问题 | 影响 |
|---|---|---|
| Q1 | `Storage` 是否需要写用户集合（今天 Library 只读，进度写私有区） | 决定是否需要 `write(collection,…)`，以及配额语义 |
| Q2 | `Network` 是否要暴露以太网/USB 网络（`pocket-settings` 已有 `Ethernet` 能力） | 影响词表，但不影响签名骨架 |
| Q3 | `Power.setIdlePolicy` 的单位与「永不」的编码（0 还是 null） | 0 与 null 混用会产生第二套语义；建议 0 |
| Q4 | `display.info().rotationDeg` 是「相对设备默认」还是「相对自然方向」 | Shell 若做旋转动画需要明确 |
