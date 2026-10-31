# 04 — Capability 模型

> Capability 回答"**有没有**"：这台机器上存在不存在这一类硬件。
> Feature（`05`）回答"**能干什么**"：存在的硬件能不能做某个具体动作。
> 本文件定义 Capability 的枚举、来源、三态语义、缺失时的降级行为、以及
> `baseosctl` / PocketJS 的消费方式。
>
> 解决 `01-audit.md` P1-2（能力被烘焙但无人读取）。

---

## 1. 为什么需要（问题陈述）

**现状**：能力信息存在，但只用于构建期裁剪，运行期无人问。

- `build-rootfs.sh:129` 把 `BASEOS_WIFI`/`BASEOS_BLUETOOTH` 写进 `/etc/baseos-release`；
- 运行时读取它们的脚本数量：**0**（`grep -rn 'BASEOS_WIFI\|BASEOS_BLUETOOTH' overlay/` 为空）；
- 唯一的消费方是 `tools/prepare_stock.py:489-499`（harvest 裁剪）和
  `validate-on-device.sh:72-76`（测试断言）。

**后果**：应用只能用"试了才知道"的方式判断能力，而失败与"没有"不可区分。

具体的三处证据：

| 场景 | 现状 | 用户看到什么 |
|---|---|---|
| 显示后端 | 应用先试 `/dev/dri/card0..1`，失败退 fbdev（`docs/13-pocketjs-on-baseos.md:19`） | failure streak 累积，日志噪音 |
| 亮度 | 无 `/sys/class/backlight`，但有 `/sys/class/disp/disp/attr`（`docs/13:20`） | 亮度项显示 `unknown`，用户以为坏了 |
| 音量 | `amixer` 控制名写死（`overlay/usr/sbin/baseos-startup-sound:26-31`） | 换设备后控制名不存在，静默失败 |

**目标**：把"这台机器有什么"变成**可查询的契约**，让"没有"是一个明确答案。

---

## 2. 三态语义（最重要的一条）

每个 Capability 有三个值：

| 值 | 含义 | 应用应该怎么做 |
|---|---|---|
| `yes` | 硬件存在，且已被**验证**（见 §5） | 显示相关 UI，调用对应 API |
| `no` | 硬件**确定**不存在 | 隐藏相关 UI，**不得**尝试调用 |
| `unknown` | 未声明、无法确定、或声明与实测不符 | 显示但置灰/标"未知"，调用 API 时接受 `3` |

**`unknown` ≠ `no`。** 这是整个模型的支点：

- 如果把 `unknown` 当 `no`，那么"还没验证过的新设备"会静默失去功能，
  且没人知道是"没有"还是"没做"；
- 如果把 `unknown` 当 `yes`，应用会调用不存在的硬件，得到失败，
  又回到"试了才知道"。

**规则的严格版本**：

> 应用层**严禁**把 `unknown` 解释为任何一种确定状态。
> 必须显式处理三态，否则视为应用缺陷。

对应现状的反例：`docs/13:20` 说亮度"映射待查"——这就是 `unknown`，
但现在应用把它当成了"没有"，于是不显示亮度项。

---

## 3. 枚举

Capability 是**封闭枚举**。新增需要改发行版代码（`04 §8` 的扩展流程）。

### 3.1 v1 枚举（11 项）

| Capability | 含义 | 判据（"有没有"的物理依据） |
|---|---|---|
| `wifi` | 有 WiFi 硬件 | 存在 WiFi 控制器 + 驱动可加载 |
| `bluetooth` | 有蓝牙硬件 | 存在 BT 传输（UART/SDIO/USB）+ 可加载 HCI |
| `touch` | 有触摸屏 | 存在 absolute 坐标输入设备 |
| `vibration` | 有震动马达 | 存在可写的震动控制节点 |
| `hdmi` | 有 HDMI 输出 | 存在 HDMI 输出通路 |
| `gpu` | 有 3D 加速 | 存在 GPU 设备节点 |
| `rtc` | 有 RTC | 存在 `/sys/class/rtc/rtc0` 或等价 |
| `usb_gadget` | 可作 USB 设备（adb/存储） | 存在 UDC |
| `usb_host` | 可作 USB 主机（外接手柄） | 存在 host 控制器 |
| `brightness` | 有可调背光 | 存在亮度控制通路（ioctl 或 sysfs） |
| `audio` | 有音频输出 | 存在声卡 + 可用的播放路径 |

**为什么是这 11 项而不是更多**：每一项都对应"应用要做分支决策"的粒度。
更细的（例如"有几个喇叭"）属于 Feature 或 DAL 的 `info` 输出，不是 Capability。

### 3.2 与 keyboardd 的 Capability 的关系（命名冲突处理）

`runtime/keyboardd/keyboardd.go:43-53` 已经定义了 `Capability` 类型：

```go
type Capability string
const (
    CapTouch            Capability = "Touch"
    CapDPad             Capability = "DPad"
    CapGamepad          Capability = "Gamepad"
    CapHardwareKeyboard Capability = "HardwareKeyboard"
)
```

这是**输入类别**，由 keyboard provider 声明，粒度是"这个 provider 支持什么输入方式"。
本文件的 Capability 是**整机硬件有无**。两者层次不同，但都叫 "Capability"。

**决定**：

1. 保留两套名字，但在**线上格式**上区分：
   - 整机：`baseosctl cap list` → `{"wifi":"yes", ...}`（小写下划线）
   - 输入类别：`baseosctl input list` → `kind=keyboard|power|gamepad|touch`
   - keyboardd 的 `Capabilities` 数组**不进入** `cap` 命名空间，它是 provider 的属性；
2. `touch` 在两套里都出现，但语义不同（整机有触摸屏 vs provider 支持触摸输入）。
   **映射规则**：`cap.touch == yes` 是 `keyboardd` 声明 `CapTouch` 的**必要不充分**条件——
   provider 还要真的能处理触摸事件。DAL 提供 `dal_input_list` 作为事实来源，
   由 keyboardd 自己决定声明哪些类别。
3. `04` 的枚举里**不包含** `DPad`/`Gamepad`/`HardwareKeyboard`：它们是输入类别，
   不是整机能力。手柄按键布局是 `board.json` 的 `input.buttons`（数据），
   不是 Capability。

这条决定写进 `README.md` 的术语表。

---

## 4. 来源（单一事实来源 + 运行时校验）

### 4.1 声明源：`board.json` + `soc.json`

```
soc.json      capabilities: {wifi: yes, bluetooth: yes, touch: unknown, ...}   ← SoC 级默认
board.json    capabilities: {wifi: yes, bluetooth: yes, touch: no, ...}       ← 板级覆盖
                              ↓ 深合并（板级胜）
构建时生成     /etc/pjos/caps.json
```

**规则**：`board.json` 的 `capabilities` **必须**包含枚举里全部 11 个键
（`02-bsp-boundary.md §5.3`）。这强制维护者在新增设备时逐项回答。

### 4.2 生成物：`/etc/pjos/caps.json`

```json
{
  "schema": "pjos.caps/1",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "generated_from": "board.json+soc.json",
  "caps": {
    "wifi": "yes", "bluetooth": "yes", "touch": "no", "vibration": "no",
    "hdmi": "yes", "gpu": "yes", "rtc": "yes",
    "usb_gadget": "yes", "usb_host": "yes",
    "brightness": "yes", "audio": "yes"
  }
}
```

生成时机：`build-rootfs.sh` 里与 `/etc/baseos-release` 同一处（现在 `:119-130`）。
**必须是构建产物，不是运行时探测**——理由：探测结果依赖内核状态，
而 Capability 描述的是**这台机器的硬件**，与当前内核是否加载了驱动无关。

### 4.3 运行时校验（`yes` 的自我修正）

声明是"应该有什么"，硬件是"实际有什么"。两者可能不符（驱动没加载、
硬件变体、固件刷新）。所以 `baseosctl cap` **在读取声明后做一次轻量校验**：

| Capability | 校验方式 | 不符时 |
|---|---|---|
| `wifi` | `dal_network_info` 的 `wifi_present` | 声明 `yes` 但实测 `no` → 输出 `unknown` + stderr 警告 |
| `bluetooth` | `dal_network_info` 的 `bt_present` | 同上 |
| `touch` | `dal_input_list` 是否含 `kind=touch` | 同上 |
| `vibration` | profile 的 `power.vibration` 节点可写 | 同上 |
| `hdmi` | `/sys/class/extcon/hdmi` 存在（若 profile 声明） | 同上 |
| `gpu` | `/dev/mali0` 或 profile 声明的 GPU 节点存在 | 同上 |
| `rtc` | `/sys/class/rtc/rtc0` 存在 | 同上 |
| `usb_gadget` | `/sys/class/udc/*` 非空 | 同上 |
| `usb_host` | `/sys/bus/usb/devices/usb*` 数量 | 同上 |
| `brightness` | `dal_display_brightness_get` 返回 0..255 | 同上 |
| `audio` | `dal_audio_info` 的 `card` 存在 | 同上 |

**降级方向只有一个：`yes` → `unknown`。绝不 `yes` → `no`。**

理由：`no` 是强断言（"这台机器绝对没有"），一次驱动加载失败不足以证明它。
而 `unknown` 是"我说它有，但现在验不了"——这正是事实。

`no` 保持 `no`：声明没有的东西，实测也不会有。若实测有，说明声明错了，
属于 profile 缺陷，用 `unknown` + 警告暴露出来（而不是悄悄变成 `yes`，
因为那会让 UI 突然多出一项，且没人知道为什么）。

### 4.4 校验的代价与开关

校验需要读节点，在 `baseosctl cap list` 上会花几毫秒。因此：

- `baseosctl cap list` 默认**只读声明**（快，用于 UI 启动）；
- `baseosctl cap list --verify` 执行校验（用于诊断与测试）；
- `baseosctl cap get <name>` 默认**校验**（单次查询，代价可接受）。

这条不对称是刻意的：UI 启动要快，单点查询要准。

---

## 5. `yes` 的取证规则（防止把"想要"写成"有"）

`01-audit.md` 的一个教训是：文档写了 `docs/14:21` 要求的字段，schema 里没有，
于是文档自己发明了字段。Capability 更容易犯这个错——写 `yes` 很便宜。

**规则**：`capabilities.<X> == "yes"` 必须能指向一条**实测证据**：

| 证据类型 | 形式 | 存放 |
|---|---|---|
| 真机验证 | `validate-on-device.sh` 的 PASS 记录 | `docs/evidence/` |
| 节点存在性 | `soc.json`/`board.json` 里声明的节点 + 一次 fake-tree 测试 | `bsp/boards/<id>/tests/` |
| 厂商固件事实 | 厂商 rootfs 里存在该驱动/固件 | `source.json` 的 harvest 记录 |

**H700 当前的实际情况**（诚实标注，这是本文件的基线）：

| Capability | 11 台 H700 的取值 | 证据 |
|---|---|---|
| `wifi` | `rg28xx` = `no`；其余 = `yes` | `devices.json:13`（rg28xx false）、`:25` 等；`validate-on-device.sh:72-76` |
| `bluetooth` | `rg28xx` = `no`；其余 = `yes` | `devices.json:14`、`:26` 等 |
| `touch` | **`unknown`** | 无任何证据表明 H700 掌机有触摸屏；`keyboardd` 的 `CapTouch` 是 provider 属性。**待用户拍板 D1** |
| `vibration` | **`unknown`** | `axp2202-battery/moto` 存在且可写（`validate-on-device.sh:70`），但"可写 moto 节点"≠"机器上有马达"；**待实测** |
| `hdmi` | `yes` | `validate-on-device.sh:56`（extcon/hdmi）、`rcS:66-71`（dispdbg 切 HDMI） |
| `gpu` | `yes` | `validate-on-device.sh:50-51`（mali_kbase + `/dev/mali0`） |
| `rtc` | `yes` | `overlay/usr/sbin/baseos-charger:19`（`rtc0/since_epoch`） |
| `usb_gadget` | `yes` | `validate-on-device.sh:97-98`（g1/UDC 绑定） |
| `usb_host` | `yes` | `validate-on-device.sh:88-89`（六个 root hub） |
| `brightness` | `yes` | `/dev/disp` ioctl（`src/charger-wait.c:14-16`）；**注意**无 `/sys/class/backlight` |
| `audio` | `yes` | `validate-on-device.sh:64`（audiocodec） |

`touch` 与 `vibration` 明确保持 `unknown`：**没有证据就不要写 `yes`**。
这不是保守，这是本模型的全部意义。

---

## 6. 缺失时的降级行为

分三层，每层的行为不同。**这一节是"降级"的定义，不是"容错"**——
区别在于：降级是**规范化的、可预期的、有 UI 表达的**；容错是"出错了继续跑"。

### 6.1 BaseOS Services 层

| Capability | `no` | `unknown` |
|---|---|---|
| `wifi` | 不加载 WiFi 驱动，不启动 wpa_supplicant，`dal_network_wifi_up` 返回 4 | 尝试加载；失败返回 3，写一条 boot log |
| `bluetooth` | 不加载 BT 栈，`dal_network_bt_up` 返回 4 | 同 wifi |
| `brightness` | `dal_display_brightness_set` 返回 4；`baseos-charger` 不调亮度 | 尝试 ioctl；失败返回 3 |
| `audio` | 不启动 `h700-speaker-amp-load`；不播 startup sound | 尝试；失败记 log |
| `vibration` | `dal_led_vibrate` 返回 4 | 尝试写 moto；失败返回 3 |
| `hdmi` | 不挂 debugfs 的 dispdbg（省一次 mount） | 挂上；切换失败返回 3 |
| `rtc` | 跳过 `hwclock -u -s`（`rcS:168`），时钟从 epoch 开始 | 同 rtc=no，但记 log |
| `usb_gadget` | 不启动 `usb-gadget-adb` | 尝试；失败静默（现有行为，`usb-gadget-adb:8-11`） |
| `usb_host` | 不加载 `late_usb` 模块 | 尝试 |
| `gpu` | 不加载 GPU 模块；`frontend-session` 跳过 `/dev/mali0` 等待 | 尝试加载并等待 |

### 6.2 Runtime 层

Runtime 不读 Capability（它读 DAL）。唯一例外是 `keyboardd` 需要知道
有没有触摸输入来决定是否声明 `CapTouch`：

```
cap.touch == no      → keyboardd 不声明 CapTouch，强制 DPad/Gamepad 模式
cap.touch == unknown → keyboardd 以 dal_input_list 的实际结果为准（不猜）
cap.touch == yes     → 仍以 dal_input_list 为准（声明不是证据）
```

**注意最后一行**：即使是 `yes`，Runtime 也要用 DAL 的事实。Capability 决定
"要不要显示这一项"，DAL 决定"能不能现在用"。

### 6.3 Application 层（PocketJS）

| Capability | `no` | `unknown` |
|---|---|---|
| `wifi` | 隐藏 WiFi 设置页、状态栏不显示 WiFi 图标 | 显示设置页，标"未知"；点击时提示"这台设备未验证 WiFi" |
| `bluetooth` | 隐藏蓝牙页 | 同上 |
| `touch` | 不启用触摸手势 | 同上 |
| `vibration` | 设置里无"震动反馈" | 同上 |
| `hdmi` | 无"输出到电视" | 同上 |
| `brightness` | 设置里无亮度行 | 显示亮度行但置灰 |
| `audio` | 无音量控制 | 显示但置灰 |

**硬规则**：应用**不得**因为 `unknown` 就崩溃或静默隐藏。必须二者之一：
显示但置灰（带解释），或不显示但在"关于本机"里列出。

---

## 7. 查询接口

### 7.1 `baseosctl`（正式接口，见 `06`）

```sh
baseosctl cap list                  # 全部，key=value
baseosctl cap list --json           # JSON
baseosctl cap list --verify          # 带运行时校验
baseosctl cap get wifi              # 输出 yes|no|unknown，退出码 0
baseosctl cap has wifi              # 0=yes 1=no 2=unknown（脚本友好）
```

**`cap has` 的三态退出码是刻意的**：脚本里 `if baseosctl cap has wifi; then`
在 `unknown` 时会走 else 分支——这正是期望（不确定就不要走 yes 路径），
但退出码 `2` 让调用方仍能区分"确定没有"与"不知道"。

### 7.2 直接读文件（允许，但仅限 Runtime）

Runtime 可以读 `/etc/pjos/caps.json`（构建产物，只读）。理由：Runtime 启动
在 `baseosctl` 可用之前（`rcS` 阶段），不能依赖 fork 一个进程。

Application **不得**读该文件：它必须走 `baseosctl`，以便未来把实现从
"读 JSON"换成"问 baseosd"时应用不受影响。

### 7.3 PocketJS 侧的最小集成

```ts
// 启动时一次
const caps = await baseosctlJson("cap", "list");
// 三态显式处理
type Tri = "yes" | "no" | "unknown";
function visible(cap: Tri) { return cap !== "no"; }
function enabled(cap: Tri) { return cap === "yes"; }
```

**禁止**：`if (caps.wifi)` —— 三态是字符串，`"no"` 是真值。
这条要写进 PocketJS 的 lint 或代码评审清单。

---

## 8. 扩展流程（新增一个 Capability）

新增 Capability 是**发行版代码改动**，不是 BSP 改动。流程：

1. 在 `bsp/schema/board.schema.json` 的 `capabilities` 枚举里加键；
2. 在 `03-dal.md` 里加对应的 `dal_*` 查询（或复用现有的）；
3. 更新全部 `bsp/boards/*/board.json`（**这是唯一允许批量改已有板的场景**，
   且改动是纯新增键，所有板的行为不变）；
4. 在 `06-baseosctl.md` 的 `cap` schema 里加键；
5. 更新 `docs/bsp-v2/04-capability.md` 的枚举表。

**为什么允许批量改已有板**：因为这是**扩展接口**，不是"修改已有设备行为"。
判据见 `02-bsp-boundary.md §8.3`：所有已有板的行为逐字节不变。

**不新增 Capability 的情形**（避免枚举膨胀）：

| 想表达的 | 正确做法 |
|---|---|
| "有 2 个喇叭" | `dal_audio_info` 的额外字段 |
| "支持 5GHz WiFi" | Feature `wifi_5ghz`（`05`） |
| "有 2 个 SD 槽" | `dal_storage_info` 的 `tf2_present` |
| "支持触摸 + 手柄同时" | 输入类别，`dal_input_list` |

---

## 9. 版本兼容

`caps.json` 带 `"schema": "pjos.caps/1"`。规则：

| 变更 | schema 版本 | 消费方行为 |
|---|---|---|
| 新增 Capability 键 | 保持 `1` | 旧消费方忽略未知键 |
| 删除键 / 改语义 | `2` | 旧消费方必须拒绝（`baseosctl` 报 `unsupported schema`） |
| 新增取值（例如 `partial`） | `2` | 同上 |

**为什么新增键不升版本**：Capability 是"有没有"，新增一项不会改变已有项的答案。
升版本会让所有旧应用失效，代价与收益不成比例。

**为什么 `baseosctl` 必须在 schema 不匹配时硬失败**：静默忽略会让
"应用问了一个新能力、系统不认识、返回空"变成静默错误——这正是
`01-audit.md` 反复出现的问题模式。

---

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 维护者为省事把全部 Capability 写 `yes` | 高（模型失去意义） | §5 的取证规则 + PR 评审检查"新 `yes` 是否带证据" |
| 运行时校验让 `cap list` 变慢 | 低 | §4.4 的默认不校验 |
| `unknown` 在 UI 上被当成 `no`（实现偷懒） | 中 | §7.3 的显式三态类型 + 评审清单 |
| 三态字符串在 JS 里是真值，`if (caps.x)` 恒真 | 中 | §7.3 明确禁止；PocketJS 侧加 lint |
| 校验的降级方向被误用（把 `no` 升级成 `yes`） | 中 | §4.3 硬规定单向 |
| 11 项枚举不够用，频繁扩展 | 中 | §8 的"不该新增的情形"清单先排除误用 |

---

## 11. 验收标准

| # | 标准 | 判据 |
|---|---|---|
| C1 | 每条 `board.json` 显式含 11 个键 | `tools/bsp_validate.py` 检查键集合相等 |
| C2 | `/etc/pjos/caps.json` 是构建产物 | 镜像里该文件的 mtime = 构建时间，不是运行时 |
| C3 | `cap has` 三态退出码正确 | fake profile 里分别写 yes/no/unknown，断言退出码 0/1/2 |
| C4 | `yes` 实测不符时降为 `unknown` | 删除 fake 树的 wlan0，`cap get wifi --verify` 输出 `unknown` 且退出 0 |
| C5 | `no` 不被升级 | 同上，声明 `no` 时即使节点存在也输出 `no` |
| C6 | Runtime 不依赖 `baseosctl` 进程 | `keyboardd` 启动路径上 `strace` 无 `execve("/usr/sbin/baseosctl")`（或代码审查确认） |
| C7 | 应用侧无 `if (caps.x)` 式真值判断 | PocketJS 仓库 lint（跨仓库，本阶段只定义规则） |
