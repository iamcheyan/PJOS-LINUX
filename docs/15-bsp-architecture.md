# 15 — BSP 与多设备架构（面向发行版长期维护）

> 结论先行：当前仓库**没有 BSP 概念**。设备差异分散在五个互不相干的位置（`devices.json`、`work/<target>/source.json`、`manifest/harvest.list`、`overlay/` 里的 H700 专有分支、`src/` 里按内核 ABI 绑定的 C 代码），
> 结果是"支持第 2 台设备容易，支持第 20 台很难"。本文给出目标分层、BSP 包格式、Device Profile v2、Capability 体系与五阶段迁移路线。
>
> 本文只做架构分析与设计，不改代码。

---

## 1. 当前实现分析

### 1.1 已经设备无关的部分

| 层 | 位置 | 为什么无关 |
|---|---|---|
| rootfs 骨架 | `overlay/`（`etc/`、`init`、`usr/sbin/frontend-session`、`usr/share/baseos/`） | busybox init + `/etc/inittab` + `frontend-session` 的启动范式对 SoC 无感知 |
| 镜像组装流程 | `build-rootfs.sh`、`build-image.sh`、`tools/lib_image.py`、`tools/mkgpt.py` | 分区偏移全部从 `source.json` 读，不用常量；rootfs 用 ext4 + squashfs 打包，与板级无关 |
| 更新与回滚 | `build-update.sh`、`tools/mkupdate.py`、A/B slot 逻辑 | 依赖分区角色（slot A/B、userdata、primary FAT），不依赖具体 SoC |
| 用户空间工具策略 | `tools/strip_gpu_module.py`、`tools/verify_harvest.py`、`manifest/harvest.list` 的**机制** | "从厂商 rootfs 里按白名单收割"这件事是通用的；只有**清单内容**是 H700 的 |
| Launcher 本身 | PocketJS 应用（另一个仓库） | 纯 TSX + 运行时能力，不知道 SoC；只通过 fbdev/evdev/bridge 与系统交互 |

### 1.2 已经与具体设备耦合的部分

| 耦合点 | 现状 | 耦合强度 |
|---|---|---|
| `work/<target>/boot-prefix.img` | 直接从厂商 StockMod 镜像切出的前 212 MB（GPT + bootloader + U-Boot + kernel + boot-resource） | **最强**：换设备必须换厂商固件 |
| `work/<target>/source.json` | 记录 GPT 几何、分区角色偏移、`preserved_regions`、厂商包校验和 | 强：一台设备一份，不可复用 |
| `devices.json` | 11 条平铺 profile：`id`/`model`/`stockmod_prefix`/`baseos_device`/`model_string`/`bootlogo_{width,height}`/`panel_rotation_ccw`/`wifi`/`bluetooth` | 中：字段太少，装不下真实差异，于是差异外溢到别处 |
| `manifest/harvest.list` | **一份全局清单**，注释写明 "H700 base OS stock harvest allowlist"，基线取自 RG40XXV 的 ldd 闭包 | 强：A133 的 soname 集合不同，必须另起一份 |
| `overlay/etc/init.d/rcS` | 内含 `insmod /lib/modules/h700_late_usb.ko`、`/usr/sbin/h700-speaker-amp-load`、`axp2202` 相关分支 | 强：H700 专有逻辑写进了"通用" rcS |
| `src/h700-speaker-amp/` | 通过 `profiles.json` 把 `H700_KERNEL_RELEASE`/`H700_KERNEL_VERSION`/banner 偏移编进二进制，运行时 `strcmp` 校验内核身份 | **最强（内核 ABI 级）**：内核版本一改就失配，换 SoC 直接不可用 |
| `src/h700-late-usb/`、`src/axp-off.c`、`src/boot-clock.c`、`src/fbsplash.c` | 分别绑 H700 的 USB PHY、AXP PMIC、时钟树、fb 几何 | 强到中：`fbsplash` 已尽量读实际 framebuffer 几何，`axp-off` 则完全是 PMIC 型号绑定 |
| `overlay/usr/sbin/baseos-charger`、`baseos-diag` | 硬编码 `/sys/class/power_supply/axp2202-battery/`、`axp*` 前缀识别、`/sys/class/graphics/fb0` | 中：可用节点映射表收敛 |
| PocketJS 侧（另一仓库） | `launch_frontend.sh` 探测 `/dev/dri/card0..1` 再退 `/dev/fb0`；按名字匹配 `ANBERNIC`/`event1` 选 evdev；compat shim 里写死 `/sys/class/disp/disp/attr/enhance_bright`、`amixer`、`axp2202-battery` | 中：这是**最该收敛到 DAL 的一层**，现在却在应用侧猜 |

### 1.3 新增一台设备（以 Smart Pro / A133 Plus 为例）要改哪些文件

必须新增或修改的，按依赖顺序：

1. 厂商 StockMod 镜像 → `prepare-stock.sh` 产出 `work/<target>/{boot-prefix.img,stock-harvest.tar,source.json}`
2. `devices.json` 加一条 profile（现在只能塞 logo 尺寸与旋转，屏幕/输入/电源的真实差异装不下）
3. `manifest/harvest.list` —— **必须新开一份**（A133 的 glibc、soname、daemon 集合与 H700 不同）
4. `overlay/etc/init.d/rcS` —— 加 SoC 分支（或复制整份 overlay，二者都是坏味道）
5. `src/` —— 若该 SoC 需要专有的扬声器功放/USB/PMIC 补丁，要新增一个 `src/<soc>-*` 目录，并按它的内核 ABI 生成 profile
6. PocketJS 侧 —— 改探测顺序、改 evdev 名字匹配、改电源节点路径（在应用仓库里改，违背"设备新增不改应用层"）
7. 测试 —— 现在的 `test-*.sh` 是全局的，没有 per-target 矩阵

> 也就是说：**新增一台设备 ≈ 触碰 6 个不同抽象层级、跨 2 个仓库**。第 2 台还能靠人肉记住，第 20 台必然失控。

### 1.4 十台设备会不会爆？

会，而且会以三种具体形态爆：

- **配置复制**：`devices.json` 平铺 11 条已经出现重复（`rg34xx` 与 `rg34xxsp` 的 `baseos_device` 相同、字段几乎一致）；
- **逻辑复制**：`overlay` 只有一份，A133 需要另一份 rcS → 要么复制整个 `overlay/`（两份漂移），要么在单份里堆 `if [ "$SOC" = ... ]`；
- **条件分支爆炸**：`src/` 已经是"按 SoC 一个目录 + 内核 ABI 字符串比对"的形态，每加一个 SoC 就多一组需要长期跟内核版本对齐的二进制。

### 1.5 现在有没有 BSP？

**没有。**

存在的只是一个"半个 profile"（`devices.json`）和"一台设备的 BSP 事实"（`work/<target>/` + 那份全局 harvest 清单）。
缺的是把"板级事实"与"发行版逻辑"隔开的那一层——也就是 BSP 的定义：**一块板子的全部差异，放在一个可被构建系统发现的目录里，其余代码不得出现该板子的名字。**

---

## 2. 问题清单

按严重度排序（P0 会阻断多设备，P2 是长期债）：

| # | 问题 | 影响 | 级别 |
|---|---|---|---|
| 1 | `overlay/` 是单份且含 H700 专有逻辑（`h700_late_usb.ko`、`h700-speaker-amp-load`、`axp2202`） | 加第二块 SoC 只能复制 overlay 或堆条件分支 | P0 |
| 2 | `manifest/harvest.list` 单一全局、内容为 H700 闭包 | A133/Snapdragon 等设备的用户空间会被误裁或漏收，镜像直接起不来 | P0 |
| 3 | `src/*` 以"内核 release + banner 字符串"做 ABI 校验 | 厂商内核一升级就失配；跨 SoC 完全不可用；这类二进制是长期维护黑洞 | P0 |
| 4 | `devices.json` 字段太少（只有 logo/旋转/无线两开关） | 屏幕、输入、电源、音频、分区角色全部外溢到代码里 | P0 |
| 5 | PocketJS 在应用侧探测硬件（fb 路径、evdev 名、电源节点） | 换设备要改应用仓库，违背分层；且探测失败时静默降级，问题被藏起来 | P1 |
| 6 | 没有 Capability 声明与查询 | 应用无法知道"这台机器有没有蓝牙/触屏/震动"，只能 try-and-fail | P1 |
| 7 | 没有 per-target 测试矩阵 | 现有 `test-*.sh` 只验证"当前这块板"；回归无法防 | P1 |
| 8 | `panel_rotation_ccw` 等字段只有一处使用，其余显示参数无处声明 | 旋转、bpp、密度、物理尺寸散落 | P2 |
| 9 | `work/` 目录混放"厂商输入"与"构建产物" | BSP 缓存无法单独清理/共享，也不便于把 BSP 作为独立 artifact 分发 | P2 |
| 10 | 文档把 H700 事实写成通用事实（如 `docs/` 里多处写死 H700） | 新维护者会把一台设备的结论误当发行版结论 | P2 |

---

## 3. 目标架构

分层原则：**上层不出现板名、不出现设备节点路径；板级差异只在 BSP 目录里。**

```
┌──────────────────────────────────────────────────────────────┐
│ Application Layer                                            │
│   PocketJS launcher · games · 3rd-party frontends            │
│   —— 只通过 "capabilities + DAL 命令" 与系统交互，不认识板子    │
├──────────────────────────────────────────────────────────────┤
│ Runtime Layer                                                │
│   pocket-linux-kms（fbdev/DRM 输出）· guest runtime · PTY     │
│   —— 从 profile 得到 显示/输入 句柄，自己不做探测               │
├──────────────────────────────────────────────────────────────┤
│ BaseOS Services                                              │
│   init/rcS · frontend-session · update/rollback · expand     │
│   baseosctl（统一系统接口） · baseosd（可选常驻）              │
├──────────────────────────────────────────────────────────────┤
│ Device Abstraction Layer (DAL)                               │
│   display  input  audio  power  network  storage  led        │
│   —— 把 "这颗 SoC 的节点" 翻译成 "稳定语义接口"                │
├──────────────────────────────────────────────────────────────┤
│ BSP (Board Support Package)  ← 唯一允许出现板名/SoC 名的地方   │
│   kernel + boot-prefix + dtb + modules + hw init + node map  │
│   + harvest 清单 + 该板的 overlay 片段 + 板级测试              │
├──────────────────────────────────────────────────────────────┤
│ Hardware                                                     │
└──────────────────────────────────────────────────────────────┘
```

三条硬约束（架构验收条件）：

1. 新增设备 **不改** Application Layer；
2. 新增设备 **不改** Runtime Layer 源码；
3. 新增设备只允许新增/修改 `bsp/<soc>/<board>/` 目录，以及 `devices.json` 里一条指向它的 profile。

---

## 4. BSP 设计

### 4.1 目录形态

```
bsp/
  allwinner/
    h700/
      bsp.json                 # 该 SoC 的共性：dtb 名、kernel id、模块、节点映射基线
      harvest.list             # SoC 级用户空间白名单（可被板级 extend）
      src/                     # SoC 专有 C（扬声器功放、USB、PMIC 等）
      overlay/                 # SoC 级 overlay 片段（合并进 rootfs）
      tests/
    a133/
      bsp.json
      harvest.list
      src/
      overlay/
      tests/
  boards/
    rg34xx/    -> board.json {soc: allwinner/h700, panel, input, power, logo, rotation}
    rg34xxsp/  -> board.json {soc: allwinner/h700, ...}
    tg5040/    -> board.json {soc: allwinner/a133, ...}   # TRIMUI Smart Pro
```

### 4.2 `bsp.json`（SoC 级）

```json
{
  "schema": "pjos.bsp/1",
  "soc": "allwinner/h700",
  "arch": "aarch64",
  "kernel": {
    "release": "4.9.170",
    "abi_guard": ["banner", "release", "version"],
    "modules": ["h700_late_usb.ko"]
  },
  "dtb": { "source": "stock", "name": "sun50i-h700-*.dtb" },
  "harvest": { "list": "harvest.list", "base": "stockmod" },
  "nodes": {
    "display": ["/dev/fb0"],
    "drm": ["/dev/dri/card0"],
    "input_glob": "/dev/input/event*",
    "battery": ["/sys/class/power_supply/axp2202-battery"],
    "backlight": ["/sys/class/disp/disp/attr/enhance_bright"],
    "audio_card": "audiocodec",
    "usb_gadget": "/sys/class/udc"
  },
  "hw_init": ["h700-speaker-amp-load"],
  "capabilities": ["wifi", "bluetooth", "fbdev", "usb-storage"]
}
```

### 4.3 `board.json`（板级）

```json
{
  "schema": "pjos.board/1",
  "id": "rg34xx",
  "soc": "allwinner/h700",
  "model_string": "RG34xx",
  "stockmod_prefix": "RG34XX-",
  "panel": { "width": 720, "height": 480, "rotation_ccw": 0, "bpp": 32, "density": 2 },
  "input": { "keyboard_name": "ANBERNIC-keys", "event_hint": "event1", "buttons": "abxy-start-select-l-r" },
  "capabilities": { "wifi": true, "bluetooth": true, "touch": false, "vibration": false, "hdmi": false },
  "overrides": { "nodes": { } },
  "logo": { "source": "generated", "width": 720, "height": 480 }
}
```

### 4.4 构建时如何被发现

`build-*.sh` 的入口只接受 `--board <id>`：

1. 读 `bsp/boards/<id>/board.json` → 得到 `soc`；
2. 读 `bsp/<soc>/bsp.json` → 得到内核/模块/节点/清单/片段；
3. 合成 overlay = `overlay/`（通用） + `bsp/<soc>/overlay/` + 板级 `overlay/`（后覆盖前）；
4. `prepare-stock` 用 `board.json` 的 `stockmod_prefix` 找厂商镜像，产出 `work/<board>/`；
5. `source.json` 仍是运行期事实（GPT 几何），但**只由 board 派生，不允许手改**。

这样"加一台设备" = 加一个 `bsp/boards/<id>/board.json`（同 SoC 时）或再加一个 `bsp/<soc>/`（新 SoC 时），其余代码零改动。

### 4.5 BSP 与内核的关系（必须写清的一条红线）

`src/` 里按内核 banner/release 做 `strcmp` 的那类补丁（扬声器功放）**属于 BSP，不属于发行版**。
规则：

- BSP 的内核补丁必须**声明它支持的内核身份**（release + version + banner），并在构建期比对 `bsp.json`；
- 匹配失败时**跳过并记录**，不允许"猜一个偏移继续写内存"；
- 每个 SoC 的内核升级= 一次 BSP 升级，与发行版发版解耦。

---

## 5. Device Profile 设计

### 5.1 字段

| 组 | 字段 | 说明 |
|---|---|---|
| identity | `id`, `model`, `model_string`, `stockmod_prefix`, `filename_alias` | 厂商固件匹配、UI 显示 |
| soc | `soc`（`vendor/soc`） | 指向 BSP |
| panel | `width`, `height`, `rotation_ccw`, `bpp`, `density`, `logical_w`, `logical_h` | 物理像素与逻辑视口分开；`density` 决定 2× 缩放 |
| display | `backend`（`fbdev`/`drm`）, `node`, `vsync`（`timer`/`pageflip`） | 不再让应用层探测 |
| input | `keyboard_name`, `event_hint`, `axes`, `button_map`, `hotkeys` | 名字匹配规则集中一处 |
| audio | `card`, `mixer_control`, `headphone_switch`, `amp_init` | 音量/耳机检测的稳定语义 |
| power | `battery_glob`, `charger_glob`, `led_glob`, `suspend_mode`, `charge_only_boot` | 电源/休眠差异 |
| network | `wifi_driver`, `wifi_tool`, `bt_tool`, `mdns` | |
| storage | `card_layout`（slot A/B、userdata、primary FAT 的分区号）, `expand_target` | 取代散落的分区号 |
| capabilities | `wifi`, `bluetooth`, `touch`, `vibration`, `hdmi`, `gpu`, `rtc` | 供应用查询 |
| bsp | `soc`, `kernel_guard`, `modules`, `hw_init` | 从 BSP 继承，板级可覆盖 |

### 5.2 规则

- **profile 只描述事实，不描述行为**（"亮度节点在哪"可以写，"亮度怎么调"属于 DAL）；
- **未知字段必须报错**，防止字段名漂移；
- **缺字段时不得静默降级**：该能力标记为 `unknown`，应用必须显式处理；
- 现有 `devices.json` 作为 **v1**，新 schema 为 **v2**，用一个 `tools/profile_migrate.py` 把 v1 的 11 条无损升级（`rg34xx`/`rg34xxsp` 共享 SoC，差异只剩 panel 与 model）。

---

## 6. Capability 系统设计

### 6.1 为什么需要

现在的做法是"探测然后猜"：探测 `/dev/dri` 失败退回 `/dev/fb0`；按名字找 `ANBERNIC` 选 evdev；shim 里写死 `axp2202`。
这在单设备上能跑，在多设备上会产生**静默错误**——例如某台设备没有背光节点，UI 显示 `unknown`，用户以为坏了。
Capability 的作用是把"这台机器有什么"变成**可查询的契约**，让"没有"是一种明确答案，而不是失败。

### 6.2 声明方式

单一事实来源：`board.json` 的 `capabilities` + BSP 的 `capabilities`（板级覆盖 SoC）。
构建时生成 `/etc/pjos/capabilities.json`：

```json
{ "schema": "pjos.caps/1", "board": "rg34xx", "soc": "allwinner/h700",
  "caps": { "wifi": "yes", "bluetooth": "yes", "touch": "no", "vibration": "no",
            "hdmi": "no", "fbdev": "yes", "drm": "no", "brightness": "yes",
            "audio": "yes", "usb-storage": "yes", "rtc": "yes" } }
```

三态：`yes` / `no` / `unknown`（未知≠没有）。

### 6.3 应用如何查询

```sh
baseosctl cap list             # 全部
baseosctl cap get wifi          # yes|no|unknown
baseosctl cap has wifi && ...   # 0/1，便于脚本
```

PocketJS 侧：启动时读一次 `capabilities.json`（或调 `baseosctl cap list`），据此决定
显示哪些卡片、状态栏显示哪些图标、设置页隐藏哪些项——**不再靠探测**。

### 6.4 `baseosctl` 该不该有？

**该有，而且应该成为唯一系统接口。** 理由：

1. 它把 DAL 的语义暴露成稳定的命令行契约，应用层不必知道 `/sys` 路径；
2. 它同时解决"compat shim"问题——现在 PocketJS 侧那 6 个 shim 是在模拟 ROCKNIX 的接口，属于**过渡产物**；长期应由 `baseosctl` 提供原生语义，shim 只做薄翻译或删除；
3. 可测试：每条子命令都能在 host 上用假 `/sys` 树做单测，不需要真机。

建议子命令集合（v1）：

```
baseosctl cap  list|get|has
baseosctl display info|set-brightness
baseosctl audio  info|set-volume|set-mute
baseosctl power  battery|charger|suspend|poweroff
baseosctl net    wifi-status|wifi-enable|bt-status|bt-enable
baseosctl input  list|map
baseosctl storage info|expand|usb-mode
baseosctl version
```

约定：**所有输出为 `key=value` 或 JSON（`--json`），不输出人类散文**，便于脚本与应用解析。

---

## 7. 迁移路线图

原则：每一步都可独立发布、都不破坏 RG34XX。

### Phase 1 — 冻结与盘点（不改行为）

- 把当前 `work/<target>/` 的"厂商输入"与"构建产物"分开（`work/input/` 与 `work/build/`）；
- 把 `devices.json` 的 11 条完整导出为 v2 profile 草稿（字段按 §5.1），先不启用；
- 补一份 `docs/16-device-matrix.md`：每台设备记录 SoC、内核、面板、输入、电源节点、验证状态；
- 验收：`build-all.sh` 行为与摘要哈希不变。

### Phase 2 — 引入 BSP 目录（structure only）

- 新建 `bsp/allwinner/h700/`，把 `manifest/harvest.list`、`src/h700-*`、rcS 中的 H700 段落**原样搬入**；
- 构建脚本改为"合成 overlay"（通用 + SoC 片段），但合成结果与今天的 `overlay/` **逐字节一致**；
- 验收：镜像哈希与 Phase 1 相同；`grep -r h700 overlay/` 结果为空（板名只出现在 `bsp/`）。

### Phase 3 — DAL 与 `baseosctl`

- 新增 `overlay/usr/sbin/baseosctl`（busybox sh 或静态 C），先只做**只读**：`cap list`、`display info`、`audio info`、`power battery`、`net wifi-status`、`storage info`；
- 把 `baseos-diag`/`baseos-charger` 里散落的节点路径改为查 profile（`/etc/pjos/board.json`）；
- PocketJS 的 compat shim 改为**优先调 `baseosctl`，失败再回落旧路径**；
- 验收：真机上 `baseosctl` 每条命令输出与设置页显示一致（同一份数据）。

### Phase 4 — 应用去设备化

- PocketJS `launch_frontend.sh`：删掉 DRM→fbdev 的猜测与 `ANBERNIC` 名字匹配，改为读 `baseosctl cap`/`display info`；
- 设置页按 capability 隐藏不可用项（没有背光就不显示亮度行）；
- 验收：把 profile 里 `display.backend` 从 `fbdev` 改成 `drm`（假想设备），应用代码零改动仍能启动。

### Phase 5 — 第二块 SoC（A133 / Smart Pro）验证架构

- 新增 `bsp/allwinner/a133/` + `bsp/boards/tg5040/`；
- 只允许新增这两个目录 + 一条 profile；若必须改 `overlay/` 或 PocketJS，说明 Phase 2/3 的设计有漏，**先修架构再加设备**；
- 验收：`build-image.sh --board tg5040` 成功产出镜像；首启进 launcher；抓帧存证。

### Phase 6 — 多设备 CI 与文档

- `tests/` 按 board 参数化；准备一份"假板"（fake board，用 tmpfs 与假 `/sys`）让 CI 在 x86 上跑通 DAL 与 profile 校验；
- 每个 release 产出 per-board 状态表（built / qemu-booted / device-verified 三态严格区分）。

---

## 8. 优先级排序

| 顺序 | 事项 | 为什么现在做 | 成本 |
|---|---|---|---|
| 1 | Phase 1 盘点 + device matrix | 不先盘点就会在 Phase 2 搬错东西；成本极低 | 低 |
| 2 | Phase 2 BSP 目录（输出哈希不变） | 把「板名从通用代码里清出去」这一步做成纯搬运，风险最低、收益最大 | 中 |
| 3 | `capabilities.json` + `baseosctl cap list`（只读） | 应用侧立刻可以"问而不是猜"，也是后续所有 DAL 的地基 | 低-中 |
| 4 | harvest 清单按 SoC 拆分 | 这是加第二台设备时最先炸的地方（用户空间被裁错直接起不来） | 中 |
| 5 | `src/` 内核补丁的 ABI 守卫规范化 | 防止"猜偏移写内存"这类不可调试故障；也是跨内核升级的护栏 | 中 |
| 6 | `baseosctl` 写操作（亮度/音量/电源） | 替换 shim，收敛到唯一接口 | 中 |
| 7 | PocketJS 去设备化 | 依赖 2+3 就绪；它本身改动小，但没地基会被迫继续探测 | 低 |
| 8 | Phase 5 第二块 SoC | 用真实设备检验架构，而不是继续堆抽象 | 高 |
| 9 | 多设备 CI（含 fake board） | 长期防回归；可最后做，但要在 Phase 5 之前有最小骨架 | 中 |

**不建议现在做的**：为每台设备做独立的镜像构建流水线（会让"20 台设备"变成 20 条流水线）；把 BSP 做成可远程下载的二进制包（在 schema 稳定之前分发只会固化错误设计）。

---

## 附：一句话验收标准

> 加第二台设备时，如果 PR 里出现了 `overlay/` 或 PocketJS 仓库的改动，说明架构没做对。
