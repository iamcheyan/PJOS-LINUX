# 08 — 方案对比与被否决的理由

> 本文件记录**考虑过但没采用**的方案，以及为什么。
> 目的不是自证正确，而是让第 51 台设备时的维护者知道：
> "某个看起来更简单的做法，我们已经试过推演并否决了，理由是 X"。
>
> 每条否决都给出：方案、它解决什么、为什么否决、什么条件下应该重新考虑。

---

## 0. 评审标准

所有方案按四个维度打分，权重来自 issue 的核心判据
（"如果增加第 51 台设备，是否需要修改已有设备的代码？"）：

| 维度 | 含义 | 权重 |
|---|---|---|
| **S51** | 新增第 51 台设备是否需要改已有设备 | 最高 |
| **迁移风险** | 能否切成可独立合并、可发布的步骤 | 高 |
| **H700 零变化** | 现有 11 台设备的行为能否保持不变 | 高 |
| **长期成本** | 50 台时的日常维护负担 | 中 |

---

## 1. 方案 A（采纳）：两级 BSP + DAL + baseosctl

见 `02`–`06`。

| 维度 | 评价 |
|---|---|
| S51 | **不需要改已有设备**（同 SoC 只加 `board.json`；新 SoC 加 `bsp/<soc>/`） |
| 迁移风险 | 9 步，前 4 步不改镜像内容 |
| H700 零变化 | 内容级可证（`07 §3`） |
| 长期成本 | 5 份板级事实收敛为 1 份 + 1 份 SoC 事实 |

**代价（诚实列出）**：

- 9 个迁移步骤，其中 M5–M7 需要真机验证；
- 新增两层间接（`soc.json` 深合并、`dal.sh`）；
- 需要一个 lint 守住边界，lint 本身要维护；
- `baseosctl` 是一个新进程，冷启动有成本。

---

## 2. 方案 B（否决）：单级 `bsp/<board>/`，无 SoC 层

### 方案

```
bsp/
  rg34xx/     board.json + kernel/ + harvest.list + overlay/ + src/
  rg34xxsp/   board.json + kernel/ + harvest.list + overlay/ + src/
  ... (11 个，每个都完整)
```

### 它解决什么

- 边界极简："一块板一个目录"，没有合并规则；
- 新增设备 = 复制一个目录改字段；
- lint 判据简单：板名只在 `bsp/<board>/` 下。

### 为什么否决

**11 台 H700 设备共享的东西会被复制 11 次**，而这些共享物是**大件**：

| 共享物 | 大小/规模 | 复制 11 次的后果 |
|---|---|---|
| `harvest.list` | 142 行，全部是厂商 rootfs 路径 | 改一条公共路径要改 11 处 |
| 内核补丁源码 | `h700_speaker_amp.c`（数百行）+ `h700_late_usb.c` | 11 份源码副本，编译 11 次 |
| `profiles.json` | 11 条已审计内核（**每条本来就不同**） | 这条不共享，但**审计流程**共享 |
| SoC 节点映射 | 37 种节点模式（`01-audit.md §2 P0-5`） | 11 份相同映射 |

更关键的是 `01-audit.md §3.2` 的定量结论：现状已经是"11 台 × 5 张表 = 55 处手工登记"。
方案 B 会把它变成"11 台 × 5 张表 × 各自独立"，**不减少任何手工登记**，
只是把它们搬进各自的目录。**手工登记的数量才是问题，位置不是。**

而且它**没有回答**"同 SoC 的第 12 台设备要改什么"——答案是"复制第 11 个目录"，
即"改已有设备"的一种变形（复制即分叉）。

### 什么条件下应该重新考虑

如果未来出现"每台设备的 SoC 都不同"的产品线（50 台 = 50 个不同 SoC），
SoC 层退化为 1:1 映射，那时两级结构就是纯开销，应该合并为单级。

**当前证据不支持这一点**：`devices.json` 的 11 条里，`baseos_device` 只有 6 个值
（`rg28xx`、`rg34xx`、`rg35xx`、`rg40xx`、`cube`、`rgsp`），
说明硬件平台高度共享。

---

## 3. 方案 C（否决）：不做 BSP，只把 `devices.json` 扩展成"大 profile"

### 方案

保持单目录结构，把 `devices.json` 从 10 个字段扩到 80 个字段，覆盖
面板/输入/音频/电源/网络/存储/节点映射/内核模块/harvest 清单。

### 它解决什么

- 改动最小：一个 JSON 文件，一个 schema；
- 没有新目录、没有合并规则、没有 lint；
- 构建脚本只需读更多字段。

### 为什么否决

三条独立理由，每条都能指向现状证据：

**C-1：profile 会变成"配置文件里的代码"。**
`01-audit.md §2 P0-1` 的 `overlay/` 里有 14 个文件含 SoC 逻辑，
其中 `rcS:185-251` 是 **80 行带时序的 shell**（stale SDIO 丢弃、两次尝试、
慢电台标记）。这段逻辑**无法**表达成 JSON 字段——除非发明一个小型 DSL，
那就是"在 JSON 里写代码"，比现状更难维护。

**C-2：内核补丁无法放进 profile。**
`src/h700-speaker-amp/` 是 C 源码 + 编译流程 + 8 个符号偏移
（`src/h700-speaker-amp/profiles.json`）。它必须住在某个目录里，
不能塞进 `devices.json`。

**C-3：harvest 清单无法放进 profile。**
142 行路径，其中含内核版本号（`manifest/harvest.list:136-137`）。
把它变成 JSON 数组会让 diff 不可读（现在按 `##` 分节，人能扫）。

**结论**：方案 C 只能覆盖"字段型"差异（面板、开关），覆盖不了"代码型"差异
（初始化序列、内核补丁、harvest 基线）。而后者正是 `01-audit.md` 的 P0-1/P0-2/P0-3。

### 什么条件下应该重新考虑

如果未来的设备差异**全部**是字段型（例如同一 SoC 的 OEM 变体，只改屏幕和外壳），
那么一个扩展的 profile 就够了。此时 BSP 目录可以退化成一个 JSON 文件。

**当前证据不支持**：`docs/14-trimui-smart-pro-port.md:19-58` 明确列出
新设备需要改 `overlay/rcS`、`src/`、PocketJS——这些都不是字段。

---

## 4. 方案 D（否决）：BSP 作为可下载的二进制包

### 方案

`bsp/` 不放在 git 里，而是作为独立 artifact 发布（像 `manifest/prepared/`
的 prepared cache 那样，`cache-pack.sh:13-18` 描述的 zstd bundle）。
构建时 `fetch-bsp.sh` 下载对应板的 BSP 包。

### 它解决什么

- 仓库不增长（50 台设备的 boot-prefix/harvest 不进 git）；
- BSP 可以独立版本化、独立发布；
- 与现有 `fetch-prepared.sh` 的模式一致。

### 为什么否决

**D-1：schema 未稳定前分发会固化错误设计。**
`docs/15-bsp-architecture.md:359` 已经写明了这一点：
"把 BSP 做成可远程下载的二进制包（在 schema 稳定之前分发只会固化错误设计）"。
本设计的 schema 是全新的（`pjos.board/1`、`pjos.soc/1`），
在第 3 台设备验证之前分发，等于让第一个 BSP 包变成事实标准。

**D-2：`bsp/` 里大部分内容必须可 diff。**
`board.json`、`soc.json`、`harvest.list`、内核补丁源码——这些都需要
code review。打成二进制包后，review 变成"看 sha256"。

**D-3：现有机制已经解决了"仓库增长"问题。**
`manifest/prepared/` 只存 `source.json`（6 KB/台）+ 一个 bundle 的 sha256，
而 bundle 本身在 GitHub Release 上（`cache-pack.sh:22`）。
`bsp/` 里的 `board.json` 是**几百字节**，`soc.json` 是**几 KB**。
50 台设备 ≈ 50 × 2 KB ≈ 100 KB。**不需要优化。**

### 什么条件下应该重新考虑

如果 `bsp/` 里出现**大于 1 MB 且不可 diff 的二进制**（例如自建的内核 Image、
DTB blob）。届时可以只把那一部分外置，而 `board.json`/`soc.json` 仍留在 git。

**当前设计已经预留**：`soc.json` 的 `dtb.source = "stock"` 表示 DTB 来自厂商固件，
不存进 `bsp/`；内核补丁是**源码**不是二进制。

---

## 5. 方案 E（否决）：DAL 做成常驻守护进程 `baseosd`（v1 就做）

### 方案

`baseosd` 在 `rcS` 里启动，持有所有硬件状态，通过 Unix socket 提供服务。
`baseosctl` 是它的客户端。

### 它解决什么

- 状态只读一次（不用每次 fork 重读 `/sys`）；
- 可以推送事件（HDMI 热插拔、电量变化）；
- 多个消费者共享一份状态。

### 为什么否决（v1）

**E-1：引入第二个"谁负责硬件"的答案。**
现在 `overlay/etc/inittab:4` 是 `::respawn:/sbin/frontend-session`。
加一个常驻进程后，"硬件状态"有两个潜在持有者（`baseosd` 的缓存 vs 内核的真相）。
缓存不一致时，谁的答案是权威？

**E-2：失败模式变差。**
`baseosd` 挂了，整机失去硬件访问。而现在的 sh 直读节点，
单个脚本失败只影响它自己。`docs/06-status-and-lessons.md` 的
"Open work" 里已经有一条"Read-only rootfs after initialization for
power-loss resilience"——说明可靠性是关注点，不应该反向增加单点。

**E-3：v1 没有消费方需要它。**
事件推送的唯一候选消费方是 PocketJS，而 PocketJS 通过 `baseosctl` 的
**一次性查询**已经够用（状态栏刷新频率是秒级，不是事件级）。

**E-4：启动预算。**
`overlay/etc/init.d/rcS:2-3` 写明"Normal-boot budget: well under one second"。
多一个进程 + socket + 就绪握手，与这个预算冲突。

### 什么条件下应该重新考虑

- 出现**必须**事件驱动才能工作的需求（例如 HDMI 热插拔要即时切换，不能轮询）；
- `baseosctl` 的冷启动成为可测量的性能问题（`06 §9` 的 < 50 ms 目标不达标）；
- 需要跨进程共享**可变**状态（例如"当前音量"由多个应用并发修改）。

**当前设计已经预留**：`03 §1.2` 说明 DAL 是库，函数签名与守护进程版本兼容；
届时加 `baseosd` 不需要改任何调用方。

---

## 6. 方案 F（否决）：Capability 用 bitmask 作为唯一表达

### 方案

`/etc/pjos/caps.json` 改成单个整数（bit 0 = wifi，bit 1 = bluetooth，…），
与 `05 §6.2` 的 Feature bitmask 同构。

### 它解决什么

- 极小（4 字节）；
- 读取零成本（不用 JSON 解析）；
- 与嵌入式习惯一致。

### 为什么否决

**F-1：三态需要 2 位/项，11 项 = 22 位，可读性崩溃。**
`04 §2` 的核心是 `unknown ≠ no`。bitmask 天然只有两态。
要表达三态必须每项 2 位，于是 `0b01` = yes、`0b10` = no、`0b00` = unknown，
`0b11` 保留。一个 22 位的整数，人无法阅读，diff 无法 review。

**F-2：`board.json` 已经是 JSON，加一个 bitmask 就是两套事实。**
`02 §5.3` 规定 `capabilities` 必须显式给全部键。如果同时维护 bitmask，
两者会漂移——这正是 `01-audit.md §1` 批判的"5 份副本"问题重演。

**F-3：Capability 的读取频率低。**
它只在应用启动时读一次（`04 §7.3`）。JSON 解析的几百微秒不是问题。

**对比**：Feature 为什么**可以**有 bitmask（`05 §6.2`）？
因为 Feature 的 bitmask 是**可选的快速路径**，JSON 仍是权威形式，
且明确标注"有损编码，需要区分 no/unknown 的消费方必须用 JSON"。
Capability 没有"快速路径"的需求，所以不需要。

### 什么条件下应该重新考虑

如果出现一个**无法解析 JSON** 的消费方（例如某个 8 位 MCU 固件需要读能力）。
届时加一个**派生**的 bitmask 文件（由 JSON 生成，单向），而不是替换 JSON。

---

## 7. 方案 G（否决）：用 systemd/udev 替代自建 DAL

### 方案

把 busybox init 换成 systemd，用 udev 规则 + systemd units 表达板级差异。

### 它解决什么

- udev 天然是"设备节点 → 语义名字"的映射层（`/dev/disk/by-role/...`）；
- systemd 有依赖图、重启策略、状态查询（`systemctl show`）；
- 不需要自己发明 DAL 与 `baseosctl`。

### 为什么否决

**G-1：启动预算。**
`rcS:2-3` 的预算是"well under one second"。systemd 的冷启动
（含 udev coldplug）在这个量级上不可行。现有设计为此做了大量优化：
`rcS:107-115` 后台加载 GPU/USB、`rcS:52-62` 把 `/usr/lib` 放进 squashfs、
`docs/09-boot-profiling.md` 整篇在讲这个。

**G-2：镜像体积。**
`manifest/harvest.list` 已经是"按 ldd 闭包精确收割"（`manifest/harvest.list:6-8`）。
加 systemd 会引入一整套依赖（dbus、libsystemd、udev 规则集）。
注意：`manifest/harvest.list:96` 确实收了 `libsystemd.so.0`，但那是**厂商 rootfs 里
被别的程序依赖**的库，不是要跑 systemd 本体。

**G-3：现有代码已经在绕过 systemd。**
`overlay/usr/sbin/systemctl` 是 87 行的**兼容 shim**，
只为让 NextUI 的脚本能跑（`systemctl:3`）。引入真 systemd 会让这个 shim
变成"真 systemd 的包装"，而不是消除它。

**G-4：`01-audit.md §2 P1-1` 的教训。**
应用侧的问题不是"缺少服务管理器"，是"应用自己探测硬件"。
systemd 不解决这个问题——它只把探测点从应用移到 udev 规则，
而 udev 规则本身也是板级配置，同样会散落。

### 什么条件下应该重新考虑

如果产品的启动预算放宽到 5 秒以上，且需要复杂服务编排
（例如多个常驻服务有依赖关系与重启策略）。**当前证据不支持**：
`validate-on-device.sh:46` 的验收标准是"2.50s frontend-exec budget"。

---

## 8. 方案 H（否决）：per-target 独立构建流水线

### 方案

每台设备一条 CI 流水线、一份构建脚本、一份产物。

### 它解决什么

- 完全隔离，一台设备的问题不影响其它；
- 每台设备可以有自己的构建参数。

### 为什么否决

`docs/15-bsp-architecture.md:359` 已经否决过：
"为每台设备做独立的镜像构建流水线（会让'20 台设备'变成 20 条流水线）"。

补充证据：`build-all.sh:60-83` 现在是**一个循环遍历所有 target**，
共享 `work/tools`（`:42-58` 的 staleness 检查）。50 条流水线会让
共享工具的构建重复 50 次，而 `build-tools.sh` 里最慢的是 curl 与 e2fsprogs
的静态编译（`build-tools.sh:60-120`）。

**这与方案 B 是同一个错误的两个形态**：把"共享"误认为"独立"。

### 什么条件下应该重新考虑

如果某台设备的构建**无法**与其它设备共享工具链（例如完全不同的架构）。
当前 11 台都是 aarch64，共享成立。

---

## 9. 方案 I（部分采纳）：`harvest.list` 按 SoC 拆分

### 方案

`manifest/harvest.list` → `bsp/<vendor>/<soc>/harvest.list`，一个 SoC 一份。

### 状态：**采纳**（M5）

这不是"否决"，但值得记录**为什么是 SoC 级而不是板级**。

### 为什么 SoC 级

`01-audit.md §2 P0-2` 指出：清单的基线是**厂商 rootfs 的 ldd 闭包**
（`manifest/harvest.list:6-8`："the on-device ldd closure of every NextUI ELF +
kept daemons (2026-07-19, RG40XXV stock V1.1.1.0)"）。

同一 SoC 的 11 台设备，厂商 rootfs 是**同一个固件家族的变体**，
ldd 闭包基本相同（`cache-pack.sh:15-16` 实测："2406 of 2409 harvest files
are identical across the fleet"）。差异只在板级的 wifi/bluetooth 开关，
这已经由 `tools/prepare_stock.py:489-499` 的 `omission_allowed` 处理。

所以：

- **SoC 级**：清单本身（哪些 soname、哪些 daemon）；
- **板级**：裁剪规则（有没有 wifi/bluetooth）。

这与 `02 §4` 的 `soc.json` 里 `harvest.list` + `board.json` 里
`capabilities` 的分工一致。

### 什么条件下应该改成板级

如果同一 SoC 的两台设备厂商 rootfs **不同源**（例如不同 OEM 各自定制）。
届时 `board.json` 可以声明 `harvest.list` 覆盖（`02 §4.1` 的深合并规则已支持）。

---

## 10. 方案 J（否决）：先用 A133 验证架构，再重构 H700

### 方案

先移植第二块 SoC（Smart Pro），在实践中发现架构需求，然后回头重构 H700。

### 它解决什么

- 避免"凭空设计"；
- 有真实需求驱动。

### 为什么否决

**J-1：前置条件不满足。**
`docs/14-trimui-smart-pro-port.md:17` 明写："RG34XX 有这份，Smart Pro 需要
确认是否有官方 StockMod 固件"。`:90-93` 更直接："**没有 StockMod** → 这条路走不通"。

也就是说：**A133 移植的第一步就无法确认可行**。以它为主线会让整个计划
卡在一个未验证的外部依赖上。

**J-2：H700 的行为无法保证。**
任务约束是"H700 当前行为完全不变"。如果先做 A133，H700 的代码会被
"顺手"改动（为了让两者共用），而这些改动没有 H700 的验收。

**J-3：架构失败无法被发现。**
`docs/15:365` 的判据是："加第二台设备时，如果 PR 里出现了 `overlay/` 或
PocketJS 仓库的改动，说明架构没做对"。如果 A133 移植时 `overlay/` 还没
被拆分，这个判据无法应用——因为**必然**要改 `overlay/`。

### 本设计的替代做法

用**fake board**（`07` 的 M9）验证架构，而不是用第二块真 SoC：

- `fake-drm` 板：验证"换显示后端不改代码"；
- `fake-minimal` 板：验证降级路径。

这提供了 A133 能提供的**架构验证**，而不依赖未确认的厂商固件。
真机验证留给 M5 之后的 A133 移植（那时架构已就位，失败可归因）。

### 什么条件下应该重新考虑

如果确认了 Smart Pro 有可用的 StockMod 固件，且 H700 的 BSP 拆分（M2–M5）已完成。
那时 A133 就是"验证架构"的正式手段，而不是"设计架构"的手段。

---

## 11. 汇总

| 方案 | S51 | 迁移风险 | H700 零变化 | 长期成本 | 结论 |
|---|---|---|---|---|---|
| A 两级 BSP + DAL + baseosctl | 优 | 中（9 步，前 4 步不改镜像） | 可证 | 低 | **采纳** |
| B 单级 `bsp/<board>/` | 良 | 低 | 可证 | **高**（共享物复制 11 次） | 否决 |
| C 扩展 `devices.json` | **差**（覆盖不了代码型差异） | 低 | 可证 | 中 | 否决 |
| D BSP 二进制包 | 良 | 中 | 可证 | 低 | 推迟（schema 稳定后） |
| E `baseosd` 常驻（v1） | 良 | 高 | 难证 | 中 | 推迟（v2 可选） |
| F Capability bitmask | 良 | 低 | 可证 | 中（三态丢失） | 否决 |
| G systemd/udev | 良 | **极高** | 难证 | 中 | 否决 |
| H per-target 流水线 | 差 | 高 | 可证 | **极高** | 否决 |
| I harvest 按 SoC 拆分 | 良 | 低 | 可证 | 低 | **采纳**（M5） |
| J 先做 A133 | 良 | 极高（前置未确认） | 难证 | 高 | 否决 |

**被采纳的组合 = A + I。** 被推迟的两个（D、E）都在设计里预留了扩展点，
不需要未来返工。

---

## 12. 重新评估的触发条件（写给第 51 台设备时的维护者）

如果出现以下任一情形，本文的否决结论**应该**被重新审视，而不是当作教条：

| 触发条件 | 需要重新评估的方案 |
|---|---|
| 50 台设备的 SoC 各不相同 | B（单级可能更合适） |
| 设备差异全部变成字段型 | C（扩展 profile 即可） |
| `bsp/` 出现 > 1 MB 不可 diff 的二进制 | D（部分外置） |
| 需要事件驱动（HDMI 热插拔即时响应） | E（`baseosd`） |
| 出现无法解析 JSON 的消费方 | F（派生 bitmask 文件） |
| 启动预算放宽到 5s+ | G（systemd） |
| 某设备无法与其它共享工具链 | H（单条流水线） |
| 确认 A133 固件可用且 M2–M5 已完成 | J（真机验证） |
