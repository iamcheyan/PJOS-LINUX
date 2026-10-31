# BSP v2 — 架构设计（第一阶段）

PocketOS 从**单 SoC 发行版**重构成**多设备发行版平台**的设计文档集。
本阶段**只做设计，不含实现代码**。

跟踪：issue #103 · 分支：`feature/bsp-v2` · 基线：`main` @ `dc99d57` · 版本：`1.5.2`

---

## 1. 目标架构

```
Application Layer      PocketJS launcher / games / 第三方前端
        ↓              不知道设备类型
Runtime Layer          keyboardd / pocket-linux-kms / guest runtime
        ↓              不知道设备类型
BaseOS Services        init / rcS / frontend-session / update / baseosctl
        ↓              只知道语义
DAL                    display audio input power network storage led
        ↓              只知道 board.json 的 nodes
BSP                    bsp/<vendor>/<soc>/ + bsp/boards/<board>/
        ↓              唯一允许出现板名/SoC 名的地方
Hardware
```

**最终目标不是 BSP，而是**：让 PocketJS 永远不知道自己运行在什么设备上。

---

## 2. 文档索引

| 文件 | 一句话结论 |
|---|---|
| [`01-audit.md`](01-audit.md) | 板级事实存在 **5 份独立副本、零交叉校验**；`overlay/` 39 个文件里 14 个含板名；11 台设备 = 55 处手工登记 |
| [`02-bsp-boundary.md`](02-bsp-boundary.md) | BSP 是 `bsp/<vendor>/<soc>/` + `bsp/boards/<board>/` 两级；新增同 SoC 板型只加 1 个 `board.json`；未知字段必须报错 |
| [`03-dal.md`](03-dal.md) | 7 个子系统的 API 签名 + 37 处节点字面量 → DAL 调用的全量映射表；DAL 是**库**不是守护进程 |
| [`04-capability.md`](04-capability.md) | 11 项封闭枚举，三态 `yes`/`no`/`unknown`；**`unknown ≠ no`**；`yes` 必须有实测证据 |
| [`05-feature.md`](05-feature.md) | 12 项动作枚举；JSON 是权威形式，bitmask 是有损快速路径；H700 上 5 项诚实标为 `unknown` |
| [`06-baseosctl.md`](06-baseosctl.md) | 10 个命令组，`key=value` 或 `--json`，**禁止人类散文**；退出码 `3`(未知) 与 `4`(不支持) 必须区分 |
| [`07-migration.md`](07-migration.md) | **9 个可独立合并的步骤**；前 4 步不改镜像内容；每步给出影响范围/验证/回滚/零变化证明 |
| [`08-ranking.md`](08-ranking.md) | 9 个备选方案与被否决理由；两个被推迟的方案都留了扩展点 |
| [`schema/board.schema.json`](schema/board.schema.json) | Device Profile v2 的 JSON Schema（`additionalProperties: false`） |
| [`schema/soc.schema.json`](schema/soc.schema.json) | SoC 级事实的 JSON Schema |
| [`schema/caps.schema.json`](schema/caps.schema.json) | `/etc/pjos/caps.json` 的生成物 schema |
| [`schema/features.schema.json`](schema/features.schema.json) | `/etc/pjos/features.json` + bitmask 位序（append-only） |

**阅读顺序**：先 `01`（为什么改），再 `02`（边界），然后 `03`（接口），
`04`/`05`（两个模型），`06`（对外接口），`07`（怎么落地）。
`08` 是给质疑者看的。

---

## 3. 术语表（全文档统一）

| 术语 | 定义 | 首次定义 |
|---|---|---|
| **BSP** | 一块板子的全部差异，放在 `bsp/` 下可被构建系统发现的目录里 | `02 §1` |
| **SoC 级事实** | 同一 SoC 上所有板共享的事实（内核、模块、harvest 基线、节点映射） | `02 §4` |
| **板级事实** | 一块板独有的（面板、输入、电源、capabilities、features） | `02 §5` |
| **Device Profile v2** | `board.json`，替代 `devices.json` | `02 §5` |
| **Capability** | 回答"**有没有**"这一类硬件。11 项封闭枚举，三态 | `04 §3` |
| **Feature** | 回答"**能干什么**"。12 项动作枚举，三态 | `05 §3` |
| **DAL** | 把设备节点翻译成稳定语义的库 | `03 §1` |
| **语义** | 与设备无关的接口（`dal_power_battery` 而不是 `/sys/class/power_supply/...`） | `03 §1.4` |
| **三态** | `yes` / `no` / `unknown`；**`unknown ≠ no`** | `04 §2` |
| **角色（role）** | 分区用途（`boot`/`rootfs`/`data`/`primary`），不是分区号 | `03 §8.2` |
| **零变化** | 行为不变。M6 之后 rootfs **内容会变**，但行为不变 | `07 §3` |
| **内容级判据** | 逐文件 manifest（path+mode+uid+gid+sha256），不是镜像 SHA | `07 §1` |

### 3.1 一个必须澄清的命名冲突

`runtime/keyboardd` 已经有一个 `Capability` 类型
（`runtime/keyboardd/keyboardd.go:43-53`），含义是**输入类别**
（`Touch`/`DPad`/`Gamepad`/`HardwareKeyboard`），由 provider 声明。

本设计集的 `Capability` 是**整机硬件有无**。两者层次不同：

- 整机：`baseosctl cap list` → `wifi=yes`（小写下划线，11 项）
- 输入类别：`baseosctl input list` → `kind=keyboard|power|gamepad|touch`
- keyboardd 的 `Capabilities` 数组**不进入** `cap` 命名空间

详见 `04 §3.2`。**保留两套名字，但在线上格式上区分。**

---

## 4. 核心判据

> **如果增加第 51 台设备，是否需要修改已有设备的代码？**
> 需要 → 设计不合格。

本设计的答案：

| 场景 | 需要改已有设备吗 |
|---|---|
| 同 SoC 新板 | **不需要**（只加 `bsp/boards/<id>/board.json`） |
| 新 SoC 新板 | **不需要**（加 `bsp/<vendor>/<soc>/` + `bsp/boards/<id>/`） |
| 厂商固件升级（同板） | **不需要改代码**（更新该板的 `source.json` 与内核 profile 条目） |
| 新 SoC 需要 schema 表达不了的行为 | 改 **schema**（发行版代码），不改任何已有板 |
| 新输入类别 / 新 Capability | 改 **枚举**（发行版代码），不改任何已有板 |

最后两行是"扩展接口"，判据是：**所有已有板的行为逐字节不变**。

---

## 5. 需要用户拍板的决策点

以下是**产品/组织决策**，本设计不替用户决定。每条给出选项、影响、建议。

### D1 — `touch` 在 H700 掌机上是什么值？

**背景**：`04 §5` 的证据表里，`touch` 无法从仓库内证据确定。
`keyboardd` 的 `CapTouch` 是 provider 属性，不是整机事实。

| 选项 | 影响 |
|---|---|
| `no`（全部 11 台） | 应用永不启用触摸手势；若某台实际有触摸屏则功能缺失 |
| `unknown`（全部 11 台） | 应用显示但置灰；用户会问"为什么不能用" |
| 逐板实测后填 | 最准确，需要 11 台真机或厂商规格 |

**建议**：`unknown`，直到有实测证据。这是 `04 §5` 的默认值。

### D2 — `vibration` 在 H700 上是什么值？

**背景**：`axp2202-battery/moto` 存在且可写（`validate-on-device.sh:70`），
但"可写 moto 节点"不等于"机器上有马达"。

| 选项 | 影响 |
|---|---|
| `yes` | 应用提供震动反馈；若无马达则静默无效 |
| `unknown` | 应用显示但置灰 |
| 实测 | 需要真机按一次 |

**建议**：`unknown`，直到实测。**注意**：`moto` 节点可能存在于所有 H700 上
（PMIC 统一暴露），所以"节点存在"不能作为证据。

### D3 — 是否需要 `baseosd` 常驻进程？

**背景**：`03 §1.2` 与 `08 §5` 论证了 v1 不做。触发条件写在 `08 §12`。

| 选项 | 影响 |
|---|---|
| v1 不做（**当前设计**） | `baseosctl` 每次 fork 重读；冷启动 < 50 ms 目标需实测 |
| v1 就做 | 可推送事件；但增加单点故障，与 `rcS:2-3` 的 1 秒预算冲突 |

**建议**：v1 不做。若 `baseosctl display info` 冷启动超过 50 ms，再评估。

### D4 — PocketJS 的 compat shim 是否保留"失败回落旧路径"？

**背景**：`docs/13-pocketjs-on-baseos.md:57` 的 6 个 shim 现在直接读 `/sys`、
调 `amixer`/`wpa_cli`。`06 §8` 建议改为调 `baseosctl` 且**不回落**。

| 选项 | 影响 |
|---|---|
| 不回落 | 失败可见，问题能暴露；但一次 `baseosctl` bug 会让 UI 功能全失效 |
| 保留回落 | 过渡期安全；但"没有"会变成"猜"，正是本设计要消除的 |

**建议**：过渡期（M7a 合并后）保留回落，M8 之后删除。**需要用户确认过渡期长度。**

### D5 — `feature.audio_hw_volume` 在 H700 上是什么值？

**背景**：`amixer -c 0 sset 'digital volume' 63` 存在
（`baseos-startup-sound:26`），但"控制名存在"≠"改它真的改变输出音量"。
`docs/05-runtime-power-network.md` 没有音量实测记录。

| 选项 | 影响 |
|---|---|
| `yes` | 应用走硬件音量；若实际是软件缩放，音量曲线会不对 |
| `unknown` | 应用优先试硬件，失败回落软件（`05 §5.2` 唯一允许回落的情形） |

**建议**：`unknown`。这条是 5 个 `unknown` 里最可能被误填 `yes` 的，
因为控制名确实存在。

### D6 — 是否接受"11 台里只有 2 台有真机验证"这一事实？

**背景**：`experiments/h700-boot-speed/native/verify-fleet.py:20` 写
`LIVE_TARGETS = {"rg34xxsp", "rg40xxv"}`。其余 9 台的"零变化"只能是
**构建期等价 + 内容级等价**，不是实测等价。

| 选项 | 影响 |
|---|---|
| 接受（**当前设计**） | 发布说明里明确区分 built / qemu-booted / device-verified 三态 |
| 要求全部真机验证 | 需要 11 台设备与 11 次刷机；会阻塞 M5–M7 |
| 抽样验证 | 折中；需定义抽样规则 |

**建议**：接受三态区分，并在 `validate-on-device.sh` 的输出里强制标注
验证到哪一态。**这一点影响发布声明，必须用户拍板。**

### D7 — `bsp/schema/` 的所有权：BSP 还是发行版？

**背景**：`02 §3` 把 schema 放在 `bsp/schema/`，理由是"谁定义谁拥有"。
但 schema 是发行版代码（改它要改 `tools/bsp_validate.py`）。

| 选项 | 影响 |
|---|---|
| `bsp/schema/`（**当前设计**） | BSP 自包含；但 lint 需要允许 `bsp/` 下出现板名（本来就允许） |
| `tools/schema/` | 与发行版代码同处；但 BSP 目录不再自包含 |

**建议**：`bsp/schema/`。因为第 51 台设备的维护者只需要看 `bsp/`。

---

## 6. 本阶段交付范围

**已交付**（仅文档 + schema）：

```
docs/bsp-v2/
├── README.md                  本文件
├── 01-audit.md                当前架构问题审计
├── 02-bsp-boundary.md         BSP 边界定义
├── 03-dal.md                  DAL 边界与接口
├── 04-capability.md           Capability 模型
├── 05-feature.md              Feature 模型
├── 06-baseosctl.md            CLI 规格
├── 07-migration.md            迁移路线图
├── 08-ranking.md              方案对比与被否决理由
└── schema/
    ├── board.schema.json
    ├── soc.schema.json
    ├── caps.schema.json
    └── features.schema.json
```

**明确未做**（属于后续阶段，见 `07 §6`）：

- 未创建 `bsp/` 目录（M2）
- 未修改任何构建脚本（M3/M4）
- 未移动 `src/` 或 `manifest/`（M5）
- 未实现 DAL 或 `baseosctl`（M6/M7）
- 未改动 PocketJS（M8，跨仓库）
- 未做 A133 支持（M5 之后验证架构）

**本阶段不产生任何镜像内容变化。**

---

## 7. 如何验证本设计

### 7.1 schema 自检（本阶段可执行）

```sh
# 全部 schema 是合法 JSON
for f in docs/bsp-v2/schema/*.json; do python3 -m json.tool "$f" >/dev/null; done

# 用一条样例 profile 验证 board schema
nix shell nixpkgs#check-jsonschema -c \
  check-jsonschema --schemafile docs/bsp-v2/schema/board.schema.json <profile>.json
```

本次实测结果（2026-10-30，HX90）：

| 用例 | 结果 |
|---|---|
| 合法 profile | **ACCEPTED** |
| 未知字段 `foo` | REJECTED |
| 缺 `capabilities.touch` | REJECTED |
| `capabilities.wifi = true`（非三态） | REJECTED |
| `panel.rotation_ccw = 45` | REJECTED |
| 缺 `features.wifi_ap` | REJECTED |
| `schema = pjos.board/2` | REJECTED |
| `input` 既无 `keyboard_name` 也无 `event_hint` | REJECTED |
| 合法 soc/caps/features | ACCEPTED（各 1 例） |
| soc `hw_init.when = whenever` / 缺 `nodes` / `arch = mips` | REJECTED |
| caps 缺 `audio` / `schema = pjos.caps/2` | REJECTED |
| features `bitmask_version = 2` / 缺 `suspend` | REJECTED |

### 7.2 审计结论可核验

`01-audit.md` 的每条结论都带 `路径:行号`。抽查：

```sh
sed -n '268,274p' src/h700-speaker-amp/h700_speaker_amp.c   # banner strcmp
sed -n '489,499p' tools/prepare_stock.py                    # omission_allowed
sed -n '1,8p'     manifest/harvest.list                      # H700 基线注释
grep -rliE 'h700|axp2202|sunxi|allwinner|8821|mali|rtl_bt' overlay/ | wc -l   # 14
```

### 7.3 迁移步骤的可执行性

`07-migration.md` 每一步都有可复制的验证命令。M1–M4 不需要真机。

### 7.4 现有测试仍全绿（证明本阶段无回归）

本阶段只新增文档，但为确认基线完好，实测跑过：

```
tests/test-splash-rotation.sh      PASS
tests/test-boot-menu-held.sh       PASS
tests/test-baseos-config.sh        PASS
tests/test-poweroff-policy.sh      PASS
tests/test-rtc-utc-policy.sh       PASS
tests/test-boot-splash-policy.sh   PASS
tests/test-frontend-session.sh     PASS
tests/test-usr-lib-image.sh        PASS
tests/test-gpt-slot.sh             PASS
tests/test-h700-speaker-amp-load.sh PASS
tests/test-usb-storage-mode.sh     PASS
tests/test-baseos-mdns.sh          PASS
tests/test-systemctl-wifi.sh       PASS
tests/test-update-apply.sh         PASS
tests/test-boot-migration.sh       PASS
tests/test-root-mount.sh           PASS
tests/test-input-dir-time.sh       PASS
tests/test-timedatectl.sh          PASS
tests/test-usb-gadget-adb.sh       PASS
tests/test-power-intent.sh         PASS
tests/test-audio-gating.py         PASS
tests/test-audio-module.py         PASS
tests/test-strip-gpu-module.py     PASS
tests/test-baseos-diag.sh          PASS
tests/test-wifi-init.sh            PASS
tests/test-axp-off.sh              PASS
tests/test-startup-sound.sh        PASS
python3 tests/test-verify-harvest.py   PASS
python3 tests/test-prepared-cache.py   PASS
```

**已知的既有失败（与本阶段无关）**：

`tests/test-old-updaters.sh` 需要 git tag `v1.0.0`…`v1.4.0`，
而本仓库本地与 origin **都没有任何 tag**（`git tag | wc -l` = 0，
`git ls-remote --tags origin | wc -l` = 0），因此失败于
`fatal: invalid object name 'v1.0.0'`。这是环境缺失，不是代码缺陷。

需要 firmware 输入的三个测试（`test-kernel-gzip.py`、`test-late-usb.py`、
`test-lib-image.py`）未运行：本机 `work/` 只有 `h700-loader`，
没有 prepared firmware（`fetch-prepared.sh` 未执行，需要下载 ~133 MB bundle）。

### 7.5 引用约定（`路径:行号`）

本目录所有结论都写成 `路径:行号`，路径**相对仓库根**。为便于阅读，
文档里对少数在仓库中**文件名唯一**的脚本使用了省略目录的短形式。
短形式到完整路径的解析表：

| 短形式 | 完整路径 |
|---|---|
| `rcS:N` | `overlay/etc/init.d/rcS:N` |
| `baseos-startup-sound:N` | `overlay/usr/sbin/baseos-startup-sound:N` |
| `baseos-update:N` | `overlay/usr/sbin/baseos-update:N` |
| `boot-menu-held:N` | `overlay/usr/sbin/boot-menu-held:N` |
| `expand-storage:N` | `overlay/usr/sbin/expand-storage:N` |
| `frontend-session:N` | `overlay/usr/sbin/frontend-session:N` |
| `systemctl:N` | `overlay/usr/sbin/systemctl:N` |
| `usb-gadget-adb:N` | `overlay/usr/sbin/usb-gadget-adb:N` |
| `usb-storage-mode:N` | `overlay/usr/sbin/usb-storage-mode:N` |

（每个短形式在仓库中只有一处匹配，可 `find . -name <短形式>` 验证。）

本阶段交付时对全部引用做过一次机械核验：**192 处 `路径:行号` 引用
全部指向存在的文件且行号在文件范围内**。

---

## 8. 与 `docs/15-bsp-architecture.md` 的关系

`docs/15` 是本设计的**前身**：它已经提出了分层、BSP 目录形态、Capability、
`baseosctl`、五阶段迁移。本设计集是它的**具体化与修正**。

### 8.1 沿用

- 分层结构（`15 §3`）——本设计原样沿用
- 三条硬约束（`15 §3`）——沿用，并在 `02 §2.1` 补充了"规则的适用范围"
- `bsp.json` / `board.json` 两级（`15 §4.1-4.3`）——沿用，扩充字段
- 三态 Capability（`15 §6.2`）——沿用，补充了取证规则与降级方向
- `baseosctl` 作为唯一接口（`15 §6.4`）——沿用，补充了退出码与 schema

### 8.2 修正

| `docs/15` 的说法 | 本设计的修正 | 理由 |
|---|---|---|
| `bsp/boards/` 是板级，但目录名暗示"在 vendor 下"（`15 §4.1` 的缩进） | 提到 `bsp/` 顶层 | 板级事实里 `soc` 是字段不是路径；换 SoC 应是字段改动 |
| 迁移 Phase 2 验收"镜像哈希与 Phase 1 相同"（`15 §7`） | 改为**内容级 manifest** | 实测：ext4/vfat 构建本身不确定（`07 §1`） |
| "profile 只描述事实"但未规定"未知字段必须报错"（`15 §5.2`） | 加 `additionalProperties: false` | 防止文档发明不存在的字段（`docs/14:21` 的实例） |
| 未区分 Capability 与 keyboardd 的 Capability | 明确两套命名空间 | `runtime/keyboardd/keyboardd.go:43-53` 已占用该词 |
| Phase 3 说 `baseosctl` 可以是"busybox sh 或静态 C" | 定为 sh 优先，并给出冷启动约束 | 与现有 666 行 `baseos-diag` 的实现风格一致 |
| 未给出 Feature 模型 | 新增 `05-feature.md` | issue 明确要求 |
| 未量化"5 份板级事实副本" | `01 §1` 给出 T1–T5 与复现命令 | 审计必须可核验 |

### 8.3 `docs/15` 中未落实的部分

`docs/15 §7` 的 Phase 1 提到"补一份 `docs/16-device-matrix.md`"。
该文件**不存在**，且 `docs/16-keyboardd-input-framework.md` 已占用编号 16
（其标题还写着 `# 13 —`，与文件名不一致）。

本设计集用 `01-audit.md §1` 的 T1–T5 表替代了 device-matrix 的职能
（它就是"每台设备的 SoC、内核、面板、输入、电源节点"的量化形式）。
**建议**：若仍需 device-matrix，它应由 `bsp/boards/*/board.json` 生成，
而不是手写。

---

## 9. 下一步

1. 用户拍板 §5 的 7 个决策点（D1–D7）；
2. 按 `07-migration.md` 从 M1 开始；
3. 每个 M 步骤单独开 PR，PR 描述里填 `07 §3` 的证据表；
4. M1–M4 可合并进同一个发布（都不改镜像内容）；
5. M5 之后每次发布前跑真机验证。

**验收标准**（复述 `docs/15:365` 的判据）：

> 加第二台设备时，如果 PR 里出现了 `overlay/` 或 PocketJS 仓库的改动，
> 说明架构没做对。
