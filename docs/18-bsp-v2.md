# 18 — BSP v2：多设备发行版平台架构

> 状态：**设计评审稿**。本阶段只做架构设计，不含实现代码。
> 前序：[15 — BSP 与多设备架构](15-bsp-architecture.md)（v1 审计与初版设想）。本文是它的严格化版本（v2）：
> 补齐 v1 缺失的 **Feature 体系**、**DAL 契约**、**`baseosctl` 全量 API**、**Device Profile v2 正式 schema**、
> **构建流水线**、**假板**与**多设备 CI**，并把「新增设备不许改别处」从口号变成**可失败的架构门**。
> 评审视角：维护 50+ 台设备。每一条设计都要通过 [§13.1 第 51 台设备测试](#131-第-51-台设备测试)。

---

## 0. 结论先行

1. **今天的 11 个 target 不是 11 台设备，而是 1 个 BSP 的 11 个变体。** 证据：`cache-pack.sh` 的注释记录
   「每台设备的 boot prefix 有 103 MiB 逐字节相同，2409 个 harvest 文件里 2406 个相同」；`src/h700-speaker-amp/profiles.json`
   里 11 条 ABI 记录对应的是少数几个内核变体。多设备架构的**第一次真实考验不是第二台 H700，
   而是第二块 SoC**。现在所有「其实只有一份」的假设，会在那一天同时失效。
2. 设备差异有 **5 个轴**（厂商引导链 / 内核 ABI / 用户空间闭包 / 硬件拓扑 / 发行版语义）。今天发行版逻辑同时依赖全部 5 个轴。
   其中前 3 个必须在架构上**被完全隐藏**，发行版只能看见第 4、5 轴的**声明数据**。
3. **三分离**：BSP 是物理事实，Profile 是产品事实，Feature 是发行版承诺。
   **行为只允许出现在 distro**；BSP 与 Profile 里出现行为 = 例外证据（设计缺陷）。
4. 推导链必须是**纯函数 + 数据**：
   `Board → Profile → Capability → Feature → DAL → baseosctl`。
   构建期生成 `/etc/pjos/*.json`，运行期**只读**。**禁止探测**（checking is not knowing）。
5. DAL 的实现是**一份代码 + 每板一份节点映射表**。任何 `if board == …` 都是架构失败。
6. Capability 三态 `yes|no|unknown`；Feature 三态 `declared|resolved|observed`。应用**严禁推断 Feature**。
7. `baseosctl` 是唯一正式系统接口：机器可读输出、稳定字段名、稳定 exit code（含 `unsupported=3`）。
8. Device Profile v2 是**正式 JSON Schema**，未知字段即失败，缺字段产出 `unknown` 而不是静默默认。
9. 构建只有一种坐标：`--board <id>`。SoC 层构件按 SoC 缓存复用，板层只做增量。
10. **所有架构承诺都变成可执行的 CI 门**：板名扫描、schema 校验、feature 冲突、H700 字节不变门、假板「51 号设备」测试。
    没有门的承诺，6 个月内必然腐烂。
11. 迁移分 9 步，每步可独立合并、可回滚；H700 的行为由**逐字节哈希门**守护。

### 0.1 本文与 docs/15 的关系

| 主题 | docs/15（v1） | 本文（v2） |
|---|---|---|
| 现状审计 | §1–§2 定性列举 10 条 | §1 逐条编号证据（L01–L24）+ 五轴模型 + 成本曲线 |
| BSP 目录 | §4.1 构想 | §2 + §8 完整包布局、准入判据、板名禁用算法、`bsp.lock` |
| DAL | 未定义（只在图里出现） | §3 完整边界：节点映射、解析算法、错误语义、backend 抽象 |
| Capability | §6 提议三态 | §4 命名空间、来源优先级、冲突检测、declared vs verified |
| Feature | **缺失** | §5 完整体系（registry / 解析算法 / 首批 16 个 feature 的逆向映射） |
| baseosctl | §6.4 一行命令表 | §6 全量 API 契约（字段、类型、exit code、写入语义、契约测试） |
| Profile | §5 字段表（散文） | §7 正式 JSON Schema + 继承模型 + v1→v2 映射 |
| 构建流水线 | §4.4 三行 | §9 阶段表、12 个新门、缓存键、确定性 |
| 假板 | 半句话 | §10 假板族 + fixture 树 + 「51 号设备测试」生成器 |
| 多设备 CI | §7 Phase 6 一行 | §11 T0–T4 五层 + 矩阵 + 预算 + 发布矩阵 |
| 迁移 | §7 六个 phase | §12 九步，含退出条件/回滚/依赖图/持续架构门 |

---

## 1. 当前架构问题审计

### 1.1 审计口径

本审计只认**可复核的证据**：文件路径 + 具体行为。每条结论都标注它属于哪个轴（V1–V5）：

| 轴 | 含义 | 谁应该拥有 | 发行版可见性 |
|---|---|---|---|
| **V1** | 厂商引导链（StockMod 镜像、boot-prefix、GPT 几何、boot0/原生加载器） | BSP | 不可见（只能见到「分区角色」） |
| **V2** | 内核 ABI（release/banner/modversions/符号偏移） | BSP | 不可见 |
| **V3** | 用户空间闭包（harvest 白名单、soname 集合、GPU blob、daemon 集合） | BSP | 不可见（只能见到「能力→需要哪些文件」） |
| **V4** | 硬件拓扑（面板、输入、PMIC、音频、无线、存储控制器、LED） | BSP + Profile | 可见（声明数据） |
| **V5** | 发行版语义（能力承诺、feature、启动阶段、更新契约、UI 需要的句柄） | 发行版 | 可见（推导产物） |

**架构判据**：发行版代码里出现 V1/V2/V3 的事实 = P0；出现 V4 的事实但以「数据」形式 = 允许；
出现 V4 的事实但以「代码分支」形式 = P1；出现板名 = P0（除非在 `bsp/` 或历史文档里）。

### 1.2 「谁在描述设备事实」矩阵

| 层/文件 | V1 | V2 | V3 | V4 | V5 | 结论 |
|---|---|---|---|---|---|---|
| `devices.json`（11 条，10 字段） | — | — | — | 部分 | 极少 | 字段太少，装不下真实差异，于是差异外溢 |
| `manifest/prepared/<target>.json` | ✔ 几何 | — | ✔ 哈希 | ✔ wifi/bt | — | **第二个事实源**，与 `devices.json` 重复 |
| `manifest/harvest.list`（全局一份） | — | — | ✔ | — | — | 内容为 H700 闭包，却无 SoC 归属 |
| `work/<target>/{boot-prefix.img,source.json}` | ✔ | — | — | — | — | 正确：厂商输入按 target 隔离 |
| `overlay/etc/init.d/rcS`（393 行） | — | ✔ | ✔ | ✔ | ✔ | **五轴全混**：H700 模块名、AXP 节点、WiFi 时序常量、TF2 控制器路径、feature 开关 |
| `overlay/usr/sbin/frontend-session` | — | — | — | ✔ | ✔ | 含 `.system/h700/...` 板名路径、`/dev/mali0`、分区号回退 |
| `src/`（含 `h700-*`、`axp-off.c`、`boot-clock.c`） | — | ✔ | — | ✔ | — | 内核 ABI 强绑定，且以板名命名 |
| `tools/prepare_stock.py` | ✔ | — | — | — | — | 硬编码 `EXPECTED_NAMES` 与「unexpected H700 GPT table」断言 |
| `build-rootfs.sh` | — | ✔ | ✔ | ✔ | ✔ | 无条件安装 `h700_*.ko`；写死 `BASEOS_PLATFORM=h700` |
| PocketJS（另一仓库，见 [14](14-trimui-smart-pro-port.md)） | — | — | — | ✔ | ✔ | 应用侧探测 fb/evdev/PMIC，属最大泄漏 |

### 1.3 泄漏清单

> 编号供后续 PR 引用（例如「本 PR 关闭 L07」）。级别：**P0** 阻断多设备；**P1** 造成隐性错误；**P2** 长期债。

| # | 位置 | 事实 | 轴 | 问题 | 级别 |
|---|---|---|---|---|---|
| L01 | `overlay/etc/init.d/rcS` | `/sbin/insmod /lib/modules/h700_late_usb.ko` | V4 | 板级模块名写进通用 init | P0 |
| L02 | `overlay/etc/init.d/rcS` | `/sys/class/power_supply/axp2202-battery/{os_sleep,boot_mode}` | V4 | PMIC 型号写进通用 init；`os_sleep=16` 是**板级策略常量** | P0 |
| L03 | `overlay/etc/init.d/rcS` | WiFi 上电时序常量 `wifi_off_cs=500 / wifi_cut_cs=185 / wifi_first_cs=225` | V4 | 厂商内核电源行为参数写死在发行版 init | P0 |
| L04 | `overlay/etc/init.d/rcS` | `/sys/class/misc/sunxi-wlan/rf-ctrl`、`/sys/bus/sdio/devices/*`、`8821cs.ko`、`rtl_btlpm.ko` | V4 | 无线子系统拓扑与模块名 | P0 |
| L05 | `overlay/etc/init.d/rcS` | `/sys/devices/platform/soc/sdc2/mmc_host/mmc*`（TF2 探测） | V4 | SoC 控制器实例路径 | P1 |
| L06 | `overlay/etc/init.d/rcS` | `/dev/mmcblk0p{5,6,7}`、`/dev/mmcblk1p1` | V1 | 分区号即厂商布局，属 BSP | P0 |
| L07 | `overlay/usr/sbin/frontend-session` | `$SD/.system/h700/paks/MinUI.pak/launch.sh` | V5 | **板名出现在卡上前端目录**，等于把 SoC 名固化进用户数据布局 | P0 |
| L08 | `overlay/usr/sbin/frontend-session` | `while [ ! -e /dev/mali0 ]` | V4 | GPU 节点名进运行时 | P1 |
| L09 | `overlay/usr/sbin/baseos-charger` | `axp-off`、`/sys/class/rtc/rtc0/since_epoch`、`/dev/mmcblk0p6` | V2/V4 | PMIC 写入工具与分区号耦合 | P1 |
| L10 | `overlay/usr/sbin/baseos-diag` | `$ROOT/sys/class/power_supply` 下 `axp[0-9]*` 正则识别 PMIC | V4 | 靠型号前缀猜设备 | P1 |
| L11 | `build-rootfs.sh` | `install ... h700_speaker_amp.ko`、`h700_late_usb.ko` 无条件 | V2 | 名字与存在性都属 BSP | P0 |
| L12 | `build-rootfs.sh` | `BASEOS_PLATFORM=h700`、`PRETTY_NAME="… (h700)"` | V4 | 发行版身份被写死为 SoC 名 | P0 |
| L13 | `tools/prepare_stock.py` | `EXPECTED_NAMES` 分区名序列 + `unexpected H700 GPT table` 断言 | V1 | 厂商布局契约属 BSP | P0 |
| L14 | `tools/prepare_stock.py` | `omission_allowed()` 直接读 `profile["wifi"]/["bluetooth"]` | V5 | capability 与 harvest 分类的耦合已经开始，但耦合在工具里而非数据里 | P1 |
| L15 | `manifest/harvest.list` | 单一全局清单，注释写明基线是 RG40XXV 的 ldd 闭包 | V3 | 第二块 SoC 直接裁错用户空间 | P0 |
| L16 | `src/h700-speaker-amp/profiles.json` | 每 target 一份 kernel sha256 + 符号偏移 | V2 | 内核升级/换 SoC 即失配；11 条记录按 target 而非按内核变体组织 | P0 |
| L17 | `src/h700-late-usb`、`src/axp-off.c`、`src/boot-clock.c`、`src/fbsplash.c` | 目录名/逻辑按 SoC | V2/V4 | 板级代码住在发行版根目录 | P0 |
| L18 | `devices.json` | 11 条 × 10 字段，`rg34xx` 与 `rg34xxsp` 的 `baseos_device` 相同 | V4 | 字段不足 → 差异外溢；复制粘贴已发生 | P0 |
| L19 | `manifest/prepared/<target>.json` | 另一份 `capabilities{wifi,bluetooth}` | V5 | 与 `devices.json` 双源，可漂移 | P1 |
| L20 | `PocketJS`（外仓） | `launch_frontend.sh` 探测 `/dev/dri/card0..1` → `/dev/fb0`，按名匹配 `ANBERNIC`，shim 写死 `axp2202-battery`、`enhance_bright`、`amixer` | V4/V5 | **应用层在做设备发现**，换设备要改应用仓库 | P0 |
| L21 | `baseosctl` | 不存在 | V5 | 没有唯一系统接口，语义散落在 5 个脚本 + 应用 shim | P0 |
| L22 | Capability/Feature | 只有 `BASEOS_WIFI/BASEOS_BLUETOOTH` 两个布尔值 | V5 | 应用无法查询「能不能做」，只能 try-and-fail | P1 |
| L23 | `tests/` | 50+ 个测试全部面向「当前这块板」，无 per-board 矩阵，无架构门 | V5 | 回归无法防，架构漂移无人发现 | P1 |
| L24 | `docs/` | 多处把 H700 事实写成通用事实 | V5 | 新维护者会把一台设备的结论当发行版结论 | P2 |

### 1.4 三个事实源的漂移风险（L18/L19）

同一件事实现在存在于三处，且**没有交叉校验**：

1. `devices.json` → `wifi: true`
2. `manifest/prepared/<target>.json` → `capabilities.wifi: true`
3. `src/h700-speaker-amp/profiles.json` → 内核 sha256（决定能不能真的驱动无线）

三者任意一个是旧的，构建就会产出一个「声明有 WiFi、实际没有」或「声明没有、白裁了闭包」的镜像。
v2 的解法不是「让它们同步」，而是**消灭重复**：capability 只有一个声明处（Profile/BSP 继承链），
`manifest/prepared` 只保留**校验过的事实快照**（用于 prepared cache 的可信锚），并在构建期做
`快照 == 推导结果` 的强一致检查（§4.2）。

### 1.5 「11 台设备其实是 1 个 BSP」的量化

| 观察 | 数据 | 含义 |
|---|---|---|
| `cache-pack.sh` | boot prefix 每台 103 MiB 相同；harvest 2409 个文件中 2406 个相同 | 11 个 target 共享同一份厂商内核与几乎同一份用户空间 |
| `profiles.json` | 11 条记录，内核 sha256 只有少数几个不同值 | 「ABI 表」实际是「内核变体表」，却按 target 组织 |
| `devices.json` | 10 个字段，其中 4 个（logo 宽高/旋转/wifi/bt）真正因板而异 | 板级差异极小，于是我们从没被迫设计抽象 |
| `harvest.list` | 只有一份，从未因 target 变化 | V3 轴从未被真正考验 |

**结论**：现有代码库里所有「设备无关」的错觉，都建立在「所有设备同 SoC、同内核、同闭包」这个隐含前提上。
v2 的设计目标就是**让这个前提显式化、可校验、可替换**，而不是等它在第 12 台设备上静默破裂。

### 1.6 成本曲线

新增设备当前成本（实测路径）：

```
厂商固件 → prepare-stock（BSP 输入）
        + devices.json 加一条            （Profile，字段不足）
        + manifest/harvest.list 新开一份  （V3，必须）
        + rcS 加 SoC 分支                （distro，必须改 → 架构失败）
        + src/ 新增 SoC 补丁 + ABI 表     （V2，必须）
        + PocketJS 改探测                （跨仓库，必须改 → 架构失败）
        + tests 新增（无矩阵）
= 触碰 6 个抽象层、2 个仓库
```

若把成本记作 `C(N) = a·N(distro分支) + b·N(profile) + c·N(soc) + d·N(app)`，
今天的 `a>0, d>0` 就是**架构缺陷项**：它们是随 N 线性增长且**跨仓库**的成本，最不可维护。
v2 的目标是把 `a→0, d→0`，只留 `b`（每板一条 profile）与 `c`（每 SoC 一个 BSP，51 台设备约有 5–8 个 SoC）。

### 1.7 必须保留的资产（不要重写）

审计同时确认了一批**已经做对**、v2 不得破坏的东西：

| 资产 | 为什么保留 |
|---|---|
| `tools/lib_image.py` / `mkgpt.py` / `gptslot.c` / `gptgrow.c` | 分区操作用角色而非硬编码偏移，已与板无关 |
| `build-update.sh` / `tools/mkupdate.py` / A/B trial 逻辑 | 更新契约与 SoC 无关 |
| `tools/kernel_abi.py` | modversions 门是**正确的** BSP 级护栏，只需改名挂到 BSP 下 |
| `tools/prepare_stock.py` 的 GPT 解析与哈希锚 | 机制通用，只需把「期望布局」变成 BSP 数据 |
| `baseos-diag` 的 `BASEOS_DIAG_ROOT` 前缀 | **已在用的 root-prefix 抽象**，是 v2 假板方案的基础（§10.3） |
| `tests/make_stock_fixture.py` | 合成 GPT fixture 的思路直接升级为假板 |
| `cache-pack.sh` / `fetch-prepared.sh` | 构件缓存与可信锚机制通用 |
| `overlay/etc/init.d/rcS` 的分阶段编排**思想** | 阶段顺序是对的，只是内容需要下沉为数据 |

### 1.8 审计结论

- 当前**没有** BSP 层。存在的是「一份全局 BSP 的事实 + 一打板级微差异」。
- 最严重的问题不是「支持第二台设备」，而是 **V1/V2/V3 三个轴的事实没有任何归属**，
  它们正在以「模块名 / 节点路径 / 时序常量 / 分区号」的形式漏进 distro。
- `overlay/` 与 `src/` 是 v2 的两大改造对象；`tools/` 与更新链是应当保留并参数化的对象。

**验收标准（本阶段）**：本审计的每条 P0 都在 §12 的路线图里有一个明确落点（哪个 phase 关闭它）。

**风险**：审计基于静态阅读与既有文档；真机行为（尤其 WiFi 时序、TF2 检测、PMIC 写入）
需要 Phase P0 的「行为快照」在真机上确认，避免把「恰好能跑的时序」误判为可删除的巧合。

---

## 2. BSP 边界定义

### 2.1 定义

> **BSP = 一块可启动硬件单元所需要的全部「物理事实」，存放于一个可被构建系统发现的目录，
> 且不包含任何发行版行为。**

三个关键词：

- **全部**：漏掉任何一条，它就会漏到 distro 里去（今天就漏了 24 条）。
- **可发现**：构建系统按 `soc` 字段定位，不需要注册表、不需要改脚本。
- **不含行为**：BSP 可以声明「这个回调要在启动的哪个阶段做」，但不能写「发行版该做什么」。

### 2.2 三条准入判据（可判定，不需要争论）

任何事实要进 BSP，必须能通过下面三个问题中的任意一个且不违反另两个：

1. **换板失效测试**：把这块板拿掉，这条内容是否仍然成立？成立 → 属于 distro；不成立 → 属于 BSP/Profile。
2. **厂商刷新测试**：厂商发布新固件时，这条内容会随之变化吗？会 → BSP（V1/V2/V3）；不会 → distro。
3. **物理 vs 承诺测试**：它描述「硬件是什么」还是「我们保证能做什么」？前者 → BSP/Profile；后者 → Feature。

反例（都属 distro）：`charge_only_boot` 的**流程**、更新 trial 策略、启动音是否播放、mdns 默认值。
正例（都属 BSP）：`os_sleep=16` 这个值、`8821cs.ko` 这个模块名、`sdc2` 这个控制器实例、
`EXPECTED_NAMES` 这个 GPT 名字序列、内核 banner 与符号偏移。

### 2.3 目录与命名

```text
bsp/
  <vendor>/<soc>/                 # SoC 级：一个 SoC 一份（50 台设备预计 5–8 份）
    bsp.json                      # SoC 事实（字段见 §2.4；校验器 tools/validate_bsp.py）
    harvest.list                  # V3 基线闭包（可按 capability 标注分组）
    kernel/
      abi.json                    # 内核身份（release/banner/modversions 期望）+ 模块清单
      modules/<name>/             # SoC 专有内核模块源码（从 src/ 迁入）
    overlay/                       # SoC 级 overlay 片段（白名单规则见 §8.2）
    nodes.json                     # V4 节点映射基线（DAL 的输入）
    tests/                         # SoC 级契约测试（可在 x86 + 假板跑）
  boards/<board>/                  # 板级：一台设备一份
    board.json                     # 产品事实（Device Profile v2，§7）
    overlay/                       # 板级片段（可选，极少数板需要）
    harvest.add                   # 板级增量（可选）
    tests/                         # 板级契约测试（可选）
    evidence/                      # 真机验证存证（截图/日志哈希，不含二进制大文件）
  boards/fake*/                    # 假板族（§10），与真板同构，走同一套校验
  matrix.json                      # 构建/CI 矩阵声明（§11.2）
  lock.json                        # BSP 版本与厂商输入的不可变锚（§2.7）
```

**命名纪律**：目录名用 `snake_case`，与 `board.json` 的 `id` 完全一致；
SoC 路径用 `<vendor>/<soc>`（例：`allwinner/h700`、`allwinner/a133`、`rockchip/rk3566`）。

### 2.4 `bsp/<vendor>/<soc>/bsp.json` 字段

| 组 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 身份 | `schema` | `"pjos.bsp/2"` | 固定前缀，版本化 |
| | `soc` / `vendor` / `family` | string | `h700` / `allwinner` / `sun50i` |
| | `arch` | `aarch64`\|`armhf`\|`x86_64` | |
| 内核 | `kernel.release` | string | 例 `4.9.170` |
| | `kernel.identity` | object | `banner`、`version`、`config_sha256`（ABI 守卫输入） |
| | `kernel.modules[]` | array | `{name, source, load_stage, load_guard}` |
| | `kernel.vendor_modules[]` | array | 从厂商闭包收割且必须 modversion 校验的模块（`mali_kbase`、`8821cs`、`rtl_btlpm`） |
| 引导 | `boot.scheme` | `stockmod-prefix`\|`uboot`\|`efi` | |
| | `boot.partition_names` | array | 厂商 GPT 名字序列（关闭 L13） |
| | `boot.partition_roles` | object | `root_a/root_b/userdata/primary_fat` → 分区号（关闭 L06） |
| | `boot.native_loader` | object\|null | 是否支持原生加载器（H700 专有 = BSP 事实） |
| 存储 | `storage.controllers[]` | array | `{id, mmc_host, roles}`（关闭 L05） |
| | `storage.card_slots[]` | array | `{id, detect, removable}` |
| 电源 | `power.pmic` | object | `{driver, node, quirks:{os_sleep}}`（关闭 L02） |
| | `power.battery_node` / `charger_node` | string | |
| | `power.suspend` | object | `{mode, rtc_alarm, wake_sources[]}` |
| 无线 | `network.wifi` | object\|null | `{module, node_prefix, rf_ctrl, timing:{off_cs,cut_cs,first_cs}}`（关闭 L03/L04） |
| | `network.bt` | object\|null | `{transport, init_hook, sink_supported}` |
| 显示 | `display.backends[]` | array | `fbdev`/`drm` + 节点 + 几何来源 |
| | `display.hdmi` | object\|null | `{switch_via, nodes}` |
| 音频 | `audio.codec` | object | `{card_name, mixer, amp_repair_module}` |
| 用户空间 | `harvest.list` | string | 相对路径 |
| | `harvest.capability_groups` | object | `wifi → [paths…]`（把 L14 的分类变成数据） |
| 能力基线 | `capabilities` | object | SoC 默认能力（板级可覆盖，见 §4.2） |
| 阶段 | `hooks[]` | array | `{stage: "early-init"\|"post-modules"\|"pre-frontend", action, guard}` |
| 资产 | `assets` | object | 工具链镜像、内核源码 tarball 的 sha256（关闭「隐式下载」） |

> **`hooks[]` 的边界**：BSP 只能声明「在这个阶段，加载这个模块 / 写这个节点 / 等这个条件」，
> 且必须是**声明式**的（数据），不能是 shell 片段。否则 BSP 会变成第二份 init。

### 2.5 板名禁用规则（可执行的）

**规则**：除 `bsp/**` 与 `docs/**`（历史文档）外，发行版任何文件**不得**出现板名/SoC 名。

实现为一条架构门（`tests/test-architecture-gate.py`，§11.1 T0）：

```text
输入：仓库内所有非 bsp/、非 docs/、非 work/、非 experiments/ 的文本文件
模式：\b(h700|h616|a133|rk3566|rg28xx|rg34xx|rg35xx|rg40xx|rgcube\w*|rgsp|anbernic|trimui|tg5040)\b
豁免：显式白名单文件 + 行内 `# arch-gate: allow <reason>` 注释
输出：命中 → 失败，并打印 (file:line, token, 建议归属)
```

白名单必须**逐条登记**并写明理由，目前只允许三类：

| 允许位置 | 理由 | 退出条件 |
|---|---|---|
| `docs/**` | 历史证据文档 | 永不退出（历史不可改） |
| `overlay/usr/sbin/frontend-session` 的 `.system/<x>/` 兼容回退 | 已发布的卡上有这个目录（L07） | §12 P7 完成双路径读取后删除 |
| `experiments/**` | 一次性实验（原生加载器等） | 相关能力进 BSP 后删除 |

### 2.6 内核 ABI 归属（红线）

`src/h700-speaker-amp` 这类「按内核 banner/release 校验后写内存」的补丁：

1. **归属 BSP**，不得出现在 distro 目录（今天住在 `src/`，即 L17）；
2. 必须**声明**它支持的内核身份（`kernel/abi.json`），构建期比对；
3. **不匹配时跳过并记录**，禁止「猜一个偏移继续写」（今天已经是这个行为，需要保留并写进契约）；
4. 每个 SoC 的内核升级 = 一次 BSP 升级，**与发行版发版解耦**（`bsp/lock.json` 记录配对关系）；
5. `profiles.json` 的 key 从 `target` 改为 **`kernel_identity`**（内核 sha256 / banner 派生），
   板级只引用身份而不复制偏移表——关闭 L16 的 `11 × N 内核` 爆炸。

### 2.7 BSP 不可变性与 `bsp/lock.json`

- **只增不改**：已发布 BSP 的内容变更必须提升 `bsp/<soc>/VERSION`，并在 lock 中记录。
- `bsp/lock.json` 记录：`{soc: {version, input_sha256{boot_prefix, harvest, kernel}, toolchain}}`。
- 构建时校验：lock 与 `manifest/prepared/<board>.json` 记录的厂商输入哈希必须一致，
  否则**失败**（不是警告）——这是「同一版本镜像可由不同输入重建」的唯一保障。
- BSP **不允许**在构建时联网下载（今天 `build-audio-module.sh` 会拉内核 tarball），
  下载只能发生在 `fetch-prepared.sh`/维护脚本，且必须进 lock。

### 2.8 兼容方式、风险、验收

**兼容**：`bsp/` 是纯新增目录。P0–P1 阶段 distro 仍读旧的 `devices.json`/`harvest.list`，
BSP 只做「影子数据 + 一致性校验」（BSP 生成的事实必须逐条等于现状），因此镜像哈希不变。

**风险**：

| 风险 | 缓解 |
|---|---|
| BSP 变成第二份脚本（hooks 滥化） | hooks 只允许 4 个 stage + 3 种 action，schema 枚举校验 |
| 板名扫描误伤（日志文本/注释） | 行内豁免注释 + 白名单登记，且豁免必须带 reason |
| 为「未来可能用到」塞入字段 | Profile schema `additionalProperties:false`，字段必须至少被一个构建期消费者使用 |

**验收**：

1. `grep` 板名在 `bsp/`、`docs/`、白名单之外为空（架构门通过）；
2. 新增一台 H700 变体设备 = 只新增 `bsp/boards/<id>/board.json`，diff 中不出现其它目录；
3. 删除 `bsp/allwinner/h700/` 后，构建系统报「找不到 SoC」而不是继续用残留常量。

---

## 3. DAL 边界定义（Device Abstraction Layer）

### 3.1 为什么需要（问题不是抽象，是**责任错位**）

今天硬件访问有三种形态同时存在：

| 形态 | 例子 | 问题 |
|---|---|---|
| distro init 直接写节点 | rcS 写 `os_sleep=16`、`rf-ctrl/scan_device` | 板级知识在 distro |
| distro 脚本自行解析 | `baseos-charger` 读 `axp2202-battery`、`baseos-diag` 用 `axp[0-9]*` 正则 | 每加一个 PMIC 型号就要改 3 个脚本 |
| **应用层探测** | PocketJS `launch_frontend.sh`（fb→drm→fb0）、shim 里写死 `enhance_bright`/`amixer`/`axp2202-battery`（L20） | 换设备要改应用仓库；探测失败静默降级 |

第二、三种的结果是**静默错误**：这台设备没有背光节点，UI 显示 `unknown`，用户以为坏了。
DAL 的目标是把「这颗 SoC 的节点长什么样」变成**数据**，把「怎么用它」变成**一份代码**，
把「有没有/能不能」变成**可查询的契约**。

### 3.2 结构：数据 + 一份实现 + 稳定语义

```
        ┌─────────────────────────────────────────────┐
        │ 语义接口（稳定，跨设备、跨 SoC、跨版本）        │
        │ display / audio / input / power / network /  │
        │ storage / led                                │
        └───────────────▲─────────────────────────────┘
                        │  baseosctl（唯一出入口）
        ┌───────────────┴─────────────────────────────┐
        │ DAL resolver（一份代码，distro 所有，无板名）  │
        │  1. 实例枚举  2. 属性读取  3. 动词执行         │
        └───────────────▲─────────────────────────────┘
                        │  读取（只读数据，不执行逻辑）
        ┌───────────────┴─────────────────────────────┐
        │ node map：bsp/<soc>/nodes.json + board 覆盖   │
        │  （唯一允许出现 /sys /proc /dev 路径的地方     │
        │     ——与 bsp/ 内其它内容同属「数据」）         │
        └─────────────────────────────────────────────┘
```

三条硬规则：

1. **DAL resolver 里没有板名、没有节点字面量**（节点全部来自 node map）。
2. **node map 里没有行为**（只有路径、glob、单位换算、枚举值映射）。
3. **应用与 runtime 不读 `/sys`、`/proc`、`/dev`**，只调 `baseosctl`（§6）。

### 3.3 七个域的稳定语义

每个域给出：**属性（可读）**、**动词（可写/动作）**、**三态**、**典型节点（仅作为 node map 的示例）**。

#### display

| 项 | 内容 |
|---|---|
| 属性 | `backend`(fbdev/drm)、`width`、`height`、`stride`、`bpp`、`rotation`、`brightness{cur,max}`、`hdmi{connected,active}`、`vendor_fps_mode` |
| 动词 | `set-brightness`、`set-rotation`（仅当 feature `display_rotation_runtime`）、`set-hdmi` |
| 三态 | 无背光节点 → `brightness.available=false`（不是错误） |
| 示例节点 | `/dev/fb0`、`/dev/dri/card0`、`/sys/class/graphics/fb0/{virtual_size,bits_per_pixel}`、`/sys/class/disp/disp/attr/enhance_bright`、`/sys/kernel/debug/dispdbg/*` |

#### audio

| 项 | 内容 |
|---|---|
| 属性 | `card`、`mixer_control`、`volume{cur,max,step}`、`mute`、`routes[]{speaker,headphone,hdmi}`、`amp_repair{active,supported}` |
| 动词 | `set-volume`、`set-mute`、`set-route` |
| 三态 | 无 mixer → `volume.available=false`；有 `amp_repair` 但内核身份不匹配 → `amp_repair.state="skipped"` |
| 示例节点 | `/dev/snd/*`、`amixer -c audiocodec`、`/usr/lib/modules/h700_speaker_amp.ko`、`/mnt/vendor/ctrl/setBluetooth.sh` |

#### input

| 项 | 内容 |
|---|---|
| 属性 | `devices[]{id,name,phys,axes,buttons,role}`、`keyboard{name,codes}`、`hotkeys{mask}`、`menu_held` |
| 动词 | `rebind`（可选）、`describe` |
| 三态 | 无匹配键盘 → `keyboard.available=false`，但 `devices[]` 仍要列出全部 |
| 示例节点 | `/dev/input/event*`、`/sys/class/input/event*/name`、`/sys/kernel/debug/gpio`（MENU 判定） |
| 说明 | `keyboardd` 是 **runtime**（§3.7），它拿到的句柄必须来自这里，而不是自己扫 `/dev/input` |

#### power

| 项 | 内容 |
|---|---|
| 属性 | `battery{capacity,status,voltage,health}`、`charger{online,current_limit}`、`boot_reason`、`suspend{state,wake_sources}`、`rtc{epoch,alarm}`、`led{state}` |
| 动词 | `suspend`、`poweroff`、`reboot`、`set-charge-limit`（可选）、`set-led` |
| 三态 | 无充电器节点 → `charger.available=false`；`charge_only_boot` 能力由 feature 决定 |
| 示例节点 | `/sys/class/power_supply/axp2202-battery/{capacity,status,boot_mode,os_sleep,work_led}`、`/sys/class/rtc/rtc0/since_epoch`、`axp-off` |

#### network

| 项 | 内容 |
|---|---|
| 属性 | `wifi{present,up,ssid,ip,mac,rfkill}`、`bt{present,powered,connected[]}`、`mdns{hostname,published}` |
| 动词 | `wifi-enable/disable`、`bt-enable/disable`、`bt-pair`（可选） |
| 三态 | `wifi.present=false` 与 `wifi.present=true,up=false` 必须可区分 |
| 示例节点 | `/sys/class/net/wlan0`、`/sys/class/misc/sunxi-wlan/rf-ctrl/*`、`/sys/bus/sdio/devices/*` |

#### storage

| 项 | 内容 |
|---|---|
| 属性 | `root_slot`(a/b)、`data{device,fs,free}`、`cards[]{slot,present,fs,label}`、`usb_mode{none,adb,mass}`、`expand{needed,target}` |
| 动词 | `expand`、`usb-mode`、`mount`/`umount`（受 feature 限制） |
| 三态 | TF2 未插卡 → `cards[1].present=false`（不是失败） |
| 示例节点 | `/dev/mmcblk0p{4,5,6,7}`、`/dev/mmcblk1p1`、`/sys/class/block/mmcblk0p4/{start,size}`、`/sys/class/udc/*` |

#### led

| 项 | 内容 |
|---|---|
| 属性 | `leds[]{name,role,brightness,max,trigger}` |
| 动词 | `set`（role: `status`/`charge`/`wifi`） |
| 三态 | 无 LED → 空数组（**不**返回错误） |
| 示例节点 | `/sys/class/leds/*`、`.../axp2202-battery/work_led` |

### 3.4 解析算法（确定性、无探测）

```text
resolve(domain, attr):
  1. 实例选择：board.nodes[domain] → 若有 node 直接命中
     否则 soc.nodes[domain] → glob 展开（按 /sys 枚举顺序排序，稳定）
     否则 → state = "unsupported"（该能力在 profile 里没声明）
  2. 属性读取：
     - node + subpath + transform（none|int_div|milli_to_int|map{表}）
     - 读取失败 → "unavailable"（声明了但此刻不可读）
  3. 单位与语义归一：
     - 亮度：0..max 归一化到 0..100 的百分比由 DAL 负责（应用不需要知道 raw 范围）
     - 容量：整数百分比；电压 mV；时间秒
  4. 返回 {value, state, source:{node, subpath}, board, soc}
```

**禁止**：

- 探测式回退（`if [ -e /dev/dri ]; then … else …`）——回退顺序必须来自 profile 的 `display.backends[]`（有序数组）。
- 按名字猜硬件（`case "$name" in axp*)`、`grep ANBERNIC`）——型号知识属于 node map。
- 应用侧 `try/except` 式能力判断——用 `baseosctl cap has <x>`。

**重要**：`source` 字段会随输出返回（`--json` 模式），但**只用于排障**。
文档与 UI 契约明确：应用不得解析 `source` 来决定行为（否则又回到节点路径耦合）。

### 3.5 错误语义（三态必须能分辨）

| 状态 | 含义 | `baseosctl` exit code | 应用应如何反应 |
|---|---|---|---|
| `ok` | 有值 | 0 | 正常显示 |
| `unsupported` | 这块板/SoC **没有**这个能力（profile 未声明） | 3 | 隐藏 UI 元素 |
| `unavailable` | 声明了，但当前不可读（模块未加载/硬件异常） | 4 | 显示「不可用」，可自愈重试 |
| `not_ready` | 暂时没准备好（启动中、正在切换） | 5 | 稍后重试 |
| `io_error` | 权限/IO 失败 | 6 | 记录并提示 |
| `usage` | 参数/schema 错误 | 2 | 程序 bug |

**这条表是 DAL 的核心价值**：它把「没有」和「坏了」分开，而今天的代码把两者都变成 `unknown`。

### 3.6 backend 抽象（为未来的 Android DAP 预留）

node map 的每一项都带 `backend` 字段：

```json
{ "domain": "power", "attr": "battery.capacity",
  "backend": "sysfs", "node": "/sys/class/power_supply/axp2202-battery", "subpath": "capacity",
  "transform": "int" }
```

`backend` 允许值（v2 定义，v2 实现只做 `sysfs`）：

| backend | 用于 | 状态 |
|---|---|---|
| `sysfs` | 现有全部设备 | v2 实现 |
| `hal` | Android 设备（DAP / 手机）通过 `baseosctl` 后端服务 | v3 设计，接口先定 |
| `fake` | 假板 / CI fixture | v2 实现（§10） |

**新增第 51 台设备（Android DAP）时**：新增 `backend: "hal"` 的 node map + 一个 HAL 适配器，
**DAL resolver 与 baseosctl 接口不变**，PocketJS 一行不改。这是选择「数据化 node map」
而不是「每设备一个脚本」的核心理由。

### 3.7 Runtime 与 DAL 的边界

| 组件 | 允许 | 禁止 |
|---|---|---|
| `pocket-linux-kms`（PocketJS runtime） | 从 `baseosctl display info --json` 取得 fb/drm 句柄、几何、旋转；从 `baseosctl input list --json` 取得 evdev 路径 | 自己扫描 `/dev/dri`、`/dev/fb*`、`/dev/input`；按名字匹配设备 |
| `keyboardd`（Go，runtime） | 由 `frontend-session` 传入 `--event <path>`（来源 DAL） | 自己遍历 `/dev/input` 猜「哪个是键盘」 |
| `frontend-session`（BaseOS） | 调 `baseosctl`，把结果作为**参数**交给 runtime | 内联节点路径、板名路径（L07） |

> 落地顺序注意：PocketJS 在**另一个仓库**。本仓库的责任是**先把接口做出来**（P4），
> 再让应用侧改（P6）。中间期用「优先 `baseosctl`、失败回落旧路径」的 shim 过渡（§12）。

### 3.8 反模式清单（评审时直接拒绝）

| 反模式 | 为什么拒绝 |
|---|---|
| `dal/<board>.sh`（每板一个 DAL 实现） | 把「一份代码」变成 N 份，第 51 台设备要写第 51 个脚本 |
| DAL 里 `case "$BASEOS_TARGET"` | 板名进入 distro（§2.5 架构门直接失败） |
| 让应用读 `baseosctl display info` 的 `source.node` 再自己打开 | 等于绕过 DAL，节点路径仍是 ABI |
| 在 DAL 里做 feature 判定 | DAL 只回答「有没有值」；「能不能做」属 Feature（§5） |
| 用 `try/except` 代替三态 | 会把「没有」和「坏了」混在一起（§3.5） |

### 3.9 兼容方式、风险、验收

**兼容**：DAL 的第一版（P3）**只读**，且 `baseosctl` 与旧脚本并存。
`baseos-diag`、`baseos-charger`、`rcS` 逐条从「内联节点」改为「查 node map」，
每一步都可以用「输出与改动前逐字节相同」验证（`baseos-diag` 有 `--json` 快照测试）。

**风险**：

| 风险 | 缓解 |
|---|---|
| node map 表达力不足，逼出脚本 | node map 允许 `glob`、`transform`、`map` 三件套；不足时**扩展 schema**，不写脚本 |
| 归一化改变既有数值（亮度 % vs raw） | DAL 同时返回 `value` 与 `raw`，P3 阶段应用仍用 raw，P6 再切 |
| 读节点有副作用（某些 sysfs 写入即动作） | node map 的 `writable:true` 必须显式声明，且写操作只在动词里 |

**验收**：

1. `grep -rnE '/sys/|/proc/|/dev/' overlay/ runtime/` 只命中白名单（`bsp/` 产物、兼容回退）；
2. 在假板上把 `power.battery` 的节点改成一个不存在的路径 → `baseosctl power battery` 返回
   `state=unavailable`、exit 4；把 profile 里该能力删掉 → `state=unsupported`、exit 3；
3. 把 `display.backend` 从 `fbdev` 改成 `drm`（假板），`baseosctl display info` 语义不变、应用代码零改动。

---

## 4. Capability 系统设计

### 4.1 定义与命名空间

> **Capability = 这台机器的硬件是否具备某一项「有/没有」的事实。** 三态，不可推断，只能查询。

命名规则：`<domain>[.<feature-part>]`，全小写下划线分段，**不含板名、不含型号**。

| 域 | Capability 名字（v2 首批） |
|---|---|
| display | `display`、`display.backlight`、`display.rotation`、`display.hdmi`、`display.drm`、`display.fbdev` |
| audio | `audio`、`audio.mixer`、`audio.headphone_detect`、`audio.hdmi_out`、`audio.amp_repair` |
| input | `input`、`input.keyboard`、`input.touch`、`input.analog_sticks`、`input.vibration` |
| power | `power.battery`、`power.charger`、`power.rtc`、`power.suspend`、`power.charge_only_boot`、`power.led` |
| network | `network.wifi`、`network.bluetooth`、`network.ethernet`、`network.usb_net` |
| storage | `storage.sd`、`storage.emmc`、`storage.second_slot`、`storage.usb_host`、`storage.usb_gadget` |
| system | `system.fast_boot_native`、`system.ab_update`、`system.dual_slot` |

### 4.2 声明来源与优先级（唯一事实源）

```text
优先级（后者覆盖前者）：
  1. distro 默认表         pjos:distro/capabilities.json      # 全部 unknown
  2. SoC BSP 基线          bsp/<vendor>/<soc>/bsp.json  → capabilities{}
  3. 板级 Profile          bsp/boards/<id>/board.json   → capabilities{}
  4. 构建期强制推导        由 BSP/Profile 的事实推出的必然结论（见下）
  5. （运行期不覆盖）
```

第 4 步是**关键**：某些 capability 不允许手写，必须由事实推导，避免「声明有 WiFi 但没有 WiFi 模块」。

| 推导规则 | 结论 |
|---|---|
| `network.wifi != null` 且 `kernel.modules` 含 wifi 模块 且 harvest 有 wpa 相关 | `network.wifi = yes` |
| `network.wifi == null` | `network.wifi = no` |
| `display.hdmi != null` 且 debugfs 开关存在 | `display.hdmi = yes` |
| `audio.amp_repair_module` 存在 且 `kernel.identity` 有对应 ABI 记录 | `audio.amp_repair = yes`（否则 `unknown`：模块在，但没验证过这颗内核） |
| `storage.controllers` 中存在第二个 removable 控制器 | `storage.second_slot = yes` |

**冲突检测（构建期失败，不是警告）**：

- 手写声明与推导结论矛盾 → 失败，并提示「删掉手写的那一条」；
- 板级声明 `yes` 但 SoC BSP 该子系统为 `null` → 失败（缺少物理声明）；
- `manifest/prepared/<board>.json` 的旧 `capabilities{}` 与新推导结果不一致 → 失败（关闭 L19 漂移）。

### 4.3 构建产物 `/etc/pjos/capabilities.json`

```json
{
  "schema": "pjos.caps/2",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "generated_by": "pjos-build 1.5.2",
  "caps": {
    "display": "yes",
    "display.backlight": "yes",
    "display.rotation": "yes",
    "display.hdmi": "yes",
    "audio": "yes",
    "audio.amp_repair": "yes",
    "input.keyboard": "yes",
    "input.touch": "no",
    "input.vibration": "no",
    "power.battery": "yes",
    "power.charge_only_boot": "yes",
    "power.suspend": "yes",
    "network.wifi": "yes",
    "network.bluetooth": "yes",
    "storage.second_slot": "yes",
    "storage.usb_gadget": "yes",
    "system.ab_update": "yes"
  },
  "unknown": ["input.analog_sticks"],
  "evidence": { "rg34xx": { "device_verified": "2026-08-12", "commit": "…" } }
}
```

规则：

- **三态必须显式**：`yes`/`no`/`unknown`。缺省不是 `no`。
- **`unknown` 必须被应用当成「可能有」处理**（即：允许用户尝试，但 UI 不给承诺）。
- `evidence` 来自设备矩阵（§4.4），构建时从 `bsp/boards/<id>/evidence/` 汇总。

### 4.4 declared vs verified（防「谎报声明」）

| 层 | 来源 | 用途 |
|---|---|---|
| **declared** | BSP/Profile（构建期） | 决定构建什么、裁剪什么、`caps.json` 内容 |
| **verified** | 设备矩阵实测（`evidence/`） | 标记 `device_verified`；CI 与发布矩阵据此区分 claim 与事实 |

构建期**不**因为「未验证」而改变 capability 值（否则无法离线构建），
但 release 页面与 `baseosctl cap list --json` 的 `verified` 字段必须如实反映。
**谎报治理**：当某板声明 `yes` 而设备实测 `no`，矩阵把该板标记为 `mismatch` 并让发布说明降级——
这是唯一能让声明长期可信的机制。

### 4.5 消费方式（应用层唯一姿势）

```sh
# 脚本
baseosctl cap has network.wifi || skip_wifi_setup

# 应用（JSON）
baseosctl cap list --json | jq -r '.caps["display.backlight"]'
```

禁止：

```sh
ls /sys/class/backlight          # ❌ 应用层探测
[ -e /dev/dri/card0 ] && ...     # ❌ 探测即推断
```

### 4.6 与 harvest（V3 闭包）的联动

今天 `harvest.list` 用 `## wifi` / `## bluetooth` 注释分组，`prepare_stock.py::omission_allowed`
按 `profile["wifi"]` 决定「缺文件是否允许」（L14）。v2 把它变成**数据驱动的条件闭包**：

```json
// bsp/<soc>/bsp.json → harvest.capability_groups
{
  "network.wifi": ["/usr/sbin/wpa_supplicant", "/usr/lib/libwpa_client.so"],
  "network.bluetooth": ["/usr/lib/libbluetooth.so.3"],
  "required": ["/usr/lib/aarch64-linux-gnu/libc.so.6", "…"]
}
```

构建期：`for cap in groups: if caps[cap] != "yes": 允许缺失`。
收益：第二块 SoC 换一份 `bsp.json` 即可，`prepare_stock.py` 不再含任何 capability 逻辑（关闭 L14）。

### 4.7 兼容、风险、验收

**兼容**：

- `/etc/baseos-release` 继续生成 `BASEOS_WIFI`/`BASEOS_BLUETOOTH`（由新 caps 推导），
  旧的前端与脚本不受影响；
- `manifest/prepared/*.json` 的 `capabilities{}` 保留，但改为**构建期一致性校验对象**（单向：新→旧）。

**风险**：

| 风险 | 缓解 |
|---|---|
| capability 名字爆炸（每功能一个名字） | 名字进 registry 文件并评审；只允许「有/没有」语义，行为一律进 Feature |
| `unknown` 被应用当 `no` | 契约写明：`unknown` 必须允许尝试；契约测试覆盖三种取值 |
| 推导规则与手写冲突导致构建脆断 | 冲突信息必须给出「删哪一行」的修复指令，错误信息本身就是文档 |

**验收**：

1. 假板（§10）三种取值都能在 `baseosctl cap get` 与 `caps.json` 中如实呈现；
2. 删掉 `bsp/allwinner/h700/bsp.json` 的 `network.wifi` 后，构建失败并提示「board 声明了 wifi 但 SoC 无物理声明」；
3. H700 的 11 个 target 生成的 caps 与今天 `BASEOS_WIFI/BLUETOOTH` 完全一致（哈希门）。

---

## 5. Feature 系统设计

### 5.1 为什么必须有（v1 最大的缺口）

| | Capability | Feature |
|---|---|---|
| 回答 | **有没有**（wifi / bluetooth / touch / vibration / hdmi） | **能干什么**（bt_sink / audio_hw_volume / display_rotation / suspend / rtc_alarm） |
| 归属 | 硬件事实 | 发行版承诺 |
| 数量级 | 数十（稳定） | 数百（随发行版演进） |
| 变化原因 | 换板 | 发版 |
| 谁定义 | BSP + Profile | **只在 distro** |
| 应用能否推断 | 不能（必须查） | **严禁推断，必须查** |

今天的实际情况是：**feature 全部隐含在代码里**。举三个真实例子：

1. rcS 里有 `wifi_off_cs=500 / wifi_cut_cs=185 / wifi_first_cs=225` —— 这是「H700 的 WiFi 上电时序」，
   一个**板级事实**，被写成 distro 的 feature 行为（L03）。
2. rcS 里有 `printf '16' > os_sleep` —— 「SP 内核支持低功耗挂起策略」既是 cap（`power.suspend`）
   又是 feature（`suspend_os_sleep_quirk`），今天是裸代码（L02）。
3. PocketJS shim 里 `amixer` 调音量 —— 「有硬件混音器」是 cap（`audio.mixer`），
   「音量可调」是 feature（`audio_hw_volume`），今天由应用自己推断（L20）。

**没有 Feature 层的后果**：每台新设备都要在 distro 里加一段「这台设备要这么干」的代码，
而正确的位置是「声明一条数据 + 让 resolver 推导」。

### 5.2 三个状态

| 状态 | 何时产生 | 谁可见 | 用途 |
|---|---|---|---|
| **declared** | distro 的 feature registry（静态，随版本） | 构建期 | 契约：这个版本**声称**支持哪些行为 |
| **resolved** | 构建期由 `resolve(profile, caps)` 纯函数推导 | 构建期 + 运行期（`/etc/pjos/features.json`） | 这台设备**实际**有哪些行为 |
| **observed** | 运行期健康检查（可选，由 `baseosd`/`baseosctl` 计算） | 运行期 | 现在**能不能用**（如 WiFi 未加载 → `degraded`） |

**应用只允许使用 resolved + observed**，永远不参与 declared 的解释。

### 5.3 Feature registry（distro 所有，纯数据）

位置：`pjos/features/<domain>.json`（distro 目录，**不在 bsp/**）。

```json
{
  "schema": "pjos.features/2",
  "features": {
    "audio_hw_volume": {
      "summary": "Volume is adjustable through the hardware mixer",
      "requires": { "caps": ["audio", "audio.mixer"] },
      "requires_facts": [],
      "conflicts": [],
      "degrade_to": null,
      "default": true
    },
    "bt_sink": {
      "summary": "Bluetooth audio sink (A2DP) via bluealsa",
      "requires": { "caps": ["network.bluetooth"], "features": ["bluetoothd"] },
      "requires_facts": [{ "path": "network.bt.sink_supported", "equals": true }],
      "conflicts": [],
      "degrade_to": null,
      "default": true
    },
    "suspend_os_sleep_quirk": {
      "summary": "Apply the SoC's low-power suspend policy bit before services start",
      "requires": { "caps": ["power.suspend"] },
      "requires_facts": [{ "path": "power.pmic.quirks.os_sleep", "present": true }],
      "apply": { "stage": "early-init", "action": { "write": "power.pmic.quirks.os_sleep" } },
      "degrade_to": "suspend_plain",
      "default": true
    },
    "wifi_slow_radio_retry": {
      "summary": "Reload the WiFi module when the radio needs a longer power-off",
      "requires": { "caps": ["network.wifi"] },
      "requires_facts": [{ "path": "network.wifi.timing", "present": true }],
      "apply": { "stage": "early-init-background", "action": { "dal_verb": "network.wifi-load" } },
      "degrade_to": "wifi_plain_load",
      "default": true
    }
  }
}
```

字段语义：

| 字段 | 说明 |
|---|---|
| `requires.caps` | 全部必须为 `yes`（`unknown` 视为不满足，但**记录原因**） |
| `requires.features` | feature 依赖 feature（构造 DAG，禁止环） |
| `requires_facts` | 读 Profile/BSP 的**数据路径**（`present`/`equals`/`in`），只做「事实是否具备」判定 |
| `conflicts` | 互斥 feature（构建期若同时 resolved → 失败） |
| `degrade_to` | 不满足时的降级 feature（必须存在于 registry，或为 `null`） |
| `apply` | **可选**：该 feature 在启动阶段的声明式动作（`write`/`dal_verb`/`module_load`）， 目标路径或动词必须来自 BSP 数据；**不允许内联 shell 片段** |
| `default` | 板级未显式 opt-out 时是否启用 |

**registry 的边界规则**：registry 里**不允许出现板名**。若某 feature 只对一块板成立，
那说明它要么是 capability/facts 的组合（写成 requires 即可），要么是 BSP 数据（写进 `bsp.json`），
要么根本不该是 feature。

### 5.4 解析算法（纯函数，无 I/O，可在 x86 上跑）

```python
def resolve(registry, caps, facts, board_overrides) -> Features:
    # 1. 候选集合 = registry 全部, default=true
    enabled = {name for name, f in registry if f["default"]}

    # 2. 应用板级 opt-out（唯一允许的板级影响）
    for name, override in board_overrides.items():
        if override.disabled:
            enabled.discard(name)          # 必须带 reason（schema 强制）
            record(name, "disabled_by_board", override.reason)

    # 3. 满足条件求解（不动点迭代，最多 len(registry) 轮，保证终止）
    repeat until stable:
        for name in list(enabled):
            f = registry[name]
            if not all(caps[c] == "yes" for c in f.requires.caps):
                enabled.discard(name); record(name, "missing_cap"); continue
            if not all(dep in enabled for dep in f.requires.features):
                enabled.discard(name); record(name, "missing_feature_dep"); continue
            if not all(fact_ok(facts, r) for r in f.requires_facts):
                enabled.discard(name); record(name, "missing_fact"); continue

    # 4. degrade（只降一级，避免链式猜测）
    for name in features_removed:
        if f.degrade_to and f.degrade_to in registry and degrade_conditions_ok(...):
            enabled.add(f.degrade_to); record(name, "degraded", f.degrade_to)

    # 5. 冲突检查 → 失败（构建期错误，不是警告）
    for a, b in conflicts_pairs():
        if a in enabled and b in enabled: fail(f"{a} conflicts {b}")

    # 6. 输出排序后的确定性集合 + 每个 feature 的 reason
    return sorted(enabled), reasons
```

要求：

- **确定性**：输入相同 → 输出字节相同（排序 + 无时间戳），可做哈希门。
- **可解释**：每个 feature 都带 `reason`（`resolved` / `missing_cap:network.bluetooth` / `disabled_by_board:…` / `degraded:…`）。
- **无探测**：不得读 `/sys`；`requires_facts` 只读 Profile/BSP 数据。

### 5.5 板级只能 opt-out，不能定义

| 允许 | 禁止 |
|---|---|
| `board.json → features: { "<name>": {"enabled": false, "reason": "硬件无 LDO 控制" } }` | 板级新增 registry 里没有的 feature |
| 板级把某 feature 指向不同的 BSP 数据（通过 Profile facts） | 板级写 feature 的实现步骤（shell/C 片段） |

**理由**：如果允许板级定义 feature，第 51 台设备就会带着第 51 份 feature 定义来，registry 变成新的板级垃圾场。

### 5.6 首批 feature 清单（从现有代码逆向推导）

这是本设计最需要的「可信性」：每条都能指到今天的代码。

| Feature | requires（caps / facts） | 今天的实现位置 | v2 归属 |
|---|---|---|---|
| `ab_update` | `system.ab_update` | `build-update.sh`、`baseos-update` | distro（保留） |
| `charge_only_boot` | `power.charge_only_boot`、`power.rtc` | rcS + `baseos-charger` + `axp-off` | feature + DAL `power.poweroff` |
| `usb_storage_maintenance` | `input.keyboard`、`storage.sd` | rcS + `boot-menu-held` + `usb-storage-mode` | feature + DAL `storage.usb-mode` |
| `second_slot_frontend` | `storage.second_slot` | rcS TF2 探测 + `frontend-session` | feature + DAL `storage.cards` |
| `expand_storage` | `storage.emmc` \| `storage.sd` | `expand-storage` + `gptgrow` | feature + DAL `storage.expand` |
| `wifi_plain_load` | `network.wifi` | rcS 默认分支 | feature `apply` |
| `wifi_slow_radio_retry` | facts `network.wifi.timing` | rcS `wifi_*=cs` 常量 | feature + BSP 数据（关闭 L03） |
| `suspend_os_sleep_quirk` | facts `power.pmic.quirks.os_sleep` | rcS `printf 16` | feature + BSP 数据（关闭 L02） |
| `audio_hw_volume` | `audio.mixer` | PocketJS shim `amixer` | feature + DAL `audio.set-volume`（关闭 L20 一部分） |
| `audio_amp_repair` | `audio.amp_repair` | `h700-speaker-amp-load` + `profiles.json` | BSP 模块 + feature 开关（关闭 L16/L17） |
| `bt_sink` | `network.bluetooth` + facts `network.bt.sink_supported` | `/data/bluealsa` + `setBluetooth.sh` | feature + DAL `network.bt` |
| `display_runtime_rotation` | `display.rotation` | PocketJS shim / fbsplash 以外的旋转逻辑 | feature + DAL `display.set-rotation` |
| `hdmi_out` | `display.hdmi` | rcS debugfs + PocketJS `dispdbg` 写 | feature + DAL `display.set-hdmi`（关闭 L20 一部分） |
| `mdns_publish` | `network.wifi` \| `network.ethernet` | `baseos-mdns` | feature + DAL `network.mdns` |
| `ntp_sync` | `network.*` | `baseos-ntp`、`timedatectl` | feature |
| `adbd_gadget` | `storage.usb_gadget` | `usb-gadget-adb`、`/sys/class/udc` | feature + DAL `storage.usb-mode` |
| `fast_boot_native` | facts `boot.native_loader` | `experiments/h700-boot-speed` + `rcS` 的 `baseos,native-boot` 分支 | **BSP 专有**（H700 only）；feature 只是开关 |
| `boot_splash_rotation` | facts `panel.rotation` | `fbsplash` + `BASEOS_PANEL_ROTATION_CCW` | 构建期 profile 消费，**不是**运行期 feature |
| `startup_sound` | `audio`、`storage.sd` | `baseos-startup-sound` | feature |

> 注意最后两条的区别：`boot_splash_rotation` 是**构建期**事实（splash 二进制在构建时就旋转好了），
> 因此它属于 Profile 消费，不进运行期 feature 集合。**feature 只描述运行期能看到的行为**——
> 这条边界避免 feature 集合膨胀成「构建期选项大全」。

### 5.7 产物 `/etc/pjos/features.json`

```json
{
  "schema": "pjos.featureset/2",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "hash": "sha256:…",
  "enabled": ["ab_update", "audio_hw_volume", "bt_sink", "…"],
  "disabled": [
    { "name": "hdmi_out", "reason": "disabled_by_board", "detail": "no HDMI TX on this board" },
    { "name": "input_touch", "reason": "missing_cap:input.touch" }
  ],
  "degraded": [ { "name": "suspend_os_sleep_quirk", "to": "suspend_plain", "reason": "missing_fact:power.pmic.quirks.os_sleep" } ]
}
```

`hash` 是确定性集合的哈希，可放进 release 说明，用于回答「这台设备的 feature 集合什么时候变的」。

### 5.8 应用如何用（禁止推断）

```sh
baseosctl feature has bt_sink || hide_bluetooth_audio_menu
baseosctl feature explain bt_sink      # → reason=missing_cap:network.bluetooth
```

`feature explain` 是**维护者的主要工具**：它回答「为什么这台设备没有蓝牙音频」，
而不是让人去翻 rcS。这条命令的收益随设备数线性增长。

### 5.9 兼容、风险、验收

**兼容**：P5 之前 feature 集合只生成、不消费（`features.json` 存在但没有任何代码读它），
因此 H700 行为不变。P5 起逐条把 rcS/脚本里的硬编码分支改为 `baseosctl feature has <name>`，
每条改动的验收都是「H700 行为与改动前一致（差分启动日志 + 关键路径时序）」。

**风险**：

| 风险 | 缓解 |
|---|---|
| feature 粒度失控（一个行为拆成 5 个 feature） | 粒度规则：**一个 feature = UI 上一个可隐藏的开关**，或一条启动阶段的独立动作 |
| `requires_facts` 变成隐式板名（`facts.board == "rg34xx"`） | facts 只暴露 BSP/Profile 的结构化数据路径，`board.id` 不在允许的 data path 白名单 |
| degrade 链导致「看起来支持其实半残」 | degrade 只允许一级，且必须在 `disabled` 与 `degraded` 中如实输出 |
| registry 长期缺少维护，变成死代码 | release 矩阵输出「未被任何 board resolved 的 feature」清单，连续两个版本未使用即标记 deprecated |

**验收**：

1. 同一组 `(caps, facts)` 在 x86 假板上解析出的 feature 集合与 H700 真机一致；
2. 把 `network.bluetooth` 从 `yes` 改为 `no`，`baseosctl feature has bt_sink` 返回 1，
   `feature explain bt_sink` 输出 `missing_cap:network.bluetooth`，**distro 与 bsp 代码零改动**；
3. registry 中不存在板名（架构门覆盖 `pjos/features/`）；
4. 解析结果确定性：同一输入两次构建 `features.json` 字节相同。

---

## 6. `baseosctl` API 设计

### 6.1 定位与进程模型

> `baseosctl` 是 **PocketOS 唯一的正式系统接口**。发行版之外的一切（应用、runtime、脚本、第三方）
> 只能通过它与系统交互。它必须是**机器可读**的；面向人类的文本由 `baseos-diag` 负责，两者不混用。

实现选择（评审结论）：

| 方案 | 结论 | 理由 |
|---|---|---|
| busybox sh 单文件 | **v2 采用** | 与现有 `overlay/usr/sbin/baseos-*` 一致；无新工具链；启动即用；便于假板测试 |
| 静态 C 二进制 | 备用 | 若 sh 版本 JSON 生成/eval 成本被实测证明过高（>30 ms/次），迁移到 C，**接口不变** |
| 常驻 daemon（`baseosd`）+ 客户端 | v3 预留 | 需要事件订阅/缓存时引入；`baseosctl` 保持为客户端，接口不变 |

**关键约束**：实现可换，**契约不可换**。契约写在本文 + `docs/` 的 golden 样例里，并用契约测试固定。

### 6.2 全局约定

```
baseosctl <domain> <verb> [args…] [--json] [--format=kv|json] [--root DIR]
                        [--dry-run] [--timeout SECONDS] [--quiet]
baseosctl version | schema
```

| 约定 | 规则 |
|---|---|
| 输出通道 | **stdout 只有数据**；一切诊断/警告进 stderr。禁止横幅、禁止 emoji、禁止自由文本 |
| 格式 | `--json`（默认关闭）输出单个 JSON 对象；默认 `kv` 输出 `key=value` 每行一个 |
| JSON 信封 | 顶层必有 `schema`、`domain`、`verb`、`state`、`board`、`soc`；payload 在 `data` |
| 数组（kv） | `key[]=v1,v2`（逗号分隔，值内逗号转义为 `\,`） |
| 数值 | 整数不带小数；单位写进 key（`voltage_mv`、`uptime_s`、`capacity_pct`） |
| 时间 | Unix epoch 秒（`epoch_s`） |
| 三态 | `state: ok|unsupported|unavailable|not_ready|io_error|usage`；kv 模式 `state=…` 首行 |
| 退出码 | 0 ok；2 usage；3 unsupported；4 unavailable；5 not_ready；6 io_error；7 conflict |
| 超时 | 默认 2 s（`--timeout` 覆盖）；超时 → `state=not_ready`、exit 5，**绝不 hang** |
| 幂等 | 所有写操作必须幂等；重复调用第二次 `changed=0` |
| 并发 | 只读命令无锁；写操作使用 `/run/baseosctl.lock` |
| 版本 | `schema` 值为 `baseos.ctl/2`；字段只增不改，删除需升 `/3` |
| root 前缀 | `--root DIR` 使所有 `/sys`、`/proc`、`/dev`、`/etc` 访问重定位到 `DIR`（假板与 CI 的基础，见 §10.3） |

### 6.3 命令面（v2 全量）

| 组 | 命令 | 状态 | 说明 |
|---|---|---|---|
| 元信息 | `version` | v2 | `board`、`soc`、`baseos_version`、`dal_version`、`caps_hash`、`features_hash` |
| | `schema` | v2 | 输出全部命令的机器可读契约（自描述，供应用与测试生成） |
| 能力 | `cap list` / `cap get <name>` / `cap has <name>` / `cap explain <name>` | v2 | 三态；`has` 仅在 `yes` 时 exit 0 |
| 特性 | `feature list` / `feature get <name>` / `feature has <name>` / `feature explain <name>` | v2 | `explain` 输出 reason |
| 显示 | `display info` / `display get brightness` / `display set-brightness <0-100>` / `display get rotation` / `display set-rotation <0|90|180|270>` / `display get hdmi` / `display set-hdmi <on|off>` | v2（info/get 只读优先） | 写操作需对应 capability |
| 音频 | `audio info` / `audio get volume` / `audio set-volume <0-100>` / `audio get mute` / `audio set-mute <on|off>` / `audio get route` / `audio set-route <speaker|headphone|hdmi>` | v2 | |
| 电源 | `power battery` / `power charger` / `power boot-reason` / `power suspend` / `power poweroff` / `power reboot` / `power rtc get` / `power rtc set <epoch_s>` / `power led get` / `power led set <role> <0-100>` | v2 | `suspend/poweroff/reboot` 需 capability |
| 网络 | `network status` / `network wifi status|enable|disable` / `network bt status|enable|disable` / `network mdns status` | v2 | 状态与动作分离 |
| 输入 | `input list` / `input describe <id>` / `input get menu-held` / `input map` | v2 | `map` 输出按键角色映射 |
| 存储 | `storage info` / `storage cards` / `storage expand` / `storage usb-mode <none|adb|mass>` | v2 | |
| 诊断 | `diag snapshot` | v2 | 机器可读的系统快照（`baseos-diag` 的 JSON 对应物） |
| 事件 | `event subscribe <topic>` | v3 | 需 daemon；v2 不实现，接口保留 |

**明确不做**（防止 `baseosctl` 变成第二个大杂烩）：

- 不做 UI/文本渲染（`baseos-splash` 保留）；
- 不做更新（`baseos-update` 保留，但它的决策输入改为 `baseosctl` 的查询结果）；
- 不做包管理、不做网络配置管理（wpa_supplicant 归 frontend 或 systemd 替代品）；
- 不做 feature 开关的**运行时修改**（feature 集合是构建期事实，运行期只读）。

### 6.4 字段契约（关键几组）

`display info --json`：

```json
{ "schema": "baseos.ctl/2", "domain": "display", "verb": "info", "state": "ok",
  "board": "rg34xx", "soc": "allwinner/h700",
  "data": {
    "backend": "fbdev",
    "width": 720, "height": 480, "stride_px": 720, "bpp": 32,
    "rotation": 0,
    "brightness": { "available": true, "cur_pct": 80, "max_raw": 255, "raw": 204 },
    "hdmi": { "available": true, "connected": false, "active": false },
    "vendor_fps_mode": null
  } }
```

`power battery --json`：

```json
{ "schema": "baseos.ctl/2", "domain": "power", "verb": "battery", "state": "ok",
  "board": "rg34xx", "soc": "allwinner/h700",
  "data": { "present": true, "capacity_pct": 74, "status": "Discharging",
            "voltage_mv": 3968, "health": "Good", "charge_only_boot": true } }
```

`cap list --json`：结构见 §4.3，另加 `verified` 字段（来自 §4.4）。

`feature explain --json`：

```json
{ "schema": "baseos.ctl/2", "domain": "feature", "verb": "explain", "state": "ok",
  "data": { "name": "bt_sink", "resolved": true, "reason": "resolved",
            "requires": { "caps": {"network.bluetooth": "yes"}, "facts": {"network.bt.sink_supported": true} } } }
```

`storage info --json`：

```json
{ "schema": "baseos.ctl/2", "domain": "storage", "verb": "info", "state": "ok",
  "data": { "root_slot": "a", "data": { "device": "/dev/mmcblk0p6", "fs": "ext4", "free_mb": 21044 },
            "cards": [ { "slot": 1, "present": true, "fs": "vfat", "label": "SDCARD" },
                       { "slot": 2, "present": false } ],
            "usb_mode": "none", "expand": { "needed": false } } }
```

**字段命名规则**：`snake_case`，单位后缀（`_pct`/`_mv`/`_s`/`_mb`/`_px`），布尔用 `present`/`available`/`supported`
三个词区分「物理存在 / 当前可用 / 契约支持」。

### 6.5 错误输出（统一信封，stderr 只放诊断）

```json
{ "schema": "baseos.ctl/2", "domain": "audio", "verb": "set-volume", "state": "unsupported",
  "error": { "code": "unsupported", "capability": "audio.mixer", "message": "no hardware mixer on this board" } }
```

`message` 允许存在（便于人排查），但**应用不得解析 `message`**，只能读 `state`/`error.code`/`error.capability`。

### 6.6 写操作契约

1. 前置检查：capability 必须为 `yes`（否则 exit 3，**不做任何写入**）；
2. `--dry-run`：输出将要写入的目标（`writes: [{path, value}]`）但不动；
3. 结果：`{ "applied": true, "changed": ["brightness"], "previous": {"brightness": 80}, "current": {"brightness": 60} }`；
4. 幂等：值相同时 `changed` 为空、`applied: true`；
5. 写入失败：`state=io_error`，且必须回读校验（`verify: "readback_mismatch"`）；
6. 破坏性动作（`poweroff`/`reboot`/`suspend`/`storage.expand`/`usb-mode`）：
   需 `--force` 或明确的 capability+feature 双满足，且必须在输出 JSON **之后**才执行（先回包，后动作）。

### 6.7 与既有脚本的关系

| 今天 | v2 | 迁移期 |
|---|---|---|
| `baseos-diag`（人类文本） | 保留；内部改为调 `baseosctl diag snapshot` 渲染 | P4 |
| `baseos-charger`（启动决策） | 逻辑保留；节点访问改走 DAL；决策输入用 `baseosctl power boot-reason`/`input get menu-held` | P3 |
| `systemctl`（兼容壳） | 保留；WiFi/BT 状态查询改 `baseosctl network …` | P4 |
| `timedatectl`（兼容壳） | 保留；RTC 访问改 `baseosctl power rtc` | P4 |
| `expand-storage` / `usb-storage-mode` | 变薄壳，主体进 `baseosctl storage …` | P4 |
| PocketJS compat shim（外仓） | 逐条改为 `baseosctl`，失败回落 | P6 |

### 6.8 契约测试（不需要真机）

```text
tests/contract/
  display/info.json          ← golden 输出（假板 rg34xx-like）
  power/battery.json
  storage/info.json
  feature/explain-bt_sink.json
  cap/list.json
  每个还配 *-unsupported.json, *-unavailable.json
测试流程：baseosctl <cmd> --json --root tests/fixtures/fake-<board>/  → 与 golden 逐字段比对
         （忽略易变字段：uptime、epoch、free_mb 用范围断言）
```

**这组 golden 是 API 稳定性的唯一保障**：字段被改名/删除 → 测试失败 → 必须升 `baseos.ctl/3`。

### 6.9 兼容、风险、验收

**兼容**：`baseosctl` 是新增文件（`overlay/usr/sbin/baseosctl`）。P3 阶段只提供只读命令，
旧脚本继续工作；P4 起旧脚本变薄壳，但**命令行接口和文本输出保持不变**（人类工具兼容性）。

**风险**：

| 风险 | 缓解 |
|---|---|
| sh 版 JSON 生成慢/易错 | 只生成结构化字段，禁止拼复杂字符串；实测 >30 ms 则迁 C（接口不变） |
| 每个域都想让它做点「顺手」的事，接口膨胀 | 命令面在 §6.3 冻结；新增命令需在本文加一行并经评审 |
| 应用绕过 `baseosctl` 继续探测 | 架构门：`grep -rn '/sys\|/proc\|/dev' <应用仓库>` 在 CI 里检查（跨仓库门，§11） |
| `--root` 假板与真机行为漂移 | 假板 golden 每组都必须有一台真机快照佐证（§10.6），漂移则 CI 失败 |

**验收**：

1. `baseosctl schema --json` 能自描述全部命令与字段，且与 golden 一致；
2. 全部只读命令在假板上完全离线可用（不需要真机、不需要 root）；
3. 每条命令的三态在假板上可复现（`ok`/`unsupported`/`unavailable`）；
4. H700 真机上 `baseosctl display info`、`power battery`、`storage info` 与设置页/`baseos-diag` 显示一致（同一份数据）；
5. 任一命令无参数/错参数返回 exit 2 且 stderr 有用法，stdout 无输出。

---

## 7. Device Profile V2 Schema

### 7.1 为什么是「一板一文件 + 四层继承」而不是「一份大 devices.json」

| 方案 | 结论 | 理由 |
|---|---|---|
| 继续一份 `devices.json` 平铺 | 拒绝 | 与 BSP 目录分离，无法与 SoC 事实联合校验；冲突无法按板定位；合并冲突集中在一个文件 |
| 一板一文件 + 继承 | **采用** | 每台设备的差异是局部 diff；新增设备只新增一个文件；schema 可严格；合并冲突天然隔离 |
| YAML + 代码生成 | 拒绝 | 引入新格式与新代码生成步骤，收益不足以抵消「多一种语言」的成本；JSON 已有工具链（`device_profile.py`） |

继承链（**后者覆盖前者，且只允许覆盖 schema 声明为 `inheritable` 的字段**）：

```
distro defaults (pjos/device-defaults.json)     # 全 unknown / 全 false
   ↓
SoC BSP baseline (bsp/<vendor>/<soc>/bsp.json → board_defaults)
   ↓
Board profile   (bsp/boards/<id>/board.json)     ← 唯一允许写「这块板」差异的地方
   ↓
（运行期：只读，不允许覆盖静态事实；用户设置另存 /data/baseos.conf）
```

**关键约束**：运行期**不得**覆盖静态事实。`/data/baseos.conf` 只能覆盖「用户偏好」
（hostname、mdns 开关、`headphone_pop_fix`），不能覆盖面板几何、capability、节点路径。
今天 `assets/baseos.conf` 已经遵守这条（只有 hostname/mdns/ssh/headphone_pop_fix），v2 把它写进契约。

### 7.2 正式 Schema（`$id: pjos.device/2`，节选核心 `$defs`）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://pocketos.dev/schema/pjos.device/2",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "id", "soc", "model", "panel", "storage", "capabilities"],
  "properties": {
    "schema": { "const": "pjos.device/2" },
    "id": { "$ref": "#/$defs/id" },
    "soc": { "type": "string", "pattern": "^[a-z0-9_]+/[a-z0-9_]+$" },
    "vendor_firmware": { "$ref": "#/$defs/vendorFirmware" },
    "identity": { "$ref": "#/$defs/identity" },
    "panel": { "$ref": "#/$defs/panel" },
    "display": { "$ref": "#/$defs/display" },
    "input": { "$ref": "#/$defs/input" },
    "audio": { "$ref": "#/$defs/audio" },
    "power": { "$ref": "#/$defs/power" },
    "network": { "$ref": "#/$defs/network" },
    "storage": { "$ref": "#/$defs/storage" },
    "leds": { "$ref": "#/$defs/leds" },
    "nodes": { "$ref": "#/$defs/nodeOverrides" },
    "capabilities": { "$ref": "#/$defs/capabilities" },
    "features": { "$ref": "#/$defs/featureOverrides" },
    "logo": { "$ref": "#/$defs/logo" },
    "tests": { "$ref": "#/$defs/tests" }
  },
  "$defs": {
    "id": { "type": "string", "pattern": "^[a-z][a-z0-9]{1,31}$" },
    "tri": { "enum": ["yes", "no", "unknown"] },

    "vendorFirmware": {
      "type": "object", "additionalProperties": false,
      "required": ["prefix"],
      "properties": {
        "prefix": { "type": "string" },
        "filename_alias": { "type": "string" },
        "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" }
      }
    },

    "identity": {
      "type": "object", "additionalProperties": false,
      "required": ["model_string", "frontend_family"],
      "properties": {
        "model": { "type": "string" },
        "model_string": { "type": "string" },
        "frontend_family": { "type": "string", "pattern": "^[a-z0-9_]{2,24}$" },
        "product_family": { "type": "string" }
      }
    },

    "panel": {
      "type": "object", "additionalProperties": false,
      "required": ["width_px", "height_px"],
      "properties": {
        "width_px": { "type": "integer", "minimum": 64, "maximum": 4096 },
        "height_px": { "type": "integer", "minimum": 64, "maximum": 4096 },
        "rotation_ccw": { "enum": [0, 90, 180, 270] },
        "bpp": { "enum": [16, 24, 32] },
        "density": { "type": "number", "exclusiveMinimum": 0 },
        "logical_width_px": { "type": "integer" },
        "logical_height_px": { "type": "integer" },
        "touch": { "type": "boolean", "default": false }
      }
    },

    "display": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "backends": { "type": "array", "items": { "enum": ["fbdev", "drm"] }, "minItems": 1 },
        "default_backend": { "enum": ["fbdev", "drm"] },
        "brightness": {
          "type": "object", "additionalProperties": false,
          "properties": {
            "available": { "$ref": "#/$defs/tri" },
            "max_raw": { "type": "integer" },
            "steps": { "type": "integer" }
          }
        },
        "hdmi": { "type": "boolean" }
      }
    },

    "input": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "keyboard_name": { "type": "string" },
        "keyboard_event_hint": { "type": "string" },
        "button_map": { "type": "object", "additionalProperties": { "type": "string" } },
        "menu_held_source": { "enum": ["evdev", "gpio"] },
        "hotkeys": { "type": "array", "items": { "type": "string" } },
        "axes": { "type": "array", "items": { "enum": ["x", "y", "rx", "ry"] } }
      }
    },

    "audio": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "card_name": { "type": "string" },
        "mixer_control": { "type": "string" },
        "max_volume_raw": { "type": "integer" },
        "headphone_detect": { "type": "boolean" },
        "amp_repair": { "enum": ["yes", "no", "unknown"] }
      }
    },

    "power": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "battery": { "type": "boolean" },
        "charger": { "type": "boolean" },
        "rtc": { "type": "boolean" },
        "suspend": { "type": "boolean" },
        "charge_only_boot": { "type": "boolean" },
        "pmic_quirks": {
          "type": "object", "additionalProperties": false,
          "properties": { "os_sleep": { "type": "integer" }, "work_led": { "type": "boolean" } }
        }
      }
    },

    "network": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "wifi": { "type": "boolean" },
        "wifi_driver": { "type": "string" },
        "wifi_timing": {
          "type": "object", "additionalProperties": false,
          "properties": {
            "off_cs": { "type": "integer" }, "cut_cs": { "type": "integer" },
            "first_cs": { "type": "integer" }
          }
        },
        "bluetooth": { "type": "boolean" },
        "bt_sink": { "type": "boolean" },
        "ethernet": { "type": "boolean" }
      }
    },

    "storage": {
      "type": "object", "additionalProperties": false,
      "required": ["roles"],
      "properties": {
        "roles": {
          "type": "object", "additionalProperties": false,
          "required": ["root_a", "userdata", "primary_fat"],
          "properties": {
            "root_a": { "type": "integer", "minimum": 1 },
            "root_b": { "type": "integer", "minimum": 1 },
            "boot": { "type": "integer", "minimum": 1 },
            "userdata": { "type": "integer", "minimum": 1 },
            "primary_fat": { "type": "integer", "minimum": 1 },
            "backup_slot_role": { "enum": ["root_b", "overlay"] }
          }
        },
        "cards": {
          "type": "array",
          "items": {
            "type": "object", "additionalProperties": false,
            "required": ["slot"],
            "properties": { "slot": { "type": "integer" }, "removable": { "type": "boolean" },
                            "controller": { "type": "string" } }
          }
        },
        "expand_target": { "enum": ["userdata", "primary_fat", "none"] },
        "second_slot_frontend": { "type": "boolean" }
      }
    },

    "leds": { "type": "array", "items": { "type": "object" } },

    "nodeOverrides": {
      "type": "object",
      "additionalProperties": {
        "type": "object", "additionalProperties": false,
        "properties": {
          "backend": { "enum": ["sysfs", "hal", "fake"] },
          "node": { "type": "string", "pattern": "^/" },
          "glob": { "type": "string", "pattern": "^/" },
          "subpath": { "type": "string" },
          "transform": { "enum": ["int", "str", "milli_to_int", "bool01", "map"] },
          "map": { "type": "object" },
          "writable": { "type": "boolean" }
        }
      }
    },

    "capabilities": {
      "type": "object",
      "additionalProperties": { "$ref": "#/$defs/tri" }
    },

    "featureOverrides": {
      "type": "object",
      "additionalProperties": {
        "type": "object", "additionalProperties": false,
        "required": ["enabled", "reason"],
        "properties": { "enabled": { "const": false }, "reason": { "type": "string", "minLength": 8 } }
      }
    },

    "logo": {
      "type": "object", "additionalProperties": false,
      "properties": { "source": { "enum": ["generated", "vendor"] },
                      "width_px": { "type": "integer" }, "height_px": { "type": "integer" } }
    },

    "tests": {
      "type": "object", "additionalProperties": false,
      "properties": { "required_layers": { "type": "array", "items": { "enum": ["T0","T1","T2","T3","T4"] } },
                      "device_verified": { "type": "string" } }
    }
  }
}
```

**Schema 纪律**：

| 规则 | 后果 |
|---|---|
| `additionalProperties: false` **全局** | 字段名拼错立刻失败（今天 `devices.json` 的未知字段被忽略） |
| 缺字段 ≠ 默认值 | 缺字段时 capability 推导为 `unknown`（§4.2），不是静默 `false` |
| `features.*` 只能 `enabled:false` + `reason` | 板级无法新增 feature（§5.5） |
| 所有长度/像素带单位后缀 | 消灭 `width`/`width_px` 混用（今天 `bootlogo_width` 与 `panel.width` 语义重叠） |

### 7.3 两个完整例子

**H700 板（等价迁移自 `devices.json` 的 `rg34xx`）**：

```json
{
  "schema": "pjos.device/2",
  "id": "rg34xx",
  "soc": "allwinner/h700",
  "vendor_firmware": { "prefix": "RG34XX-" },
  "identity": { "model": "RG34XX", "model_string": "RG34xx", "frontend_family": "h700" },
  "panel": { "width_px": 720, "height_px": 480, "rotation_ccw": 0, "bpp": 32, "density": 2 },
  "display": { "backends": ["fbdev", "drm"], "default_backend": "fbdev",
               "brightness": { "available": "yes", "max_raw": 255 }, "hdmi": true },
  "input": { "keyboard_name": "ANBERNIC-keys", "keyboard_event_hint": "event1",
             "menu_held_source": "evdev", "axes": ["x", "y"] },
  "audio": { "card_name": "audiocodec", "mixer_control": "Playback", "max_volume_raw": 100,
             "amp_repair": "yes" },
  "power": { "battery": true, "charger": true, "rtc": true, "suspend": true,
             "charge_only_boot": true },
  "network": { "wifi": true, "wifi_driver": "8821cs", "wifi_timing": {"off_cs": 500, "cut_cs": 185, "first_cs": 225},
               "bluetooth": true, "bt_sink": true },
  "storage": { "roles": { "root_a": 5, "userdata": 6, "primary_fat": 7, "boot": 4 },
               "cards": [ { "slot": 1, "removable": false }, { "slot": 2, "removable": true, "controller": "sdc2" } ],
               "expand_target": "userdata", "second_slot_frontend": true },
  "capabilities": { "input.vibration": "no", "input.touch": "no", "display.hdmi": "yes" },
  "logo": { "source": "generated", "width_px": 720, "height_px": 480 }
}
```

**跨 SoC 板（A133 Plus / Smart Pro 示意）**：

```json
{
  "schema": "pjos.device/2",
  "id": "smartpro",
  "soc": "allwinner/a133",
  "vendor_firmware": { "prefix": "TRIMUI-SMARTPRO-" },
  "identity": { "model": "TRIMUI Smart Pro", "model_string": "SmartPro", "frontend_family": "tg5040" },
  "panel": { "width_px": 1280, "height_px": 720, "rotation_ccw": 0, "bpp": 32, "density": 2 },
  "display": { "backends": ["drm"], "default_backend": "drm", "brightness": { "available": "yes" }, "hdmi": false },
  "input": { "keyboard_name": "TRIMUI-keys", "menu_held_source": "evdev", "axes": ["x", "y", "rx", "ry"] },
  "audio": { "card_name": "audiocodec", "mixer_control": "Playback" },
  "power": { "battery": true, "charger": true, "rtc": true, "suspend": true, "charge_only_boot": "unknown" },
  "network": { "wifi": true, "bluetooth": true, "bt_sink": true },
  "storage": { "roles": { "root_a": 5, "userdata": 6, "primary_fat": 7, "boot": 4 },
               "cards": [ { "slot": 1, "removable": true } ], "expand_target": "userdata" },
  "features": { "audio_amp_repair": { "enabled": false, "reason": "A133 codec has no amp latch to repair" } }
}
```

> 注意最后那个 `features`：**板级的唯一影响方式是 opt-out**，而且必须给理由。
> 这份 profile 没有半行代码，也没有板名出现在 distro 里。

### 7.4 v1 → v2 字段映射（无损升级）

| v1 字段（`devices.json`） | v2 路径 | 备注 |
|---|---|---|
| `id` | `id` | 不变 |
| `model` | `identity.model` | |
| `model_string` | `identity.model_string` | |
| `stockmod_prefix` | `vendor_firmware.prefix` | |
| `filename_alias` | `vendor_firmware.filename_alias` | |
| `baseos_device` | `identity.frontend_family` | **语义澄清**：它从来不是「device」，而是「卡上前端目录族」（见 L07） |
| `bootlogo_width/height` | `logo.width_px/height_px` + `panel.width_px/height_px` | 拆开：物理面板 vs 素材尺寸 |
| `panel_rotation_ccw` | `panel.rotation_ccw` | |
| `wifi` | `network.wifi` + `capabilities["network.wifi"]` | 单一声明，推导产出 cap |
| `bluetooth` | `network.bluetooth` + `capabilities["network.bluetooth"]` | 同上 |
| —（新） | `power.*`、`audio.*`、`input.*`、`storage.roles`、`network.wifi_timing`、`power.pmic_quirks` | 从 rcS/脚本里提取的事实 |
| `manifest/prepared/*.json → layout` | 不迁移 | 保持为「厂商输入快照」，由 `bsp/lock.json` 校验 |

### 7.5 兼容方式（双栈期）

- `tools/device_profile.py` 变为**适配器**：`schema==1` 时按 §7.4 在内存里升到 v2 再校验；
  `schema==2` 时直接用 JSON Schema 校验。
- 构建脚本仍吃 `device_profile.py shell <target>` 的扁平环境变量（一期不变），
  但变量值改为**从 v2 推导**，因此 `build-rootfs.sh`/`build-image.sh` 的接口零改动。
- 对外命令行 `./build-all.sh rg34xx` 保持不变（`--board` 作为等价别名，二期切换默认）。
- P2 结束时删除 `devices.json` 与 v1 适配器（`devices.json` → 11 份 `bsp/boards/*/board.json`），
  保留一个 `tools/profile_migrate.py --check` 用于比对历史。

### 7.6 风险与验收

**风险**：

| 风险 | 缓解 |
|---|---|
| Schema 过度设计（字段没人用） | 每个字段必须有一个构建期或运行期消费者（`grep` 可验证），否则删 |
| 迁移时字段语义漂移（`baseos_device` → `frontend_family`） | 一次性改名 + 明确 deprecation；旧名在适配器里保留一个版本并打警告 |
| 一板一文件导致「共享字段重复」 | SoC `board_defaults` 提供默认值；重复出现在 3 个以上文件即提升为 SoC 默认 |
| Schema 版本升级成本 | schema 版本进构建门；升级必须同时提供 migrate 脚本 |

**验收**：

1. 11 台现有设备全部迁移后，`device_profile.py shell <id>` 输出与今天**逐字段相同**（哈希门）；
2. 未知字段 / 拼错字段名 → 构建失败并指向 schema 行；
3. 新增一台同 SoC 设备只需 `bsp/boards/<new>/board.json` 一个文件；
4. `baseosctl version` 能报出当前 profile 的 schema 版本与 ids。

---

## 8. BSP Package Layout

### 8.1 完整树（含 distro 侧对照）

```text
pjos/                                  # distro 侧（原 overlay/ + manifest/ + src/ 的可移植部分）
  features/<domain>.json               # feature registry（§5.3）
  device-defaults.json                 # Profile 继承链顶端
  capabilities.registry.json           # capability 名字白名单（§4.1）
  boot/stages.json                     # 启动阶段清单（early-init / post-modules / pre-frontend）
  tools/                               # resolve/generate/validate（Python，host 侧）
overlay/                               # distro rootfs 骨架（MUST NOT 含板名）
  etc/init.d/rcS                       # 改为「按 stages.json 执行声明动作」
  usr/sbin/{baseosctl,baseos-*,frontend-session,…}
  usr/share/baseos/…
bsp/
  allwinner/_soc_family.json           # 厂商级共性（可选）
  allwinner/h700/
    bsp.json
    nodes.json
    harvest.list
    kernel/abi.json
    kernel/modules/{h700_late_usb,h700_speaker_amp}/
    overlay/etc/…                      # SoC 片段（白名单路径）
    tests/{kernel-abi.py,dal-nodes.py}
  allwinner/a133/
    …
  boards/rg34xx/board.json
  boards/…/board.json
  boards/fake-min/…
  boards/fake-rich/…
  boards/fake-degraded/…
  matrix.json
  lock.json
```

### 8.2 overlay 片段的合并规则（确定性的关键）

合并顺序：`overlay/`（distro） → `bsp/<soc>/overlay/` → `bsp/boards/<id>/overlay/`。

| 规则 | 说明 |
|---|---|
| **文件级后写者胜** | 同路径文件整体替换，不做行级合并（行级合并不可审计） |
| **只允许白名单目录** | BSP overlay 只能写：`etc/init.d/`、`usr/lib/modules/`、`usr/sbin/`（且文件名必须不含板名）、`etc/baseos/` |
| **不允许删除** | 片段不能表达「删掉 distro 的文件」；需要删除时改 distro |
| **静态校验** | `tools/validate_bsp.py` 检查：白名单、无板名、无 `#!/bin/sh` 之外的二进制、文件权限确定性 |
| **等价门** | H700 的 SoC 片段为空集合（今天所有板级内容先在 distro），因此合成结果必须与 `overlay/` **逐字节相同**（`tar --sort=name --mtime=@0` 比较） |

> 为什么先让 H700 的 SoC 片段为空？因为「搬运」这一步的风险必须可被哈希门完全覆盖：
> 搬之前与搬之后产物相同，才能证明搬对了。真正的搬入发生在 P2 的第二个 PR（`h700_*` 模块、
> rcS 的 H700 段落），每个 PR 都以「镜像哈希不变」为准入条件。

### 8.3 harvest 拆分

| 文件 | 内容 | 谁维护 |
|---|---|---|
| `bsp/<soc>/harvest.list` | V3 基线闭包（glibc/soname/GPU/daemon），带 capability 分组注释 | SoC 维护者 |
| `bsp/boards/<id>/harvest.add` | 板级增量（极少数板独有的 daemon/资源） | 板维护者 |
| `bsp/<soc>/bsp.json → harvest.capability_groups` | capability → 路径组（§4.6），决定「缺文件是否允许」 | SoC 维护者 |
| `manifest/prepared/<board>.json → harvest.sha256` | 快照哈希 | 构建系统 |

校验链（沿用今天的 `verify_harvest.py`，改为多清单 + 分组）：

```
prepared.tar  ⊇  soc/list ∪ board/add
缺失路径若属于某个 capability 组且该 cap != yes  → 允许
其余缺失 → 失败（提示 refresh prepared 或补清单）
```

### 8.4 `src/` 的归属与 ABI guard

| 今天 | v2 位置 | 处理 |
|---|---|---|
| `src/h700-speaker-amp/` | `bsp/allwinner/h700/kernel/modules/h700_speaker_amp/` | 目录名可含 SoC（在 bsp 内允许） |
| `src/h700-speaker-amp/profiles.json` | `bsp/allwinner/h700/kernel/abi.json` | key 从 target 改为 `kernel_identity`（§2.6） |
| `src/h700-late-usb/` | 同上 | |
| `src/axp-off.c`、`src/boot-clock.c` | `bsp/allwinner/h700/`（SoC 级工具） | 名字改为通用名（`poweroff-pmic`、`boot-clock`）以便 distro 侧调用不出现板名 |
| `src/fbsplash.c` | 保留在 `src/`（**与板无关**，按 profile 渲染） | 只消费 profile |
| `src/native-*`、`experiments/h700-boot-speed/` | `bsp/allwinner/h700/boot/native/` | 原生加载器是 H700 专有事实 |
| `src/adbd-patches/`、`src/apply-pocketjs-input.py` | 保留在 `src/`（与板无关） | |

**ABI guard 契约**（写进 `bsp.json` 与模块元数据）：

```
module: h700_speaker_amp
supports: [{ kernel_identity: "sha256:8eeb…", release: "4.9.170", banner: "Linux version 4.9.170 …" }]
on_mismatch: skip_and_log        # 绝不允许 "guess offset"
verify_stage: build-time (kernel_abi.py) + runtime (load guard)
```

### 8.5 per-board 测试

| 层级 | 位置 | 跑在哪 |
|---|---|---|
| BSP 契约（ABI、节点映射、harvest 完整性） | `bsp/<soc>/tests/` | x86 + prepared 输入（不需要真机） |
| 板契约（profile schema、caps/features 推导、logo、分区角色） | `bsp/boards/<id>/tests/` | x86 |
| 假板回归（DAL/baseosctl golden） | `tests/contract/` | x86 |
| 真机验证（启动、抓帧、`baseosctl snapshot`） | `bsp/boards/<id>/evidence/` + `validate-on-device.sh` | 真机/农场 |

### 8.6 `lock.json` 与 provenance

```json
{ "schema": "pjos.bsp.lock/2",
  "socs": { "allwinner/h700": { "version": "1", "kernel_release": "4.9.170",
            "toolchain": "ghcr.io/loveretro/h700-toolchain@sha256:bf5d…" } },
  "boards": { "rg34xx": { "vendor_input_sha256": { "boot_prefix": "fb75…", "harvest": "d1c8…" } } } }
```

构建期：`lock` 与 `manifest/prepared/<board>.json` 的哈希必须一致；不一致 → 失败。
`lock` 变更必须单独一个 commit（避免「顺手更新了 lock」淹没在功能改动里）。

### 8.7 兼容、风险、验收

**兼容**：`overlay/` 保持存在（distro 骨架），`bsp/` 为新增；`src/` 的迁移在 P2 分多个 PR 完成，
每个 PR 都能独立构建出哈希相同的镜像。

**风险**：

| 风险 | 缓解 |
|---|---|
| overlay 片段合并引入不可见行为（某人放了同名文件） | 白名单 + 「BSP 片段清单进构建日志」，并在 `baseosctl version` 里暴露 `overlay_fragments[]` |
| `src/` 搬家打乱 git 历史 | 用 `git mv`（保留 blame）；一次 PR 只搬一个模块 |
| 模块改名导致 distro 调用点遗漏 | 架构门：distro 侧出现 `h700` 即失败（§2.5），反向保证不漏 |

**验收**：

1. `bsp/` 之外板名命中数为 0；
2. 每个 BSP overlay 片段只出现在白名单目录；
3. `bsp/lock.json` 与 prepared 哈希一致；
4. 删除 `bsp/boards/rg34xx/` 后 `./build-all.sh` 报「未知 board」并列出可用 board。

---

## 9. Build Pipeline 变化

### 9.1 现状流水线（按依赖）

```text
fetch-prepared / prepare-stock   →  work/<target>/{boot-prefix.img,stock-harvest.tar,source.json}
build-tools                      →  work/tools/*（busybox、fbsplash、adbd、gptslot…）
build-audio-module <target>      →  work/<target>/audio-module/*.ko
build-rootfs <target>            →  work/<target>/rootfs.tar（overlay + harvest + 模块 + baseos-release）
test-boot-qemu <target>          →  QEMU 冒烟（init 链）
native build-release.py <target> →  work/<target>/native-release/
build-image <target>             →  work/<target>/baseos-<target>.img
build-update <target>            →  *.bosupd
build-all                        →  zip + 校验和
```

**问题**：所有阶段都以 `target` 为唯一坐标，因此每台设备都重复编译工具与模块；
且 `build-rootfs.sh` 里 12 处硬编码板级内容（L11/L12）使「同 SoC 复用」不可能。

### 9.2 v2 流水线（两级坐标：SoC 构件 + 板构件）

```text
① resolve      board.json + bsp.json + distro defaults → resolved.json（内存）
               （含 caps（§4）+ features（§5）+ 继承后的 profile）
② validate     G01–G06（见 §9.3）
③ soc-build    per SoC（缓存）：内核模块、ABI 表、SoC overlay 片段、SoC harvest 基线
               缓存键 = soc + kernel_identity + bsp version + toolchain sha
④ board-stage  per board：合成 overlay（§8.2）、harvest（§8.3）、生成
               /etc/pjos/{device.json,capabilities.json,features.json}、baseos-release
⑤ compose      rootfs.tar → image（沿用 lib_image/mkgpt/kernel_gzip/native）
⑥ verify       G07–G12（§9.3）→ 产物 + 证据 + matrix 记录
```

**收益**：

- 加 SoC 级设备成本 O(1)（除新 SoC 首次）；加同 SoC 板成本 = 一次 board-stage + compose；
- 50 台设备、6 个 SoC 的情况下，SoC 层只构建 6 次；
- 缓存键与板无关 → 换板名不重建内核模块（今天是按 target 重复构建）。

### 9.3 构建门（新增/加强）

| 门 | 阶段 | 检查 | 失败语义 |
|---|---|---|---|
| G01 profile schema | validate | v2 JSON Schema（严格未知字段） | 失败 |
| G02 板名扫描 | validate | distro 内板名命中（§2.5） | 失败 |
| G03 capability 一致性 | validate | 手写 vs 推导 vs prepared 快照（§4.2） | 失败 |
| G04 feature 图 | validate | 环、缺失依赖、冲突、degrade 目标存在 | 失败 |
| G05 node map 完整性 | validate | 每个 `caps=yes` 的域必须有节点映射；`caps=no` 的域禁止映射 | 失败 |
| G06 BSP overlay 白名单 | validate | §8.2 规则 | 失败 |
| G07 harvest 完整性 | compose 前 | §8.3 多清单 + 分组 | 失败 |
| G08 kernel ABI | soc-build | `kernel_abi.py` + 模块声明的 identity | 失败（模块层可降级为 `skipped` 并记录，但必须显式声明 `on_mismatch`) |
| G09 生成物自洽 | board-stage | `features.json` 引用的 feature 都在 registry；`device.json` 与 profile 同源 | 失败 |
| G10 字节不变门（迁移期） | compose | H700 产物 `rootfs.tar` / `.img` 哈希与基线一致 | 失败（仅 P1–P3 期间强制） |
| G11 镜像自检 | compose 后 | `BASEOS_TARGET`/`BASEOS_BOARD`/caps 哈希进 p5 校验 | 失败 |
| G12 契约测试 | verify | `tests/contract/` golden 全绿 | 失败 |

### 9.4 坐标与兼容

- 一期：`./build-all.sh <target>` 与 `./build-rootfs.sh <target>` 保持不变（内部按 board 解析）；
- 二期：`--board <id>` 为正式形式，`<target>` 作为别名（等价，打印一次 deprecation 警告）；
- `work/` 布局变化（**需要**，否则缓存无法按 SoC 复用）：

```text
work/
  prepared/<board>/           # 厂商输入（原 work/<target>/ 的输入部分）
  soc/<soc>/                  # SoC 级构件缓存（模块、ABI 表、片段）
  boards/<board>/             # 板级产物（rootfs.tar、img、bosupd、resolved.json、logs）
  tools/                      # 共享工具（不变）
```

  `cache-pack.sh`/`fetch-prepared.sh` 随路径调整，但**数据格式不变**（仍是 boot-prefix + harvest + source.json）。

### 9.5 确定性

- 所有生成物禁用时间戳与随机值（`SOURCE_DATE_EPOCH`、`tar --mtime=@0 --sort=name --owner=0 --group=0`）；
- `features.json` 的 `hash` 是内容的哈希，不含构建时间；
- `resolved.json` 输出前按 key 排序，便于 diff（review 时能直接看出「这台设备解析出了什么」）；
- 构建日志里打印 `input_sha256[]`（profile、bsp、lock、prepared），**这就是可复现构建的凭证**。

### 9.6 风险与验收

**风险**：

| 风险 | 缓解 |
|---|---|
| 两级缓存导致「用了过期 SoC 构件」 | 缓存键含 kernel_identity + toolchain sha + bsp version；命中前校验输入哈希 |
| `work/` 路径迁移打断既有 release 脚本 | 保留一个版本的「路径兼容软链」（`work/<target>` → `work/boards/<target>`） |
| 字节不变门在 P2 之后失效（确实改了内容） | G10 只在迁移期强制；之后由 G11 + 契约测试 + 设备矩阵接棒 |

**验收**：

1. P1 结束时 `./build-all.sh` 的 11 个 `rootfs.tar` 哈希与改动前一致；
2. 新增一台同 SoC 板：`build-all.sh --board <new>` 只跑 board-stage + compose（日志中 SoC 阶段显示 cache hit）；
3. 构建日志包含 `input_sha256[]` 且同一 commit 两次构建哈希相同；
4. 任一新增门被违反时，构建失败信息里含「违反了哪条规则 + 怎么改」。

---

## 10. Fake Board 设计

### 10.1 目的（为什么假板不是玩具）

三个真实问题，假板是唯一可行的解法：

1. **多设备 CI 不可能全用真机**：50 台设备不可能每台都在 CI 上。但「第 51 台设备的 profile 是否会
   污染 distro」必须在合并前回答。
2. **架构门需要在没有真机的情况下可测**：板名扫描、schema、feature 推导、DAL 三态——
   这些都能在 x86 上验证，前提是有一块「可声明为任意形态」的板。
3. **已有的先例**：`baseos-diag` 的 `BASEOS_DIAG_ROOT` 与 `tests/make_stock_fixture.py`
   已经在做「用前缀目录模拟根」，假板是把这条先例**制度化**，而不是新发明。

> 边界：假板**证明不了**内核、时序、功耗、触摸标定、WiFi 吞吐。它证明的是**架构正确性**。
> 两者不可互相替代（§10.6）。

### 10.2 假 BSP 与假板族

假板放在 `bsp/boards/fake-*`，走**完全相同的** schema 与校验（这是关键：假板不能有特权）。

| 假板 | 目的 | 关键特征 |
|---|---|---|
| `fake-min` | 最小合法设备 | 无 WiFi、无 BT、无电池、无背光、fbdev、单存储；`caps` 大多 `no` |
| `fake-rich` | 全能力设备 | 全 caps `yes`、drm+fbdev、HDMI、双卡、触摸、震动、LED |
| `fake-degraded` | 声明有但当前不可读 | 节点存在性由 fixture 控制；用于测 `unavailable`/`not_ready` |
| `fake-lying` | 反面：声明 `yes` 但节点缺失 | **必须**让构建/测试失败或产出明确 `unavailable`；用于验证「不静默降级」 |
| `fake-liar`(schema) | 故意拼错字段/未知字段 | 用于验证 G01 门 |

`bsp/boards/fake-*/` 也必须有 `soc` 指向一个 `bsp/fake/<soc>/bsp.json`，其中 `backend: "fake"`。

### 10.3 fixture 树（`--root` 的统一约定）

```text
tests/fixtures/<board>/root/
  sys/class/power_supply/<pmic>-battery/{capacity,status,voltage_now,boot_mode,os_sleep}
  sys/class/backlight/*/{brightness,max_brightness}
  sys/class/leds/*/{brightness,max_brightness}
  sys/class/net/wlan0/{operstate,address}
  sys/class/input/event0/...
  sys/kernel/debug/dispdbg/...
  proc/meminfo, proc/cmdline, proc/mounts
  dev/{fb0,dri/card0,input/event0,mmcblk0p5,mmcblk0p6,mmcblk0p7}
  etc/pjos/{device.json,capabilities.json,features.json}
  etc/baseos-release
```

约定：

- `baseosctl --root <dir>` 与 `--root` 下的相对路径完全等价于真机的绝对路径（与 `BASEOS_DIAG_ROOT` 同义，
  P3 起统一为一个环境变量 `BASEOS_ROOT`，旧名保留为别名）。
- fixture **由生成器产出**（`tests/make_fake_board.py --board fake-rich --out …`），不手写、
  不进 git 大文件；生成器本身用 `bsp/boards/fake-*/board.json` 作为输入——**假板也走 profile**。
- 坏节点用「缺失文件」或「内容为 `error`」表示，`io_error` 用不可读权限表示。

### 10.4 假板的三种状态矩阵

| 场景 | fixture | 期望 |
|---|---|---|
| capability 没有 | profile `caps: no` + 无节点 | `unsupported`, exit 3 |
| capability 有，节点缺失 | profile `yes` + 删节点 | `unavailable`, exit 4（**不是** unsupported） |
| capability 有，值格式非法 | 节点内容 `garbage` | `io_error`, exit 6（不得返回 0 或崩溃） |
| 声明 `yes` 但 SoC 无物理声明 | 改 bsp.json | **构建失败**（G03） |
| feature 依赖缺失 | 改 caps | `feature has` = 1，`explain` 给 reason |

### 10.5 「第 51 台设备测试」（本设计的核心回归）

目标：**证明新增设备只碰 `bsp/boards/<new>/`，且期间不修改任何既有设备的行为。**

实现为 CI 任务 `tests/fake-board/generate-51st.sh`：

```text
1. 复制 bsp/boards/fake-rich → bsp/boards/fifty-first（真实设备不存在）
2. 只允许改：id、soc（指向 fake SoC）、panel 尺寸、features opt-out 一条
3. 断言：
   a. validate 全绿（G01–G06）
   b. build-all --board fifty-first 成功
   c. 产物里 baseosctl cap/feature/display/power 全部可用（在 fixture 上）
   d. git diff --stat 只包含 bsp/boards/fifty-first/  （由任务本身构造，故校验的是 #4）
   e. 既有 fake-rich 的 golden 输出**未变化**
4. 清理
```

第 `d` 项是**对开发者的门**，不是对脚本：任何人发 PR 声称「支持新设备」时，
CI 的 `changed-files` 检查会拒绝「同时修改了 `overlay/`、`runtime/`、`pjos/features/` 以外的新板支持 PR」——
例外必须显式标注 `arch-change` 标签并说明为什么这不是纯板级新增。

### 10.6 假板不能替代什么

| 假板能证明 | 假板不能证明 |
|---|---|
| profile/schema/caps/features 推导正确 | 内核能启动、模块能加载 |
| DAL 三态与 baseosctl 契约 | 实际时序（WiFi 上电、PMIC 挂起） |
| distro 里没有板名/节点字面量 | 触摸坐标与旋转是否真的匹配 |
| 构建流水线可用、产物自洽 | 温度/功耗/稳定性 |
| 「第 51 台设备」不动别处 | 真机 UI 表现 |

因此 CI 分两层：**假板层（每次 PR）** + **真机层（nightly / 发布前）**（§11）。

### 10.7 风险与验收

**风险**：

| 风险 | 缓解 |
|---|---|
| 假板 golden 与真机漂移（假板通过、真机错） | 每组 golden 必须有一条真机快照作为「锚」，锚变了就要求更新 golden（`evidence/<board>/anchor.json`） |
| 假板变成「第二个实现」（为通过测试而写的假逻辑） | 假板只能通过 fixture 数据改变结果，禁止 `if fake` 分支（架构门禁止 `fake` 出现在 `overlay/`） |
| 假板测试跑得慢 | fixture 生成 <1 s，全部契约测试目标 <30 s |

**验收**：

1. 四个假板在 x86 上全部跑通 `baseosctl` 只读命令；
2. `fake-lying` 能让 G03 失败（证明一致性检查有效）；
3. 「第 51 台设备」脚本在 CI 中 <3 min 完成；
4. `overlay/` 里不出现 `fake` 字样。

---

## 11. 多设备 CI

### 11.1 五层测试（T0–T4）

| 层 | 名称 | 跑在哪 | 时长目标 | 内容 |
|---|---|---|---|---|
| **T0** | 静态架构门 | 每次 PR（x86，秒级） | <20 s | 板名扫描（§2.5）、profile schema（G01）、feature 图（G04）、node map 完整性（G05）、overlay 白名单（G06）、`lock` 一致性 |
| **T1** | 假板契约 | 每次 PR | <90 s | `baseosctl` golden（§6.8）、caps/features 推导、DAL 三态、fake 四板 |
| **T2** | 构建矩阵（冒烟） | 每次 PR（受影响 board/soc） | <8 min | 对**变更影响到的** board 跑 board-stage；对受影响的 SoC 跑一次 soc-build；产出 `rootfs.tar` 哈希 |
| **T3** | 全矩阵构建 | nightly | <90 min | 全部 board × 全部 gate（G07–G12），输出 `matrix-report.json` |
| **T4** | 真机验证 | nightly（有机器时）/ 发布前（必须） | 人工+自动 | 启动、抓帧、`baseosctl snapshot` 与 golden 比对、电池/充电/无线冒烟 |

**PR 快门的取舍**：T2 只构建「受影响」的 board（按 `bsp/matrix.json` 的依赖：改 `bsp/allwinner/h700/**` → 影响该 SoC 全部板；改 `bsp/boards/rg34xx/**` → 只影响一台）。这是 50 台设备下唯一可行的做法。

### 11.2 矩阵定义 `bsp/matrix.json`

```json
{
  "schema": "pjos.matrix/2",
  "socs": {
    "allwinner/h700":  { "tier": "supported", "boards": ["rg28xx","rg34xx","rg34xxsp","rg35xxplus","…"] },
    "allwinner/a133":  { "tier": "experimental", "boards": ["smartpro"] },
    "fake/*":          { "tier": "ci", "boards": ["fake-min","fake-rich","fake-degraded","fake-lying"] }
  },
  "release": { "required_tiers": ["supported"], "warn_tiers": ["experimental"] },
  "device_runs": { "rg34xx": "nightly", "rg35xxplus": "weekly" }
}
```

| tier | 含义 | CI 要求 | 发布 |
|---|---|---|---|
| `supported` | 承诺可用 | T2 + T3 + T4 nightly | 进发布矩阵，声明 caps 必须 verified |
| `experimental` | 可构建，未承诺 | T2 + T3 | 进发布矩阵，标记 experimental |
| `ci` | 假板 | T0–T2 | 不发布 |
| `retired` | 曾支持 | 不构建 | 只在历史矩阵中出现 |

### 11.3 变更检测与预算

```text
changed paths → 影响集合：
  bsp/<vendor>/<soc>/**      → 该 SoC 的全部 board（T2 全跑）
  bsp/boards/<id>/**         → 仅 <id>
  pjos/features/**           → 全部 board（feature 是全局的）—— 但仍用 T1 假板先挡住
  pjos/**、tools/**、overlay/** → 全部 board（distro 变更）
```

预算（PR）：
- T0 <20 s、T1 <90 s、T2 <8 min、总计 P95 <12 min；
- 超预算时的降级策略：T2 只跑「1 个代表板 + 变更板」，其余进 nightly。**不允许**为了速度关掉 T0/T1。

### 11.4 发布矩阵（让「支持」成为可审计的声明）

`manifest/release/<version>/matrix.json`：

```json
{ "schema": "pjos.release.matrix/2", "version": "1.5.2",
  "boards": {
    "rg34xx": { "tier": "supported", "image_sha256": "…", "update_sha256": "…",
                "caps_verified": ["network.wifi","display.backlight","audio.mixer"],
                "caps_claimed_unverified": ["display.hdmi"],
                "features_hash": "sha256:…", "last_device_run": "2026-08-28",
                "status": "ok" },
    "smartpro": { "tier": "experimental", "…": "…", "status": "degraded",
                  "reason": "wifi unavailable at boot in 2/10 runs" } } }
```

规则：

- 状态取值：`ok` / `degraded` / `mismatch`（声明与实测不符）/ `untested`；
- `mismatch` 必须阻断发布（否则 capability 声明会长期说谎，§4.4）；
- `features_hash` 进矩阵 → 任何设备的 feature 集合变化在发布 diff 中可见。

### 11.5 真机农场最小方案

不必买齐设备。最小可行：

1. **每 SoC 至少一台**代表机（H700 一台、A133 一台）跑 nightly；
2. 其余设备按 `device_runs` 频率轮转（weekly）；
3. 自动验证只做**可自动化**的部分：启动成功（串口/日志）、`baseosctl version|cap list|feature list` 快照、
   抓一张 fb 截图（像素哈希容差）、`dmesg` 错误白名单扫描；
4. 其余（电池曲线、扬声器音质、手感）进人工 checklist，结果写回 `evidence/`。

### 11.6 风险与验收

**风险**：

| 风险 | 缓解 |
|---|---|
| 全矩阵构建时间随设备线性增长，最终不可承受 | 两级缓存（§9.2）+ tier 分层 + nightly 分担；每季复核 P95 |
| 真机农场维护成本被低估 | 只承诺「每 SoC 一台」，其余按需；设备清单写进 `matrix.json` 而不是 CI 脚本 |
| 门太多导致开发者绕过（加豁免注释） | 豁免必须带 reason 且被统计；CI 输出「本 PR 豁免数」，连续上升则评审阻断 |

**验收**：

1. 改 `overlay/` 里任意一行 → T2 覆盖全部 `supported` 板；
2. 新增一台 `experimental` 板 → PR 只跑该板（证明依赖图正确）；
3. nightly 产出 `matrix-report.json`，包含每板的 gates 结果与哈希；
4. 发布前 `mismatch` 存在则发布脚本拒绝出包。

---

## 12. 迁移路线图

### 12.1 原则

1. **每步一个可合并 PR**，独立可回滚（revert 单个 PR 不破坏后续）；
2. **H700 行为不变**由 G10 字节不变门守护（P1–P3）；
3. 先**加数据**（影子），再**改消费者**（切换），最后**删旧**（清理）——三步永不合并进同一个 PR；
4. 每一步都有「退出条件」，没达成不进下一步；
5. 跨仓库的那一步（PocketJS，P6）本仓库只负责提供接口与契约文档，不代改应用。

### 12.2 阶段表

| Phase | 目标 | 主要改动面 | 关闭 | 退出条件 | 风险 | 回滚 |
|---|---|---|---|---|---|---|
| **P0** 行为快照 | 建立「今天的 H700 到底怎么跑」的基线 | `tests/baseline/`（新增）：11 台的 `baseosctl` 前身快照、启动日志、`baseos-diag --json`、镜像哈希 | — | 基线可在 CI 重现；哈希入库 | 快照包含环境噪声 | 纯新增，无副作用 |
| **P1** BSP 骨架（影子） | 建立 `bsp/` 目录与 schema，但**不消费** | `bsp/{allwinner/h700,boards/*}`、`bsp/matrix.json`、`bsp/lock.json`、`tools/validate_bsp.py`、G01/G02/G06 门 | L17(部分) | 11 份 board.json 与 `devices.json` 语义等价（G10 哈希不变）；板名扫描在 distro 内为 0（先加白名单） | 白名单过宽 | 删除 `bsp/` 与门，无影响 |
| **P2** Profile 切换 | 构建读 v2 profile；`devices.json` 下线 | `tools/device_profile.py`（适配器+v2）、`tools/profile_migrate.py`、`src/h700-*` → `bsp/…/kernel/modules/`、rcS 的 H700 段落 → `bsp.json` 数据 | L11,L12,L13,L16,L17 | G10 全绿（11 台哈希不变）；`device_profile.py shell` 输出逐字段相同 | 字段语义漂移 | 恢复 v1 适配器（保留一个版本） |
| **P3** DAL 只读 | `node map` + `baseosctl` 只读命令 + 三态 | `bsp/<soc>/nodes.json`、`overlay/usr/sbin/baseosctl`（只读子集）、`baseos-diag` 改为调用、`baseos-charger` 节点访问改走 DAL | L02,L03,L05,L09,L10 | `baseosctl` 在真机与 `baseos-diag` 数据一致；假板 golden 建立 | 归一化改变数值 | `baseosctl` 停用，旧脚本恢复直读（DAL 是新增） |
| **P4** baseosctl 全量 + 写操作 | 命令面完整、写操作幂等、旧脚本变薄壳 | `overlay/usr/sbin/{baseosctl,baseos-*}`、`tests/contract/**` | L21,L14 | 所有旧脚本的人类接口不变（文本输出兼容）；契约测试覆盖三态 | sh 版本性能 | 保留旧脚本（并行一个版本） |
| **P5** Feature 体系 | registry + 解析 + `features.json` + rcS 声明化 | `pjos/features/*.json`、`pjos/boot/stages.json`、`overlay/etc/init.d/rcS`（改为按 stages + feature 执行） | L01,L02,L03,L04,L06,L07(部分) | H700 feature 集合与今天的行为一一对应（差分启动日志）；行为不变 | rcS 重构引入时序差异 | 恢复旧 rcS（保留一个版本，按 `/etc/pjos/legacy-rcS` 开关） |
| **P6** 应用侧切换（外仓） | PocketJS / runtime 只走 `baseosctl` | 应用仓库：`launch_frontend.sh`、compat shim、`keyboardd` 参数化；本仓库提供契约文档 + `baseosctl` 稳定 API | L07,L08,L20,L22 | 应用仓库 grep 无 `/sys`、`/dev`；UI 功能不回归 | 跨仓库协调 | 应用侧 feature flag 回落旧路径 |
| **P7** 假板与 51 号设备门 | 假板族 + 生成器 + T0/T1 全绿 | `bsp/boards/fake-*`、`tests/fixtures/`、`tests/fake-board/**`、`tests/architecture_gate.py` | L18(收尾),L23 | CI 里 T0+T1 <2 min；「51 号设备」脚本通过 | 假板与真机漂移 | 删除假板测试（架构门保留） |
| **P8** 第二块 SoC 预演 | 用一个 **fake SoC**（不是新硬件）走完整链路 | `bsp/fake/generic-arm64/`、`bsp/boards/fake-min|fake-rich` | 剩余 L19/L24 | 新 SoC 只需 `bsp/<vendor>/<soc>/` + boards，distro diff 为 0 | 假 SoC 覆盖不足 | 无副作用（纯新增） |
| **P9** 清理与收尾 | 删除遗留、更新文档、明确契约 | 删 `devices.json`、v1 适配器、`experiments/`（已迁移部分）、更新 `docs/15` 指向 `docs/18` | L24 | 架构门无豁免残留；文档与代码一致 | 误删仍被引用之物 | 逐条 revert |

> 顺序说明：P2 在 P3 之前，因为「profile 数据先统一」才能给 DAL 提供节点来源；
> P5（feature）在 P3/P4 之后，因为 feature 的 `apply` 动作依赖 `baseosctl` 动词。
> P6 必须晚于 P4（否则应用切过去时接口还不全）。

### 12.3 依赖图

```text
P0 ──► P1 ──► P2 ──┬──► P3 ──► P4 ──┬──► P5 ──► P6
                   │                │
                   └──► P7 ─────────┘
                                     └──► P8 ──► P9
```

（P7 依赖 P1 的假板骨架，可与 P3–P5 并行；P8 需要 P5 完成，因为它要验证 feature 在多 SoC 下的行为。）

### 12.4 持续生效的架构门（永不移除）

| 门 | 检查 | 生效起点 |
|---|---|---|
| 板名不得进 distro | §2.5 | P1 |
| Profile 严格 schema | §7.2 | P2 |
| capability 单一事实源 | §4.2 | P3 |
| DAL 之外不得出现节点路径 | §3.9 | P3 |
| feature 只能 distro 定义 | §5.5 | P5 |
| 假板 + 51 号设备 | §10.5 | P7 |
| 发布矩阵 mismatch 阻断 | §11.4 | P4 |

> 这七条是对「架构不会腐烂」的**唯一**保障。任何一条被临时关闭，都必须在 PR 里写明恢复日期。

### 12.5 明确不做的事

| 不做 | 理由 |
|---|---|
| 不引入 YAML/TOML 配置 | 已有 JSON + 工具链，多一种格式只增加维护面 |
| 不做运行时设备发现/热插拔框架 | 掌机形态固定，探测是问题的来源而不是解法 |
| 不重写 `lib_image`/`mkgpt`/更新链 | 它们已经板无关，重写是纯风险 |
| 不做「插件化 BSP」（动态加载 .so） | 50 台设备下，静态目录 + 严格 schema 更可审计 |
| 不为「未来的 x86 掌机」提前设计 | 需要时新增一个 arch + backend，接口已留（`backend` 字段、`arch` 字段） |

---

## 13. 自检与反模式

### 13.1 第 51 台设备测试

新增一台「不同 SoC、不同面板、无电池、有触摸」的设备，逐层回答：

| 层 | 需要改什么 | 为什么这就够了 |
|---|---|---|
| BSP `bsp/<vendor>/<soc>/{bsp.json,nodes.json,harvest.list,kernel/*}` | 新增一个 SoC 目录 | 所有 V1/V2/V3 事实在此声明 |
| Profile `bsp/boards/<new>/board.json` | 新增一个文件 | 所有 V4 产品差异在此声明 |
| Capability | **不改**（自动从 BSP/profile 推导） | §4.2 推导规则 |
| Feature | **不改**（除非新硬件需要新 feature → 改 distro registry，且对所有板生效） | §5.3 |
| DAL | **不改**（数据驱动） | §3.2 |
| `baseosctl` | **不改**（契约稳定） | §6.2 |
| `overlay/` | **不改** | §2.5 架构门强制 |
| Runtime / PocketJS | **不改**（若需要改 → 架构失败，回到 §3.7 补接口） | §3.7 |
| 测试 | **只加** `bsp/boards/<new>/tests/`（可选） | §8.5 |

**判据**：如果任何一格写的是「改 `overlay/`」「改 PocketJS」「改 runtime」，本设计就是失败的，必须回到对应章节修改设计而不是绕过。

### 13.2 已拒绝的方案（及理由）

| 方案 | 为什么拒绝 |
|---|---|
| **每设备一个 overlay 目录 + 构建时选一个** | 会把 distro 复制 N 份，N=50 时任何 distro 修复都要改 50 处；且差异不可审计 |
| **一个巨大的 `devices.json`（把所有字段塞进去）** | 与 BSP 目录分离、无法联合校验、合并冲突集中、无法严格 schema |
| **DAL 用 per-board shell 脚本实现** | 一份代码变成 N 份（§3.8） |
| **让应用（PocketJS）自己探测硬件并降级** | 换设备必须改另一个仓库（L20），且探测失败会静默错误 |
| **用 capability 直接当 feature**（没有 Feature 层） | 「有 WiFi」不等于「BT sink 可用」；应用会被迫自己组合判断，语义散落回应用层 |
| **运行时通过 `/etc/pjos` 可写来自愈配置** | 静态事实运行期可变 → 不可复现、不可信、无法审计；devicetree 语义必须只读 |
| **BSP 里放 shell hook（启动脚本片段）** | BSP 会变成第二份 init（§2.4 明确禁止，只允许声明式 action） |

### 13.3 长期演进（本设计不需要改的地方）

| 未来场景 | 需要新增 | 不需要改 |
|---|---|---|
| Android DAP（`backend: hal`） | 一个 HAL 适配器 + node map | DAL/baseosctl/Application |
| 无电池设备（电视盒） | board.json（`power.battery=false`） | 全部 |
| 双屏 / 外接屏 | `display.backends[]` 扩展 + feature | 全部 |
| x86 掌机 | `arch: x86_64` + `backend: sysfs` 复用 | 全部 |
| 硬件转轮/模拟摇杆 | `input.axes` + `input` 域属性 | 全部（除非需要新动词） |

### 13.4 开放问题（需要产品/团队决策，不阻塞设计）

1. **`experimental` 的对外承诺**：是否允许发布 experimental 镜像？若允许，发布说明如何标注？
2. **H700 的 11 个 target 是否长期全部保留**：其中若干仅 logo/面板不同，是否合并为「同一 board + 变体」？（影响 `board.json` 数量）
3. **`bsp/lock.json` 的评审流程**：BSP 升级是否要求真机验证存证才能合并？
4. **Feature 命名规范**：是否统一 `<domain>_<behavior>` 前缀（如 `audio_hw_volume`），现有命名已基本符合。
5. **跨仓库的门**（应用侧不得读 `/sys`）如何强制执行：应用仓库 CI 加同样的架构门，还是靠评审？

---

## 附录 A — 术语

| 术语 | 含义 |
|---|---|
| **BSP** | 一块可启动硬件单元的全部物理事实（`bsp/`），不含发行版行为 |
| **SoC BSP** | 同一 SoC 共享的事实（内核、闭包、节点基线） |
| **Board Profile** | 一台具体设备的物理/产品事实（Device Profile v2） |
| **Capability** | 硬件「有没有」某项能力，三态 `yes/no/unknown` |
| **Feature** | 发行版「能不能」提供某项行为，三态 `declared/resolved/observed` |
| **DAL** | Device Abstraction Layer：node map（数据）+ 一份实现 + 稳定语义 |
| **node map** | 语义属性 → 节点路径的映射表，唯一允许出现 `/sys`、`/proc`、`/dev` 的地方 |
| **V1–V5** | 五个设备差异轴（§1.1） |
| **假板** | 用 fixture 目录模拟的板，走同一套 schema，用于 CI |
| **G10 字节不变门** | 迁移期强制：H700 产物哈希必须不变 |
| **51 号设备测试** | 证明新增设备只需新增 `bsp/boards/<id>/` 的回归 |

## 附录 B — Schema 版本与兼容承诺

| Schema | 版本 | 兼容策略 |
|---|---|---|
| `pjos.bsp/2` | BSP 事实 | 只增字段；删除需升 `/3` |
| `pjos.device/2` | Device Profile | 严格（`additionalProperties:false`）；升版必须提供 migrate |
| `pjos.caps/2` | 能力集合 | 只增名字；`unknown` 语义不变 |
| `pjos.features/2` / `pjos.featureset/2` | Feature registry / 集合 | registry 只增；集合结构稳定 |
| `baseos.ctl/2` | `baseosctl` API | 字段只增；删除/改名升 `/3` |
| `pjos.matrix/2` | CI/发布矩阵 | 只增 tier |

**总原则**：应用侧只依赖 `baseos.ctl/*` 与 `pjos.featureset/*`；其余 schema 是**构建期内部契约**，
可以更快演进，但必须过 G01 + 契约测试。

## 附录 C — 与 `docs/15` 的差异索引

| docs/15 章节 | 本文对应 | 差异 |
|---|---|---|
| §1 现状 | §1 | 编号化（L01–L24）+ 五轴模型 + 成本曲线 |
| §2 目标分层 | §2、§3 | 补准入判据、DAL 完整设计 |
| §3 目标分层图 | §0、§12.3 | 改为可执行的推导链与依赖图 |
| §4 BSP 包格式 | §8 | 补 overlay 合并规则、harvest 拆分、lock、ABI guard |
| §5 Device Profile v2 | §7 | 从散文表格升级为正式 JSON Schema + 完整例子 + v1 映射 |
| §6 Capability 与 baseosctl | §4、§6 | Capability 补推导/冲突；baseosctl 补全量 API、错误语义、契约测试 |
| §7 迁移 | §12 | 6 phase → 9 phase，每步加退出条件/回滚/依赖 |
| （缺） | §5 | **Feature 体系**（新增） |
| （缺） | §9 | **构建流水线**（新增） |
| （缺） | §10 | **假板**（新增） |
| （缺） | §11 | **多设备 CI**（新增） |
| （缺） | §13 | 自检、反模式、长期演进、开放问题（新增） |
