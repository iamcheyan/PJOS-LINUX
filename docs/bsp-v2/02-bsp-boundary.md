# 02 — BSP 边界定义

> 本文件定义：BSP 是什么、不是什么、放在哪、由谁发现、新增一台设备要做什么。
> 它解决 `01-audit.md` 的 P0-1（overlay 单份）、P0-2（harvest 单份）、
> P0-3（内核补丁散落）、P0-4（profile 表达力不足）、P0-5（分区号字面量）
> 与 §1（5 份板级事实副本）。

---

## 1. 一句话定义

> **BSP = 一块板子的全部差异，放在一个能被构建系统发现的目录里；
> 该目录之外，任何文件都不得提及这块板。**

反过来说，一条判据：

> 如果一个改动**只**影响某一块板的行为，它属于 BSP；
> 如果它影响所有板的行为，它属于发行版；
> 如果它"影响某几块板"，说明**缺少一个中间层**（SoC 层），见 §3。

---

## 2. 边界：什么属于 BSP，什么不属于

| 类别 | 归属 | 判据 | 当前在哪 |
|---|---|---|---|
| 厂商引导链（boot0/U-Boot/env/boot 镜像） | **BSP** | 逐板逐固件版本，带 SHA | `work/<target>/boot-prefix.img` |
| GPT 几何与分区角色 | **BSP** | 逐板，来自厂商表 | `work/<target>/source.json`、`tools/mkgpt.py`、`tools/gptslot.c` |
| 内核与 DTB | **BSP** | 逐板，随厂商固件 | `manifest/kernel-gzip.json`、`work/<target>/boot-gzip/` |
| 内核模块（厂商 blob + 自建补丁） | **BSP** | 逐板，内核 ABI 绑定 | `src/h700-*`、`src/h700-speaker-amp/profiles.json` |
| 用户空间 harvest 清单 | **BSP** | 逐 SoC，内容是厂商 rootfs 的闭包 | `manifest/harvest.list` |
| 硬件初始化序列（insmod 顺序、PMIC 初值、GPIO） | **BSP** | 逐 SoC | `overlay/etc/init.d/rcS:11-12,109-115,189-251` |
| 设备节点映射（节点 → 语义） | **BSP** | 逐 SoC，板级可覆盖 | 目前**不存在**，散在 10+ 脚本 |
| Capability / Feature 声明 | **BSP** | 逐板事实 | 目前只有 `devices.json` 的两个布尔 |
| 面板参数（尺寸、旋转、bpp、时序） | **BSP** | 逐板 | `devices.json` + `panel-contract.json` |
| 板级测试 | **BSP** | 逐板 | 目前**不存在** |
| init / inittab / 服务脚本 | **发行版** | 对所有板相同 | `overlay/init`、`overlay/etc/inittab` |
| 更新/回滚引擎 | **发行版** | 依赖分区**角色**而非编号 | `overlay/usr/sbin/baseos-update`、`gptslot` |
| 日志、诊断框架 | **发行版** | 机制通用，节点来自 DAL | `overlay/usr/sbin/baseos-diag` |
| `baseosctl` | **发行版** | 语义稳定 | 目前**不存在** |
| DAL | **发行版** | 把 BSP 的节点翻译成语义 | 目前**不存在** |
| PocketJS / Runtime | **发行版**（另一仓库） | 不认识板 | — |

### 2.1 规则的适用范围（重要，避免自相矛盾）

"板名只允许出现在 `bsp/` 下"这条规则的**执行对象是会被构建系统或运行时消费的文件**：

```
强制（lint 覆盖）：
  overlay/          被 build-rootfs.sh 拷进镜像
  runtime/          被编进镜像
  tools/            构建期执行
  src/              被编译
  manifest/         被构建读取
  build-*.sh  prepare-stock.sh  fetch-prepared.sh  cache-pack.sh  verify-target.sh
  devices.json      （迁移完成后删除，见 07）

不强制（允许提及，因为是"关于系统的事实描述"）：
  docs/             文档，包括本目录。审计必须能指名证据，否则无法核验。
  experiments/      实验记录，按定义是一次性的
  tests/            测试可以指名它测的是哪块板（见 §7.4）
  work/             构建产物，不入库
```

lint 的判定见 §7。**`docs/bsp-v2/01-audit.md` 里出现板名是合规的**，
因为它属于 `docs/`；它引用的每一处代码位置才是 lint 的对象。

---

## 3. 目录结构

```
bsp/
├── README.md                     # 本层的索引与约定（人读）
├── schema/
│   ├── board.schema.json         # board.json 的 JSON Schema
│   ├── soc.schema.json           # soc.json 的 JSON Schema
│   └── nodes.schema.json         # 节点映射表的 JSON Schema
├── allwinner/                    # vendor
│   ├── h700/                     # SoC
│   │   ├── soc.json              # SoC 共性：内核身份、模块、节点基线、harvest
│   │   ├── harvest.list          # SoC 级用户空间白名单
│   │   ├── kernel/
│   │   │   ├── profiles.json     # 11 个已审计内核 Image（从 src/h700-speaker-amp 迁入）
│   │   │   └── modules/          # 自建内核补丁源码（从 src/h700-* 迁入）
│   │   ├── overlay/              # SoC 级 overlay 片段（合并进通用 overlay）
│   │   │   ├── etc/init.d/soc-hw-init      # 原 rcS 的 SoC 段落
│   │   │   └── usr/sbin/...
│   │   └── tests/                # SoC 级测试（fake sysfs）
│   └── a133/
│       ├── soc.json
│       ├── harvest.list
│       ├── kernel/
│       ├── overlay/
│       └── tests/
└── boards/                       # 板级
    ├── rg34xx/
    │   ├── board.json            # 唯一的板级事实来源
    │   ├── overlay/              # 可选：板级 overlay 片段
    │   └── tests/                # 可选：板级测试
    ├── rg34xxsp/
    │   └── board.json
    └── ...
```

设计取舍：

- **两级而不是一级**（`soc/` + `boards/`），因为 11 台 H700 设备共享内核、模块、
  harvest 基线。一级目录会把 11 份相同内容复制 11 次——那正是 `01-audit.md §3.2`
  说的"250 处手工登记"。
- **`boards/` 在 `bsp/` 顶层而不是 `bsp/<vendor>/<soc>/boards/`**：板级事实里
  `soc` 是一个字段，不是路径。这样"把一块板换 SoC"是一次字段改动，而不是一次目录搬迁。
  代价是 `bsp/boards/` 会变长（50 台 = 50 个目录），这是可接受的——目录列表不需要维护。
- **`schema/` 放在 `bsp/` 下**而不是 `tools/`：schema 是 BSP 的契约，谁定义谁拥有。

---

## 4. `soc.json`（SoC 级）

装"这块 SoC 上所有板都一样"的事实。

```json
{
  "schema": "pjos.soc/1",
  "soc": "allwinner/h700",
  "arch": "aarch64",
  "kernel": {
    "identity": { "release": "4.9.170", "abi_guard": ["release", "version", "banner"] },
    "profiles": "kernel/profiles.json",
    "modules": [
      { "name": "mali_kbase",  "source": "vendor", "flat": "/usr/lib/modules/mali_kbase.ko" },
      { "name": "8821cs",      "source": "vendor", "flat": "/usr/lib/modules/8821cs.ko" },
      { "name": "rtl_btlpm",   "source": "vendor", "flat": "/usr/lib/modules/rtl_btlpm.ko" },
      { "name": "h700_speaker_amp", "source": "bsp", "build": "kernel/modules/speaker-amp" },
      { "name": "h700_late_usb",    "source": "bsp", "build": "kernel/modules/late-usb" }
    ]
  },
  "dtb": { "source": "stock", "from": "boot-prefix.img" },
  "harvest": { "list": "harvest.list", "base": "stock" },
  "nodes": {
    "display":   { "fb": ["/dev/fb0"], "disp": ["/dev/disp"], "debugfs_switch": "/sys/kernel/debug/dispdbg" },
    "input":     { "glob": "/dev/input/event*" },
    "power":     { "supply_glob": "/sys/class/power_supply/*", "rtc": "/sys/class/rtc/rtc0" },
    "audio":     { "card_prefix": "audiocodec" },
    "network":   { "wifi_iface": "wlan0", "wifi_ctrl": "/sys/class/misc/sunxi-wlan/rf-ctrl", "bt_uart": "ttyS1" },
    "storage":   { "boot_disk": "/dev/mmcblk0", "roles": { "boot": 4, "rootfs": 5, "data": 6, "primary": 7 } },
    "led":       { "glob": [] }
  },
  "hw_init": [
    { "step": "load-gpu",     "module": "mali_kbase",  "when": "boot", "background": true },
    { "step": "load-late-usb", "module": "h700_late_usb", "when": "boot", "background": true },
    { "step": "load-bt-lpm",  "module": "rtl_btlpm",   "when": "boot", "background": true },
    { "step": "load-wifi",    "module": "8821cs",      "when": "boot", "background": true,
      "pre": "discard-stale-sdio", "retry": { "unload": true, "hold_ms": 5000 } },
    { "step": "speaker-amp",  "module": "h700_speaker_amp", "when": "before-frontend",
      "params": { "apply": 1, "headphone_pop_fix": "from-board" } }
  ],
  "capabilities": { "wifi": "yes", "bluetooth": "yes", "touch": "unknown", "vibration": "unknown", "hdmi": "yes" }
}
```

`hw_init` 是**数据**而不是脚本：现在 `rcS:107-115`、`:185-251`、`:377-382`
里的顺序、后台化、重试策略全部硬编码在 shell 里。声明化以后，
`overlay/etc/init.d/rcS` 只剩"读 `soc.json`，按 `hw_init` 逐条执行"。

### 4.1 板级可以覆盖 SoC 级的任何 `nodes` 条目

覆盖规则（**深合并，板级胜**）：

```json
// bsp/boards/rg28xx/board.json 片段
{ "nodes": { "network": { "wifi_iface": null } } }
```

`null` 表示"这块板没有这一项"，与"没写"（继承）严格区分。
这解决了 `01-audit.md` P1-2 的问题：`wifi=false` 目前只影响 harvest 裁剪，
不影响运行时的任何判断。

---

## 5. `board.json`（板级）— Device Profile v2

这是**唯一**的板级事实来源。`devices.json` 的 v1 schema 在迁移完成后删除。

### 5.1 完整字段

```json
{
  "schema": "pjos.board/1",
  "id": "rg34xx",
  "soc": "allwinner/h700",
  "identity": {
    "model": "RG34XX",
    "model_string": "RG34xx",
    "frontend_family": "rg34xx",
    "firmware_prefix": "RG34XX-",
    "firmware_alias": null
  },
  "panel": {
    "width": 720, "height": 480,
    "rotation_ccw": 0,
    "bpp": 32,
    "density": 2,
    "logical_width": 720, "logical_height": 480
  },
  "display": { "backend": "fbdev", "node": "/dev/fb0", "vsync": "timer" },
  "input": {
    "keyboard_name": "ANBERNIC-keys",
    "event_hint": "event1",
    "buttons": ["a","b","x","y","start","select","l1","l2","r1","r2"],
    "power_key_match": { "name_prefix": "axp", "name_suffix": "-pek" },
    "menu_gpio_label": "GPIO Key Menu"
  },
  "audio": {
    "card": 0,
    "controls": {
      "master": ["digital volume", 63],
      "lineout": ["lineout volume", 31],
      "routing": ["OutputL Mixer DACL","OutputR Mixer DACR","LINEOUT","SPK"]
    },
    "amp_module": "h700_speaker_amp",
    "headphone_pop_fix_default": false
  },
  "power": {
    "battery": "axp2202-battery",
    "charger": "axp2202-usb",
    "led": "axp2202-battery/work_led",
    "suspend": "mem",
    "os_sleep_value": 16,
    "charge_only_boot": true
  },
  "network": { "wifi": true, "bluetooth": true, "bt_uart": "ttyS1" },
  "storage": {
    "layout": "baseos-ab-v1",
    "expand_target": "primary",
    "tf2_disk": "/dev/mmcblk1"
  },
  "capabilities": {
    "wifi": "yes", "bluetooth": "yes", "touch": "no",
    "vibration": "no", "hdmi": "yes"
  },
  "features": {
    "bt_source": "yes", "bt_sink": "yes",
    "audio_hw_volume": "yes", "display_rotation": "yes",
    "suspend": "yes", "rtc_alarm": "yes",
    "usb_gadget": "yes", "usb_host": "yes"
  },
  "logo": { "source": "generated", "width": 720, "height": 480 },
  "overrides": { "nodes": {}, "hw_init": [] }
}
```

### 5.2 每个设备 profile 的**最小内容**

必须存在的（缺一项构建即失败）：

| 字段 | 为什么最小 | 缺失时的行为 |
|---|---|---|
| `schema` | 版本判定 | 拒绝 |
| `id` | 目录名一致性 + 日志/更新校验 | 拒绝 |
| `soc` | 指向 `bsp/<vendor>/<soc>/` | 拒绝 |
| `identity.firmware_prefix` | 从固件目录里认出这台设备 | 拒绝（`device_profile.find_image` 已如此） |
| `identity.model_string` | `/mnt/vendor/bin/dmenu.bin` 与前端识别 | 拒绝 |
| `panel.width/height/rotation_ccw` | bootlogo、fbsplash、DAL display | 拒绝 |
| `display.backend` + `display.node` | DAL display | 拒绝 |
| `input.event_hint` 或 `input.keyboard_name` | DAL input | 拒绝（二者至少一个） |
| `capabilities.*`（枚举内全部键） | `baseosctl cap` | 拒绝（必须显式给出，包括 `unknown`） |
| `features.*`（枚举内全部键） | `baseosctl feature` | 拒绝 |

可选（缺失 = 从 SoC 继承；SoC 也没有 = 该能力 `unknown`）：

`panel.density`、`panel.logical_*`、`display.vsync`、`input.buttons`、
`input.power_key_match`、`input.menu_gpio_label`、`audio.*`、`power.*`、
`network.*`、`storage.*`、`logo.*`、`overrides.*`。

**规则：未知字段必须报错。** 这一条是 `01-audit.md §3.1` 的直接解药：
`docs/14:21` 要求了 4 个不存在的字段。加一条"未知字段报错"，文档与实现就无法再漂移。

### 5.3 显式给出而不是"默认 false"

`capabilities` 与 `features` 的每一个键都必须显式出现，取值 `yes`/`no`/`unknown`。
理由见 `04-capability.md §2`：`unknown`（未知）和 `no`（没有）是**不同答案**，
不能靠"没写就是没有"混淆。代价是每条 profile 多 10 行；收益是新增设备时
维护者必须逐个回答"这台机器有没有 X"，而不是让默认值替他回答。

---

## 6. 与 kernel / uboot / rootfs 的关系

这是最容易设计错的部分。三条红线：

### 6.1 引导链：BSP **引用**厂商产物，不重新生成

`boot-prefix.img`（GPT + boot0 + U-Boot + env + boot）逐字节来自厂商固件，
只做两处受控修改：

1. `tools/mkgpt.py` 把 8 条目表改成 BaseOS 布局（`tools/mkgpt.py:36` `NUM_ENTRIES = 8`）；
2. `tools/kernel_gzip.py` 替换 p4 的内核/ramdisk/cmdline，并改 U-Boot 选择器字节。

**BSP 的责任是声明"改哪些、期望的 SHA 是多少"**，不是"怎么改"。
所以 `soc.json` 里 `dtb.from = "boot-prefix.img"`，而 `manifest/kernel-gzip.json`
（迁移后：`bsp/allwinner/h700/boot/*.json`）记录每台设备的
`boot0_sha256`/`uboot_sha256`/`package_offset`。

**红线**：BSP 不得包含自己的 boot0/U-Boot。理由：这些是厂商签名/校验过的，
自己生成等于重写引导链，与本架构目标无关且风险极高。

### 6.2 内核：BSP 拥有内核补丁，发行版不拥有

`src/h700-speaker-amp`、`src/h700-late-usb` 迁入 `bsp/allwinner/h700/kernel/modules/`。
`src/` 只保留**与 SoC 无关**的静态工具：`fbsplash.c`、`boot-clock.c`、
`charger-wait.c`、`native-health.c`、`baseos-regs.c`、`axp-off.c`（→ 见下）。

其中两个需要特别处理：

| 文件 | 现状 | 归属 | 理由 |
|---|---|---|---|
| `src/axp-off.c` | 只认 `axp2202`（`src/axp-off.c:26`）+ `axp20x-i2c` 驱动路径（`:18`） | **BSP**（`bsp/allwinner/h700/tools/`） | 它写的是 PMIC 寄存器 0x27，与具体 PMIC 型号绑定 |
| `src/baseos-regs.c` | 34 个 SoC 寄存器地址（`src/baseos-regs.c:27-60`） | **BSP** | 地址是 SoC 事实 |
| `src/charger-wait.c` | `DISP_LCD_SET_BRIGHTNESS` ioctl + 按名字找 `axp*-pek`（`:15-16`, `:49-50`） | **BSP**（ioctl 常量与输入名匹配） | 显示 ABI + 输入命名 |
| `src/fbsplash.c` | 只读 `/etc/baseos-release` 的旋转键（`:882`），其余读实际 fb 几何 | **发行版** | 已经设备无关 |
| `src/boot-clock.c` | `cntvct_el0` + fallback | **发行版** | 通用 arm64 |
| `src/native-health.c` | 读 `axp2202-battery/boot_mode`（`:26`）、`/dev/mali0`（`:251`） | **混合** → 拆 | 节点从 `soc.json` 取；逻辑留发行版 |

`native-health.c` 是唯一需要**改代码**才能拆干净的：它现在 `#define` 了节点路径。
迁移步骤见 `07-migration.md` 的 M5。

### 6.3 rootfs：BSP 只贡献"片段"，不贡献整份 overlay

合成规则（`build-rootfs.sh:114` 现在是 `cp -R /overlay/. "$R/"`）：

```
rootfs = busybox + 厂商 harvest
       + overlay/                                    (发行版通用，先铺)
       + bsp/<vendor>/<soc>/overlay/                 (SoC 片段，覆盖)
       + bsp/boards/<id>/overlay/                    (板级片段，最后覆盖)
       + /etc/pjos/{board,soc,caps,features}.json     (构建时由 profile 生成)
       + /etc/baseos-release                          (版本 + target，保持现状)
```

**迁移的验收判据**：合成后的树与今天 `cp -R /overlay/.` 的结果**逐文件一致**
（用 §7.2 的 manifest 比较，不用 tar 字节比较——理由见 §7.3）。

---

## 7. 构建系统如何发现 BSP

### 7.1 入口只有 `--board <id>`

现有 CLI 已经是 `build-*.sh <target>`（`build-rootfs.sh:15-16`），保持不变；
`<target>` 语义从"`devices.json` 的一条"变成"`bsp/boards/<id>/board.json`"。

解析顺序（`tools/device_profile.py` 改造，CLI 与输出变量名不变）：

```
1. bsp/boards/<id>/board.json          → id, soc, 全部板级事实
2. bsp/<vendor>/<soc>/soc.json         → SoC 事实
3. 深合并（board 胜）                   → 有效配置
4. 输出 PROFILE_* 变量（保持现有名字）  → 所有 build-*.sh 无需改动
```

**关键约束：`PROFILE_*` 变量的名字和数量不得减少。**
`build-rootfs.sh:17`、`build-image.sh:32`、`verify-target.sh:29`、
`tools/make-bootlogo.sh:17`、`validate-on-device.sh:12`、`test-boot-qemu.sh:21`、
`flash-card.sh:8`、`build-all.sh:30`、`build-stockmod.sh:23,26,30`、
`cache-pack.sh`、`fetch-prepared.sh:40`、`prepare-stock.sh:13`
全部通过 `eval "$(python3 tools/device_profile.py shell "$TARGET")"` 取变量。
只要这层接口不变，迁移就可以逐脚本进行，不必一次改完。

### 7.2 lint：板名只能出现在 `bsp/` 下

```sh
# tools/bsp-lint.sh（新增，M2 落地）
# 退出码：0 合规，1 违规
for tree in overlay runtime tools src manifest build-*.sh prepare-stock.sh \
            fetch-prepared.sh cache-pack.sh verify-target.sh; do
    grep -rniE '<board-or-soc-token-regex>' "$tree" && fail
done
```

token 清单从 `bsp/` 自身派生，而不是硬编码在 lint 里：

```sh
# 板名 = bsp/boards/* 的目录名；SoC 名 = bsp/<vendor>/<soc>/ 的目录名
# 外加每个 board.json 的 identity.firmware_prefix / model / model_string
```

这样第 51 台设备加进 `bsp/` 时，lint **自动**开始检查它的板名，无需改 lint。

`tests/`、`docs/`、`experiments/` 不在 lint 范围内（§2.1）。

### 7.3 为什么"逐文件 manifest"而不是"镜像 SHA 不变"

`01-audit.md` 之外的实测发现（本次审计新增，非引用）：

```sh
# ext4：同一输入两次 mke2fs，内容相同但镜像不同
$ mke2fs -F -t ext4 -b 4096 -L rootfs -d src a.img 8M   # 两次
# → 差 1 字节 @0x22b08（inode 区）；即使固定 -U 和 -E hash_seed 仍差
# 加 -E root_owner=0:0 后差异缩小到 1 字节，仍不相等

# vfat：mkfs.vfat 每次生成随机 volume id
$ mkfs.vfat -F 32 -n BASEOS -S 512 a.img   # 两次 → 差 4 字节（BPB volume id @0x43）
```

结论：**"镜像 SHA 不变"不能作为迁移的验收标准**，它今天就不成立。
可用的替代判据（本次实测均成立）：

| 判据 | 实测结果 |
|---|---|
| `rootfs.tar` 的**逐文件 manifest**（路径 + mode + uid/gid + 内容 sha256，排序后 sha256） | 两次 `cp -R` + tar 后 **manifest 相同** |
| `mksquashfs -mkfs-time 0` 的产物 | 两次运行 **字节相同** |
| `overlay/` 合成后的文件集合与内容 | 逐文件 `cmp`，可精确断言 |

因此 `07-migration.md` 的每一步都用**内容级**判据，不用镜像哈希。

### 7.4 测试如何按板参数化

- `tests/` 保留"机制测试"，断言对象是**行为**而非板名；
- `bsp/boards/<id>/tests/` 放"这块板的断言"（例如 `validate-on-device` 的 H700 节点集合）；
- 通用 runner 遍历 `bsp/boards/*/tests/`；
- `tests/test-baseos-config.sh:92` 那种"从 `devices.json` 里 sed 出 id"的写法
  改成读 `bsp/boards/*/board.json`，这样加板自动被覆盖。

---

## 8. 新增一台设备：step-by-step

以"同 SoC、新板型"（最常见）为例。**不允许**改动 `overlay/`、`runtime/`、
PocketJS、`tools/` 里的任何文件；违反即为架构失败。

### 8.1 同 SoC，新板型（例如 H700 家族的第 12 块板）

```sh
# 1. 建目录
mkdir -p bsp/boards/<id>

# 2. 写 board.json（照 5.1 的字段，capabilities/features 逐项显式）
$EDITOR bsp/boards/<id>/board.json

# 3. 校验 schema（未知字段、缺必填、枚举越界都在这里失败）
python3 tools/bsp_validate.py board bsp/boards/<id>/board.json

# 4. 从厂商固件准备输入（一次性，需要 .img）
./prepare-stock.sh <id> /path/to/<PREFIX>-....img

# 5. 结构门禁（分区形状、p1 空 ext4、p3 仍指向 rootfs、内核 ABI）
./verify-target.sh <id>

# 6. 构建 + 用户空间冒烟
./build-all.sh <id>

# 7. 真机验收（断言来自 board.json，不是脚本里的字面量）
./validate-on-device.sh <id> <device-ip> <root-password>
```

需要新增的**只有** `bsp/boards/<id>/`（1 个文件，或加 `overlay/`+`tests/`）。
`devices.json` 不需要改——它已经不存在了。

### 8.2 新 SoC，新板型

在 8.1 之上，先做 SoC 层：

```sh
# 1. bsp/<vendor>/<soc>/soc.json      ← 内核身份、模块、节点基线、hw_init
# 2. bsp/<vendor>/<soc>/harvest.list  ← 该 SoC 厂商 rootfs 的闭包（新基线，不是 H700 的子集）
# 3. bsp/<vendor>/<soc>/kernel/       ← 若需自建内核补丁；否则省略
# 4. bsp/<vendor>/<soc>/overlay/      ← SoC 专有的 hw init 片段
# 5. bsp/<vendor>/<soc>/tests/        ← fake sysfs 下的节点映射测试
# 6. bsp/boards/<id>/board.json       ← soc 指向上面
```

**新 SoC 的判据**：如果 `bsp/<soc>/overlay/` 里的内容无法被
`bsp/<soc>/soc.json` 的 `hw_init` + `nodes` 表达，说明 `soc.json` 的 schema 不够，
**先扩展 schema 再加设备**——这是唯一允许"改发行版代码"的合法情形，
且改的是 schema 而不是任何具体板的分支。

### 8.3 判据：第 51 台设备需要改已有设备的代码吗？

| 场景 | 需要改已有设备吗 | 为什么 |
|---|---|---|
| 同 SoC 新板 | **不需要** | 只新增 `bsp/boards/<id>/` |
| 新 SoC 新板 | **不需要** | 只新增 `bsp/<soc>/` + `bsp/boards/<id>/` |
| 厂商固件升级（同一板） | **不需要改代码**，只更新该板的 `source.json` 与 `profiles.json` 条目 | 见 `02 §6.1` |
| 新 SoC 需要 soc.json 表达不了的行为 | **需要改 schema**（发行版代码），但**不需要改任何已有板** | 这是设计允许的扩展点 |
| 新输入类别（例如触觉反馈的新语义） | **需要改 DAL 枚举**（发行版代码），但不需要改任何已有板 | 同上 |

**"新增设备时必须修改已有设备代码" = 设计失败。** 上表最后两行是
"扩展发行版接口"，不是"修改已有设备"——区别在于：扩展接口时，
所有已有板的行为**逐字节不变**；修改已有设备时，某台设备的行为会变。

---

## 9. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 两级（soc/board）合并规则复杂，容易写出"改了 SoC 影响所有板"的意外 | 高 | 合并规则只有一条：**深合并、板级胜、`null` 表示删除**。禁止任何条件逻辑 |
| `PROFILE_*` 接口一旦改变，12 个脚本同时失效 | 高 | 迁移期间该接口冻结（§7.1）；新增字段只加不改 |
| `bsp/boards/` 目录数增长到 50+ 后，`ls` 成为维护负担 | 低 | 目录不需要维护；需要视图时用 `tools/bsp_list.py` 生成表 |
| 内核补丁迁入 `bsp/` 后，`build-audio-module.sh` 的 docker 挂载路径变化 | 中 | 迁移步骤只改挂载路径，不改编译参数；用产物 `sha256` 断言等价 |
| lint 的 token 派生依赖目录名，改名会漏检 | 中 | lint 同时读 `board.json` 的 `identity.*`；改名本身要求改 `board.json` |
| 第 51 台设备时 `soc.json` schema 不够用，导致被迫加板级分支 | 中 | §8.2 的"先扩展 schema"是硬规定；PR 评审检查"是否出现板名条件分支" |

---

## 10. 验收标准（本文件的定义何时算落实）

| # | 标准 | 可执行判据 |
|---|---|---|
| A1 | 板名只出现在 `bsp/` 与 `docs/`/`tests/`/`experiments/` | `tools/bsp-lint.sh` 退出 0 |
| A2 | 新增板型只新增 `bsp/boards/<id>/` | PR 的 `git diff --name-only` 全部匹配 `^bsp/boards/<id>/` |
| A3 | `board.json` 未知字段报错 | 在 profile 里加 `"foo": 1`，`bsp_validate.py` 退出非 0 |
| A4 | `capabilities`/`features` 必须显式全给 | 删掉任一键，`bsp_validate.py` 退出非 0 |
| A5 | overlay 合成结果与迁移前逐文件一致 | `tools/overlay_manifest.py` 两份 manifest 相同 |
| A6 | `PROFILE_*` 接口未变 | `python3 tools/device_profile.py shell <id>` 输出键集合与 `main@dc99d57` 相同 |
| A7 | 第 51 台设备不需要改已有板的文件 | 新板 PR 里不存在对 `bsp/boards/<其他id>/` 的修改 |
