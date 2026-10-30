# 05 — Feature 模型

> Capability 回答"有没有"，Feature 回答"能干什么"。
> 本文件定义 Feature 的枚举、来源、三态、取证规则、bitmask 与 JSON 两种表达、
> 以及版本兼容策略。
>
> 解决 `01-audit.md` P1-3（能力与行为混在同一批布尔值里）。

---

## 1. 为什么需要：一个真实的反例

现状里 `wifi=true` 同时回答了两个问题：

1. "这台机器有没有 WiFi 硬件" → Capability
2. "harvest 要不要收 `wpa_supplicant`/`8821cs.ko`" → 构建期决策

（`tools/prepare_stock.py:489-499`、`devices.json:25`）

而"能干什么"这一整类问题**完全没有表达**：

| 问题 | 现状答案 | 在哪 |
|---|---|---|
| 能不能当蓝牙音箱（sink）？ | 不知道。`bluealsa` 被收进镜像（`manifest/harvest.list:120-121`），但没有任何代码启动它 | 无 |
| 音量能不能硬件控制？ | 不知道。`amixer` 控制名写死（`baseos-startup-sound:26-31`），失败静默 | 无 |
| 能不能 suspend？ | 能——前端直接写 `mem` 到 `/sys/power/state`（`docs/05-runtime-power-network.md:16`），但系统没有接口告诉应用这件事 | 无 |
| 能不能 RTC 唤醒？ | 不知道。只在实验里出现过一次（`docs/12-kernel-gzip.md:233`） | 无 |
| 能不能旋转？ | 能，但只是 splash 能（`src/fbsplash.c:882`）；运行时旋转无接口 | 无 |

**后果**：应用只能靠"调用试试"。而"试试"在多设备上产生静默错误——
这正是 `01-audit.md` 反复出现的模式。

---

## 2. 与 Capability 的严格分工

| | Capability | Feature |
|---|---|---|
| 问题 | 有没有这一类硬件 | 存在的硬件能不能做这个动作 |
| 粒度 | 11 项封闭枚举 | 可扩展枚举（见 §7） |
| 依据 | 硬件存在性 | 硬件 + 驱动 + 软件栈 + 已验证的行为 |
| 依赖 | 无 | 通常依赖一个或多个 Capability |
| 例子 | `bluetooth` | `bt_sink`、`bt_source` |
| 反例 | `bt_sink` 不是 Capability（它是能力，不是硬件） | `bluetooth` 不是 Feature（它是硬件，不是动作） |

**依赖关系必须显式声明**，且要能校验：

```
feature.bt_sink  ⇒ cap.bluetooth == yes
feature.suspend  ⇒ cap.rtc == yes?   否 —— suspend 不需要 RTC
feature.rtc_alarm ⇒ cap.rtc == yes
```

规则：**如果 `cap.X == no`，则所有依赖 X 的 feature 必须是 `no`**。
这是构建期可校验的一致性（`tools/bsp_validate.py`）。

反过来**不成立**：`cap.X == yes` 不蕴含任何 feature 是 `yes`。
蓝牙芯片存在 ≠ 能做 sink（可能缺 bluealsa 的 A2DP 配置）。

---

## 3. 枚举

### 3.1 v1 枚举（12 项）

| Feature | 含义 | 依赖 | 判据（"能干什么"的物理/软件依据） |
|---|---|---|---|
| `bt_sink` | 可作蓝牙音频接收端（手机连它放歌） | `bluetooth` | bluealsa + A2DP sink profile + 已验证 |
| `bt_source` | 可作蓝牙音频发送端（连蓝牙耳机） | `bluetooth` | bluealsa + A2DP source profile + 已验证 |
| `audio_hw_volume` | 音量由硬件混音器控制（非软件缩放） | `audio` | 存在可写的 mixer control |
| `audio_hw_mute` | 静音由硬件控制 | `audio` | 存在 mute switch |
| `display_rotation` | 运行时可变旋转（非仅 splash） | — | fb/DRM 支持旋转或软件旋转已验证 |
| `display_output_switch` | 可切换 LCD/HDMI | `hdmi` | dispdbg 或 DRM connector 切换已验证 |
| `suspend` | 可进入 suspend-to-RAM | — | `/sys/power/state` 含 `mem` 且实测可唤醒 |
| `rtc_alarm` | 可设定 RTC 闹钟唤醒 | `rtc` | RTC 有 `wakealarm` 或等价，且实测 |
| `usb_storage_export` | 可把卡导出为 USB 大容量设备 | `usb_gadget` | configfs mass_storage 已验证 |
| `usb_adb` | 可作 adb 设备 | `usb_gadget` | functionfs + adbd 已验证 |
| `usb_host_input` | 可外接 USB 手柄 | `usb_host` | host 控制器 + HID 已验证 |
| `wifi_ap` | 可开热点 | `wifi` | 驱动支持 AP 模式 |

**为什么是这 12 项**：每一项都对应"应用要做分支决策"的具体动作，且都能指向
一个可验证的行为。更细的（"支持 aptX"）属于 DAL `info` 输出或未来扩展。

### 3.2 明确**不在** v1 枚举里的

| 想表达 | 为什么不放进来 | 正确位置 |
|---|---|---|
| "支持 5GHz" | 是 WiFi 的属性，不是动作 | `dal_network_info` 的 `bands=` |
| "支持 60Hz 刷新" | 是显示的属性 | `dal_display_info` 的 `refresh_hz=` |
| "支持 2 个手柄" | 是输入枚举结果 | `dal_input_list` 的行数 |
| "支持 exFAT" | 是文件系统支持 | `dal_storage_info` 的 `fs_supported=` |

规则：**Feature 只描述"动作"，不描述"属性"。** 属性属于 DAL 的 `info` 输出。

---

## 4. 来源

### 4.1 声明源：`board.json` 的 `features`

```
board.json  features: {bt_sink: yes, bt_source: yes, audio_hw_volume: yes, ...}
soc.json    features: {…}   ← SoC 级默认，板级可覆盖
                ↓ 深合并（板级胜）
构建时生成   /etc/pjos/features.json
```

**必须显式给出全部 12 个键**（与 Capability 同样的规则，`02 §5.3`）。

### 4.2 生成物：`/etc/pjos/features.json`

```json
{
  "schema": "pjos.features/1",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "features": {
    "bt_sink": "yes", "bt_source": "yes",
    "audio_hw_volume": "yes", "audio_hw_mute": "unknown",
    "display_rotation": "yes", "display_output_switch": "yes",
    "suspend": "yes", "rtc_alarm": "unknown",
    "usb_storage_export": "yes", "usb_adb": "yes", "usb_host_input": "yes",
    "wifi_ap": "unknown"
  }
}
```

### 4.3 H700 当前的实际情况（诚实标注）

**取证规则（与 `04 §5` 同一条）**：`yes` 必须能指向实测证据。

| Feature | H700 取值 | 证据 / 缺证据的原因 |
|---|---|---|
| `bt_sink` | **`unknown`** | `bluealsa` 与 `bluealsa-aplay` 在镜像里（`manifest/harvest.list:120-121`），但**没有任何代码启动它们**；A2DP sink profile 未验证 |
| `bt_source` | **`unknown`** | 同上 |
| `audio_hw_volume` | **`unknown`** | `amixer -c 0 sset 'digital volume' 63` 存在（`baseos-startup-sound:26`），但"控制名存在"≠"改它真的改变输出音量"；`docs/05` 没有音量实测记录。**待实测** |
| `audio_hw_mute` | **`unknown`** | 无任何 mute control 的证据 |
| `display_rotation` | **`unknown`** | 只有 splash 能旋转（`src/fbsplash.c:882`）；运行时旋转无实现 |
| `display_output_switch` | `yes` | `rcS:66-71` 注释明确说 dispdbg 切换 LCD/HDMI，且 issue #10 验证过 |
| `suspend` | `yes` | `docs/05:16`（前端写 `mem`）；`validate-on-device.sh:71`（`grep -q mem /sys/power/state`） |
| `rtc_alarm` | **`unknown`** | 只有 `docs/12:233` 的一次实验记录；发行版无接口 |
| `usb_storage_export` | `yes` | `overlay/usr/sbin/usb-storage-mode` 完整实现 + `docs/08` 描述的工作流 |
| `usb_adb` | `yes` | `validate-on-device.sh:97-98`（g1/UDC + functionfs） |
| `usb_host_input` | `yes` | `validate-on-device.sh:88-89`（六个 root hub，`h700_late_usb` 启动） |
| `wifi_ap` | **`unknown`** | 无 AP 模式证据 |

**5 个 `unknown` 是这份设计的诚实部分**：它们标记了"我们不知道"的地方，
而不是假装知道。每一个 `unknown` 都是一条待办（见 §9）。

---

## 5. 三态与降级

三态语义与 `04 §2` 完全相同（`yes`/`no`/`unknown`，`unknown ≠ no`）。
Feature 特有的部分：

### 5.1 依赖不一致时的降级

构建期校验（`tools/bsp_validate.py`）：

```
若 cap.X == no 且存在依赖 X 的 feature.Y != no
    → 构建失败
```

运行时校验（`baseosctl feature get --verify`）：

```
若 cap.X 实测降为 unknown（04 §4.3），则 feature.Y 也降为 unknown
若 cap.X 实测仍为 no（声明就是 no），feature.Y 必须是 no（构建期已保证）
```

**方向只有一个：`yes` → `unknown`，绝不升级。**

### 5.2 应用层降级

| Feature | `no` | `unknown` |
|---|---|---|
| `bt_sink` | 无"蓝牙音箱模式"菜单 | 显示菜单，标"未验证"，点击时明确提示 |
| `bt_source` | 无"连接蓝牙耳机" | 同上 |
| `audio_hw_volume` | 音量用软件缩放（应用自己乘系数） | 优先试硬件；失败回落软件，并在设置里标"软件音量" |
| `display_rotation` | 无旋转选项 | 显示但置灰 |
| `suspend` | 无"睡眠"按钮，只有关机 | 显示，点击时提示"本机未验证睡眠" |
| `rtc_alarm` | 无"定时唤醒" | 同上 |
| `wifi_ap` | 无热点开关 | 同上 |

**`audio_hw_volume == unknown` 的降级是唯一允许"回落"的情形**：
因为软件缩放总能工作。其余情形不允许回落——回落等于猜测。

---

## 6. 表达形式：JSON 与 bitmask

两种表达，用途不同。

### 6.1 JSON（权威形式）

`/etc/pjos/features.json` 与 `baseosctl feature list --json` 用 JSON。
理由：可读、可扩展、能带 `unknown`。

### 6.2 bitmask（可选，给资源受限消费方）

**用途**：给需要"一次读 4 字节就知道全部 feature"的消费方（例如未来某个
静态链接的 C 工具、或 32 位嵌入式前端）。

**格式**：

```
bits 0..11    = v1 的 12 个 feature，顺序即 §3.1 表格顺序
bits 12..29   = 保留（必须为 0）
bit  30       = "有 unknown 项"标志
bit  31       = "bitmask 格式版本 1"标志（恒为 1）
```

具体位序（**这份表就是契约**）：

| bit | Feature |
|---|---|
| 0 | `bt_sink` |
| 1 | `bt_source` |
| 2 | `audio_hw_volume` |
| 3 | `audio_hw_mute` |
| 4 | `display_rotation` |
| 5 | `display_output_switch` |
| 6 | `suspend` |
| 7 | `rtc_alarm` |
| 8 | `usb_storage_export` |
| 9 | `usb_adb` |
| 10 | `usb_host_input` |
| 11 | `wifi_ap` |

**编码规则**：

```
bit = 1  →  feature == yes
bit = 0  →  feature == no 或 unknown（需要 bit30 区分）
```

**这是一个有损编码**：`no` 与 `unknown` 都编码为 0。因此：

> **任何依赖"区分 no 与 unknown"的消费方，必须用 JSON，不得用 bitmask。**

`bit30`（"有 unknown 项"）只告诉你"至少有一项不确定"，不告诉你是哪一项。
这是刻意的：完整三态需要 24 位（每项 2 位），而 24 位 bitmask 的可读性
不如 JSON，收益不足以证明复杂度。

`baseosctl feature bitmask` 输出十进制与十六进制两个值：

```
bitmask=1439
bitmask_hex=0x8000059f
```

（`0x8000059f` = bit31 | bit30? 视取值而定；实际值由实现计算，此处仅示形。）

### 6.3 为什么还要提供 bitmask

因为**第 51 台设备**的判据里有一条是"消费方不需要改代码就能读新设备的 feature"。
JSON 天然满足；bitmask 的位序是固定的，新增 feature 会占用 bit 12，
**旧消费方的 `& mask` 仍然正确**（它们不认识 bit 12，忽略即可）。
这让 bitmask 成为一个**向后兼容的快速路径**。

**代价**：位序一旦发布不能改。写进 `bsp/schema/features.schema.json` 的
`"bitmask_order"` 数组，且加一条测试断言"枚举顺序 == bitmask 顺序"。

---

## 7. 扩展流程（新增一个 Feature）

与 `04 §8` 同构，但多两步：

1. 在 `bsp/schema/board.schema.json` 的 `features` 枚举里加键；
2. 在 `bsp/schema/features.schema.json` 的 `bitmask_order` 末尾追加（**只能追加**）；
3. 若依赖某 Capability，在 schema 的 `depends` 里声明；
4. 在 `03-dal.md` 里确认有对应的 DAL 调用（Feature 的 `yes` 必须能被执行）；
5. 更新全部 `bsp/boards/*/board.json`（纯新增键，行为不变）；
6. 更新 `06-baseosctl.md` 的 `feature` schema；
7. 更新本文件的枚举表与位序表。

**判据（与 `02 §8.3` 一致）**：扩展接口时所有已有板行为逐字节不变；
若某台设备的行为会变，那不是"扩展"，是"修改已有设备"。

### 7.1 什么时候**不**该新增 Feature

| 想表达 | 为什么不该是 Feature |
|---|---|
| "支持某款蓝牙耳机" | 是兼容性列表，属于测试矩阵 |
| "音量最大 63" | 是属性，`dal_audio_info` |
| "支持双屏" | 是 display 的结构，`dal_display_output list` |
| "支持某个编解码器" | 是属性；若应用要做分支，才考虑升为 Feature |

---

## 8. 版本兼容策略

### 8.1 三处版本

| 位置 | 字段 | 变更规则 |
|---|---|---|
| `features.json` | `"schema": "pjos.features/1"` | 新增键不升；删键/改语义升 2 |
| `baseosctl feature` 输出 | 同上 | 跟随文件 |
| bitmask | bit31 = 格式版本 1 | 新增 feature 不升；改位序或语义升 2 |

### 8.2 消费方契约

| 消费方版本 | 面对 `pjos.features/2` 时的正确行为 |
|---|---|
| v1 | **拒绝**并报 `unsupported schema`（不得静默忽略） |
| v1 | 面对 `pjos.features/1` 里的未知键 → **忽略**（前向兼容） |

这条不对称是刻意的：

- **未知键忽略** → 让新系统 + 旧应用能工作（应用只是不显示新功能）；
- **未知 schema 拒绝** → 让"语义变了"无法被静默误读。

`04 §9` 的 Capability 用完全相同的策略。

### 8.3 bitmask 的兼容矩阵

| 场景 | 旧消费方（认识 12 位） | 新消费方（认识 15 位） |
|---|---|---|
| 系统只有 12 个 feature | 正确 | 正确（高 3 位为 0） |
| 系统有 15 个 feature | **正确**（忽略 bit 12-14） | 正确 |
| 系统把 bit 5 的语义改了并升到 schema 2 | **错误**（会误读 bit 5） | 正确 |

第三行说明：**改语义必须升 bitmask 格式版本（bit31 无法表达"2"）**。
所以 bit31 只是个"这是一个 bitmask"的标记，真正的版本在 `baseosctl` 输出里：

```
bitmask=1439
bitmask_hex=0x8000059f
bitmask_version=1
```

消费方必须检查 `bitmask_version`。这是 bitmask 唯一的弱点，
也是为什么 JSON 是权威形式。

---

## 9. `unknown` 的待办清单（本设计产生的实际工作项）

每一个 `unknown` 都是"需要实测才能变 `yes`"的条目。这是本阶段的**产出**，
不是缺陷：

| Feature | 变 `yes` 需要做的验证 | 影响 |
|---|---|---|
| `bt_sink` | 启动 bluealsa 作 sink，用手机连接播放 | 蓝牙音箱模式可用性 |
| `bt_source` | 启动 bluealsa 作 source，连蓝牙耳机 | 蓝牙耳机支持 |
| `audio_hw_volume` | 改 mixer 后测量实际输出（示波器/录音） | 音量语义是否正确 |
| `audio_hw_mute` | 找 mute switch 并验证 | 静音语义 |
| `display_rotation` | 运行时旋转并抓帧 | 旋转功能 |
| `rtc_alarm` | 设定 alarm → suspend → 观察唤醒（`docs/12:233` 的复现） | 定时唤醒 |
| `wifi_ap` | `hostapd` 或 `wpa_supplicant` AP 模式 | 热点 |

**这些验证不属于第一阶段**（本阶段只做设计）。列在这里是为了让
"我们不知道"变成可追踪的工作项，而不是散落在各文档的"待查"里。

---

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 维护者为省事全写 `yes` | 高 | 取证规则（§4.3）+ PR 评审 |
| `unknown` 过多导致 UI 全是置灰项 | 中 | `unknown` 的 UI 规范：默认显示但置灰，且"关于本机"里可查；不做成错误态 |
| bitmask 位序被改 | 高（破坏旧消费方） | schema 里锁死 `bitmask_order` + 测试断言 |
| Feature 枚举膨胀到几十项 | 中 | §7.1 的"不该新增"清单 |
| Feature 与 DAL 脱节（声明 `yes` 但没有 DAL 能执行） | 高 | §7 第 4 步：新增 Feature 必须确认有 DAL 调用 |
| 依赖校验只在构建期，运行时硬件缺失 | 中 | 运行时校验把 `yes` 降 `unknown`（§5.1） |

---

## 11. 验收标准

| # | 标准 | 判据 |
|---|---|---|
| F1 | 每条 `board.json` 显式含 12 个 feature 键 | `tools/bsp_validate.py` 检查键集合相等 |
| F2 | 依赖一致性在构建期强制 | 构造 `cap.bluetooth=no` + `features.bt_sink=yes`，构建失败 |
| F3 | bitmask 位序与枚举顺序一致 | 单元测试断言 `bitmask_order == 枚举顺序` |
| F4 | `no` 与 `unknown` 在 JSON 里可区分，在 bitmask 里不可区分 | 断言 `feature list --json` 有 3 种值；`feature bitmask` 只有 2 种位 |
| F5 | 未知 schema 被拒绝 | 把 `features.json` 的 schema 改成 `pjos.features/9`，`baseosctl feature list` 退出非 0 |
| F6 | 未知键被忽略 | 在 `features.json` 里加 `"future_thing": "yes"`，`baseosctl feature list` 仍退出 0 |
| F7 | 每个 `yes` 有证据 | 人工评审清单（本阶段无法自动化；`04 §5` 同） |
