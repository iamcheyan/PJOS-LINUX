# 06 — `baseosctl` CLI 规格

> `baseosctl` 是 PocketOS **唯一的正式系统接口**。
> 应用层（PocketJS）只能通过它访问硬件能力；不得直接读 `/sys`、`/proc`、`/dev`。
>
> 本文件定义：子命令、输出 schema、退出码、失败语义、版本兼容。
> 解决 `01-audit.md` P1-1（应用层探测硬件）、P1-2（无能力查询）、
> P1-3（无 Feature 查询）。

---

## 1. 为什么它是唯一的正式接口

现状有 **6 类**"应用访问系统的途径"，彼此不一致：

| 途径 | 证据 | 问题 |
|---|---|---|
| 直接读 `/sys` | `docs/13-pocketjs-on-baseos.md:20`（`/sys/class/disp/disp/attr`） | 路径是 SoC 事实，换设备就变 |
| 直接读 `/proc` | `docs/13:16`（`/proc/asound/cards` 隐含） | 同上 |
| 直接开 `/dev` | `docs/13:15`（`/dev/fb0`、`/dev/input/eventN`） | 同上 |
| 调 `amixer` | `docs/13:57`（compat shim 映射到 amixer） | 控制名是板级事实 |
| 调 `wpa_cli` | `docs/13:57` | 同上 |
| 调 `systemctl` shim | `overlay/usr/sbin/systemctl`（87 行，只为 NextUI 而存在） | 绑定单一前端 |

`baseosctl` 把 6 类收敛为 1 类。**这不是新增抽象，是删除 6 个私有契约。**

---

## 2. 全局约定

### 2.1 输出格式

| 规则 | 说明 |
|---|---|
| 默认 `key=value`，一行一项 | `key=value` 便于 `grep`/`cut`/`awk` |
| `--json` 输出单个 JSON 对象 | 便于应用解析 |
| **禁止人类散文** | 没有 "Battery is at 87%" 这种句子 |
| 数值不带单位后缀 | `capacity=87` 不是 `capacity=87%`；单位进键名（`voltage_uv`） |
| 布尔用 `yes`/`no`，不用 `true`/`false` | 与 Capability/Feature 三态同一套词汇（`04 §2`） |
| 三态用 `yes`/`no`/`unknown` | 同上 |
| 时间用 Unix epoch 秒 | `alarm_epoch=1730000000` |
| 路径只在 `display node` 一个子命令里出现 | `03 §3.3` 的显式例外 |
| stdout 只放数据，stderr 只放原因 | 便于 `2>/dev/null` |
| 一行一个"记录"，多记录用重复键 | `dal_input_list` 风格：`node=... name=...` |

### 2.2 退出码（全局统一）

| 码 | 含义 | 何时用 |
|---|---|---|
| `0` | 成功 | 查询有结果；写操作已完成 |
| `1` | 失败 | 操作被尝试但失败（权限、IO、超时） |
| `2` | 用法错误 | 未知子命令、参数个数/类型错 |
| `3` | 未知 | 无法确定（对应三态的 `unknown`） |
| `4` | 不支持 | profile 明确声明 `no`，或该板无此硬件 |
| `5` | 前置条件不满足 | 例如 `power suspend` 时 USB 存储模式激活 |
| `6` | schema 不匹配 | `caps.json`/`features.json` 的 schema 不认识 |

**`3` 与 `4` 必须区分**：这是 `04 §2` 三态模型在 CLI 上的体现。
脚本里：

```sh
baseosctl cap has wifi
case $? in
    0) use_wifi ;;
    1) skip_wifi ;;           # 确定没有
    2) ask_user_or_skip ;;    # 未知
esac
```

（`cap has` 的 0/1/2 是**三态专用**，见 §4.1；其余子命令用上表的 0–6。）

### 2.3 参数与通用选项

```
baseosctl [--json] [--quiet] [--timeout SEC] <group> <verb> [args...]

--json        输出 JSON 而非 key=value
--quiet       抑制 stderr 的非致命警告（不抑制错误）
--timeout N   给可能阻塞的操作设上界（秒）；默认各子命令自带合理值
--version     打印 baseosctl 版本与 schema 版本
```

### 2.4 幂等与并发

- 所有写操作幂等：`display set-brightness 100` 连调两次结果相同；
- 并发安全由 DAL 保证（读-改-写节点时不做跨调用事务）；
- `baseosctl` **不加全局锁**：加锁会让一个卡住的调用拖死所有查询。

---

## 3. 子命令总表

| 组 | 子命令 | 说明 |
|---|---|---|
| `cap` | `list` `get` `has` | Capability（`04`） |
| `feature` | `list` `get` `has` `bitmask` | Feature（`05`） |
| `display` | `info` `node` `set-brightness` `get-brightness` `blank` `output` | `03 §3` |
| `audio` | `info` `get-volume` `set-volume` `mute` `cards` | `03 §4` |
| `power` | `battery` `charger` `supplies` `boot-reason` `led` `suspend` `poweroff` `reboot` `alarm` | `03 §6` |
| `network` | `info` `wifi-up` `wifi-down` `wifi-scan` `bt-up` `bt-down` `mdns` | `03 §7` |
| `input` | `list` `node` `key-state` `menu-held` | `03 §5` |
| `storage` | `info` `roles` `role` `expand` `usb-mode` `card-mount` | `03 §8` |
| `led` | `list` `set` `vibrate` | `03 §9` |
| `version` | — | 系统版本、board、soc、schema 版本 |

`version` 是**必查项**：应用启动时先问它，确认自己能理解这台机器的输出。

---

## 4. 详细规格

### 4.1 `cap`

```sh
baseosctl cap list [--verify]
baseosctl cap get <name> [--verify]
baseosctl cap has <name>
```

**`cap list`**（key=value）：

```
schema=pjos.caps/1
board=rg34xx
soc=allwinner/h700
wifi=yes
bluetooth=yes
touch=no
vibration=unknown
hdmi=yes
gpu=yes
rtc=yes
usb_gadget=yes
usb_host=yes
brightness=yes
audio=yes
```

**`cap list --json`**：

```json
{
  "schema": "pjos.caps/1",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "verified": false,
  "caps": {
    "wifi": "yes", "bluetooth": "yes", "touch": "no", "vibration": "unknown",
    "hdmi": "yes", "gpu": "yes", "rtc": "yes",
    "usb_gadget": "yes", "usb_host": "yes",
    "brightness": "yes", "audio": "yes"
  }
}
```

**`cap get wifi`**：stdout `yes`；退出码 `0`（无论值是什么——查询本身成功）。
**`cap has wifi`**：无输出；退出码 `0`=yes `1`=no `2`=unknown。
（`has` 是脚本友好形式，与 `get` 的"查询成功"语义不同。）

**失败语义**：
- `caps.json` 缺失 → 退出 `3`，stderr `caps: no /etc/pjos/caps.json`（**不是** 1：
  缺文件意味着"这台机器没告诉我它有什么"，是未知而非失败）；
- schema 不认识 → 退出 `6`；
- 未知 capability 名 → 退出 `2`，stderr 列出合法名。

### 4.2 `feature`

```sh
baseosctl feature list [--verify]
baseosctl feature get <name> [--verify]
baseosctl feature has <name>
baseosctl feature bitmask
```

`feature list` 输出结构同 `cap list`，`schema=pjos.features/1`。

`feature bitmask`：

```
bitmask=1439
bitmask_hex=0x8000059f
bitmask_version=1
```

位序见 `05 §6.2`。`bitmask_version` 必须检查（`05 §8.3`）。

### 4.3 `display`

```sh
baseosctl display info
baseosctl display node              # 唯一输出设备路径的子命令
baseosctl display get-brightness    # 0..255
baseosctl display set-brightness N
baseosctl display blank on|off
baseosctl display output list
baseosctl display output set <name>
```

`display info`：

```
backend=fbdev
width=720
height=480
bpp=32
rotation_ccw=0
logical_width=720
logical_height=480
vsync=timer
brightness=180
brightness_min=0
brightness_max=255
brightness_control=ioctl
outputs=lcd
```

`display node`：stdout `/dev/fb0`，退出 0。

`display output list`：

```
output=lcd connected=yes active=yes
output=hdmi connected=no active=no
```

**失败语义**：
- `set-brightness` 超出 `[min,max]` → 退出 `2`（用法错误，不截断）；
- 无亮度控制 → 退出 `4`；
- 亮度控制存在但写失败 → 退出 `1` + stderr 原因；
- `display output set hdmi` 当 `cap.hdmi == no` → 退出 `4`。

### 4.4 `audio`

```sh
baseosctl audio info
baseosctl audio get-volume          # 0..100
baseosctl audio set-volume 0..100
baseosctl audio mute on|off
baseosctl audio cards
```

`audio info`：

```
card=0
card_name=audiocodec
mixer=amixer
volume_control=digital volume
volume_min=0
volume_max=63
volume=63
volume_raw=63
mute_control=none
route_controls=OutputL Mixer DACL,OutputR Mixer DACR,LINEOUT,SPK
amp_module=h700_speaker_amp
amp_loaded=yes
```

`volume` 是归一化 0..100，`volume_raw` 是原始量程（`03 §4.2`）。

**失败语义**：
- 无声卡 → `info` 退出 `3`（未知）或 `4`（声明 `audio=no`）；
- `set-volume` 无声卡 → 退出 `4`；
- mixer 存在但控制名不匹配 → 退出 `1` + stderr 列出实际控制名（诊断关键）。

### 4.5 `power`

```sh
baseosctl power battery
baseosctl power charger
baseosctl power supplies
baseosctl power boot-reason
baseosctl power led on|off|auto
baseosctl power suspend
baseosctl power poweroff
baseosctl power reboot
baseosctl power alarm get
baseosctl power alarm set <epoch>
```

`power battery`：

```
present=yes
capacity=87
status=Discharging
voltage_uv=3980000
health=Good
```

`power boot-reason`：

```
reason=normal
source=pmic
```

`source` 说明用了哪条路径（`pmic` / `cmdline` / `default`），便于诊断
（对应 `03 §6.2` 的降级顺序）。

`power suspend`：成功时**进程返回 0 并已恢复**（不是"已进入睡眠"）。
这意味着调用方在 `suspend` 返回后才继续——语义清晰，代价是调用方要等。

**失败语义**：
- `power poweroff` 在 USB 存储模式激活时 → 退出 `5`（`src/axp-off.c:182`
  现在拒绝在这种情况下切电源，这是**正确行为**，CLI 要如实表达）；
- `power alarm set` 当 `feature.rtc_alarm != yes` → 退出 `4`；
- `power suspend` 当 `feature.suspend != yes` → 退出 `4`。

### 4.6 `network`

```sh
baseosctl network info
baseosctl network wifi-up
baseosctl network wifi-down
baseosctl network wifi-scan
baseosctl network bt-up
baseosctl network bt-down
baseosctl network mdns refresh
```

`network info`：

```
wifi_present=yes
wifi_iface=wlan0
wifi_state=up
wifi_ip=203.0.113.42
bt_present=yes
bt_state=up
bt_hci=hci0
```

`network wifi-scan`（每行一个网络）：

```
ssid=MyAP signal=72 security=wpa2
```

**失败语义**：
- `wifi-up` 当 `cap.wifi == no` → 退出 `4`；
- `wifi-up` 加载失败 → 退出 `1`，stderr 说明是驱动还是时序
  （H700 的慢电台路径要能区分，见 `03 §7.2`）；
- `wifi-scan` 无接口 → 退出 `3`。

### 4.7 `input`

```sh
baseosctl input list
baseosctl input node <kind>
baseosctl input key-state <kind> <KEY>
baseosctl input menu-held
```

`input list`：

```
node=/dev/input/event0 name=axp2202-pek kind=power
node=/dev/input/event1 name=ANBERNIC-keys kind=keyboard
node=/dev/input/event2 name=... kind=gamepad
```

`input menu-held`：stdout `held=yes|no|unknown`；退出 0。
（对应 `03 §5.2`：H700 走 GPIO 路径，且该事实来自 `board.json`。）

**注意**：`input node` 输出设备路径，与 `display node` 同理——
Runtime 必须能 `open()` 它。这是第二个显式例外，规则同 `03 §3.3`：
**只能通过本命令获得，不得自己拼路径或探测。**

### 4.8 `storage`

```sh
baseosctl storage info
baseosctl storage roles
baseosctl storage role <boot|rootfs|data|primary|tf2>
baseosctl storage expand
baseosctl storage usb-mode prepare|status
baseosctl storage card-mount
```

`storage info`：

```
boot_disk=/dev/mmcblk0
layout=baseos-ab-v1
rootfs_mounted_ro=no
data_free_mb=118
primary_free_mb=27000
tf2_present=no
usb_mode=off
```

`storage role rootfs`：输出**设备路径**（例如 `/dev/mmcblk0p5`），
但语义是"当前活动的 A/B 槽位"，不是固定分区号（`03 §8.2`）。

`storage expand` 退出码（沿用 `overlay/usr/sbin/expand-storage:33-37` 的语义）：

| 退出 | 含义 |
|---|---|
| `0` | 本次扩容成功 |
| `1` | 已经满了（幂等，**不是错误**） |
| `2` | 错误 |

**这是一个刻意的不一致**：`storage expand` 用 `0/1/2` 表达三种业务结果，
而不是全局的 `0/1/2/3/4`。理由：`expand-storage` 已在生产使用该约定
（`gptgrow` 的退出码语义，`tools/gptgrow.c:6-8`），改变它会破坏
`build-rootfs.sh` 与真机上的既有行为。CLI 在 `--json` 输出里同时给
`"changed": true|false`，让应用不必依赖退出码。

### 4.9 `led`

```sh
baseosctl led list
baseosctl led set <kind> on|off|auto
baseosctl led vibrate <ms>
```

### 4.10 `version`

```sh
baseosctl version
```

```
baseosctl_version=1
schema_caps=pjos.caps/1
schema_features=pjos.features/1
schema_board=pjos.board/1
schema_soc=pjos.soc/1
baseos_version=1.5.2
baseos_build=dc99d57
board=rg34xx
soc=allwinner/h700
```

**应用启动必须先调这个**：schema 版本不匹配时立即降级，
而不是等到某条查询返回 `6`。

---

## 5. 失败语义总则

### 5.1 "未知"不是"失败"

这是本 CLI 最重要的设计决定：

| 情形 | 退出码 | 理由 |
|---|---|---|
| 文件缺失（`caps.json`） | `3` | 系统没告诉我，不是它坏了 |
| 节点不存在 | `3` | 可能是驱动没加载 |
| profile 声明 `no` | `4` | 确定没有 |
| 节点存在但读失败 | `1` | 尝试了，失败了 |
| 参数错 | `2` | 调用方错 |

**为什么区分**：`04 §2` 的三态模型要求 `unknown ≠ no`。如果 CLI 把两者
都返回 `1`，应用无法区分"这台机器没有 WiFi"和"WiFi 驱动没加载"，
就会退回"试试看"——正是本设计要消除的。

### 5.2 部分失败

多值查询（`supplies`、`input list`、`output list`）中某一项读失败：

- 该行**仍然输出**，值写 `unknown`；
- 退出码 `0`（查询整体成功）；
- stderr 一行警告。

理由：让应用看到"有 3 个电源，其中 1 个读不出来"，比"整个查询失败"有用。

### 5.3 阻塞操作的上界

| 操作 | 默认上界 | 超时后 |
|---|---|---|
| `network wifi-up` | 8s（H700 的两次尝试，`rcS:237,244` 的 8/40 次 0.25s 等待） | 退出 `1`，stderr `wifi: no wlan0 after 8s` |
| `power suspend` | 无上界（内核决定） | — |
| `storage expand` | 60s | 退出 `1` |
| `storage usb-mode prepare` | 2s（`usb-storage-mode:44-47` 的 10×0.1s 等待） | 退出 `1` |

`--timeout N` 可覆盖。

### 5.4 绝不静默

任何非 0 退出**必须**在 stderr 有一行原因。禁止：

```sh
# 反例：现状里大量存在
[ -x /usr/sbin/h700-speaker-amp-load ] && /usr/sbin/h700-speaker-amp-load >/run/log 2>&1
```

（`overlay/etc/init.d/rcS:380-381`：失败被吞进日志文件，调用方不知道。）

`baseosctl` 的规则：写操作失败 → stderr 一行 + 非 0 退出；
调用方可以选择忽略，但**必须显式忽略**。

---

## 6. JSON schema 示例

### 6.1 `cap list --json`

```json
{
  "$schema": "https://pjos.local/schema/caps-1.json",
  "schema": "pjos.caps/1",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "verified": false,
  "caps": {
    "wifi": "yes",
    "bluetooth": "yes",
    "touch": "no",
    "vibration": "unknown",
    "hdmi": "yes",
    "gpu": "yes",
    "rtc": "yes",
    "usb_gadget": "yes",
    "usb_host": "yes",
    "brightness": "yes",
    "audio": "yes"
  }
}
```

### 6.2 `feature list --json`

```json
{
  "schema": "pjos.features/1",
  "board": "rg34xx",
  "soc": "allwinner/h700",
  "verified": false,
  "bitmask_version": 1,
  "features": {
    "bt_sink": "unknown",
    "bt_source": "unknown",
    "audio_hw_volume": "unknown",
    "audio_hw_mute": "unknown",
    "display_rotation": "unknown",
    "display_output_switch": "yes",
    "suspend": "yes",
    "rtc_alarm": "unknown",
    "usb_storage_export": "yes",
    "usb_adb": "yes",
    "usb_host_input": "yes",
    "wifi_ap": "unknown"
  }
}
```

### 6.3 `display info --json`

```json
{
  "schema": "pjos.display/1",
  "backend": "fbdev",
  "width": 720, "height": 480, "bpp": 32,
  "rotation_ccw": 0,
  "logical_width": 720, "logical_height": 480,
  "vsync": "timer",
  "brightness": 180, "brightness_min": 0, "brightness_max": 255,
  "brightness_control": "ioctl",
  "outputs": [
    { "name": "lcd", "connected": true, "active": true },
    { "name": "hdmi", "connected": false, "active": false }
  ]
}
```

### 6.4 `power battery --json`

```json
{
  "schema": "pjos.power/1",
  "battery": { "present": true, "capacity": 87, "status": "Discharging",
               "voltage_uv": 3980000, "health": "Good" }
}
```

### 6.5 错误输出（`--json`）

```json
{
  "schema": "pjos.error/1",
  "error": "unsupported",
  "code": 4,
  "message": "feature rtc_alarm is 'unknown' on this board",
  "context": { "group": "power", "verb": "alarm" }
}
```

`code` 与退出码一致；`error` 是 `usage|failed|unknown|unsupported|precondition|schema` 之一。

---

## 7. 版本兼容

### 7.1 三处版本

| 版本 | 位置 | 变更规则 |
|---|---|---|
| `baseosctl_version` | `version` 子命令 | 新增子命令/新增键不升；改语义/删子命令升 |
| `schema_caps` / `schema_features` | 同上 | 见 `04 §9`、`05 §8` |
| `schema_board` / `schema_soc` | 同上 | 见 `02 §5` |

### 7.2 兼容矩阵

| 变更 | 升 `baseosctl_version` | 旧应用是否仍工作 |
|---|---|---|
| 新增子命令 | 否 | 是 |
| 新增输出键 | 否 | 是（忽略未知键） |
| 新增 JSON 字段 | 否 | 是 |
| 改键名 | **是** | 否（必须） |
| 改键的语义（单位、量程） | **是** | 否 |
| 删除子命令 | **是** | 否 |
| 改退出码语义 | **是** | 否 |

### 7.3 应用的启动契约

```ts
const v = await baseosctl("version");
if (v.baseosctl_version < 1) throw new Error("baseosctl too old");
if (v.schema_caps !== "pjos.caps/1") throw new Error("caps schema mismatch");
if (v.schema_features !== "pjos.features/1") throw new Error("features schema mismatch");
```

**禁止**"猜一个兼容版本继续跑"。理由同 `04 §9`：静默忽略是
`01-audit.md` 里所有问题的共同形态。

---

## 8. 与现有兼容层的替换关系

`overlay/usr/sbin/systemctl`（87 行）现在只为 NextUI 服务
（`systemctl:3`："Covers exactly the calls NextUI's h700 scripts make"）。
它的三个职责与 `baseosctl` 的对应：

| systemctl shim 职责 | 现状实现 | `baseosctl` 对应 |
|---|---|---|
| `is-active bluetooth` | `pidof bluetoothd`（`:56`） | `network info` 的 `bt_state` |
| `start/restart bluetooth` | 起 dbus + bluetoothd（`:60-76`） | `network bt-up` |
| `stop wpa_supplicant` | 杀进程并等待（`:34-51`） | `network wifi-down` |

**迁移策略**：`systemctl` 保留（NextUI 的脚本会调它），但改为
**薄翻译层**：内部调 `baseosctl`。这样 shim 不再拥有语义，
只拥有"名字翻译"。

`docs/13-pocketjs-on-baseos.md:57` 描述的 compat shim 同理：
`LEVEL`/`STATE`/`CONTROL`/`SERVICE` 全部改为调 `baseosctl`，
失败时**不**回落旧路径（回落会让"没有"变成"猜"）。

**待用户拍板 D4**：是否在 PocketJS 侧保留回落（见 `README.md`）。

---

## 9. 实现形态（第一阶段不实现，只定约束）

| 项 | 约束 | 理由 |
|---|---|---|
| 语言 | POSIX sh（首选）或静态 C（若 sh 太慢） | 与现有 overlay 一致；无运行时依赖 |
| 依赖 | busybox applet + `/usr/lib/baseos/dal.sh` | 不引入新依赖 |
| 大小 | < 20 KB | 启动路径上被调用 |
| 冷启动 | < 50 ms（`display info`） | UI 启动会调 |
| 位置 | `/usr/sbin/baseosctl` | 与现有 `baseos-*` 一致 |
| 可测性 | 全部路径可用 `BASEOS_SYS_ROOT` 指向 fake 树 | 沿用 `usb-gadget-adb:36-54` 的既有模式 |

**为什么首选 sh**：`baseos-diag`（666 行）、`baseos-update`（555 行）已经证明
busybox sh 能承载这个复杂度；引入第二个语言会让"谁能读这个代码"变成两个答案。

---

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| sh 实现下每次调用 fork 多个子进程，冷启动 > 50ms | 中 | 热点路径（`display info`、`cap list`）预渲染为静态变量文件，`dal_init` 只 `source` |
| 退出码 3/4 的区分被实现偷懒合并 | 高（模型失效） | `04 §11 C3`、`05 §11 F4` 的测试断言 |
| `--json` 与 key=value 两条路径的字段漂移 | 中 | 单一数据源：先生成内部记录，再分别渲染两种格式 |
| 新增子命令不加 `baseosctl_version` 判断 | 低 | §7.2 的矩阵 |
| 应用仍然直接读 `/sys`（绕过 baseosctl） | 高 | PocketJS 侧 lint（跨仓库）；`06` 定义规则，不实现 |
| `storage expand` 的 0/1/2 与全局码冲突 | 低 | §4.8 已显式记录为例外；`--json` 提供 `changed` |

---

## 11. 验收标准

| # | 标准 | 判据 |
|---|---|---|
| S1 | 10 个组全部存在 | `for g in cap feature display audio power network input storage led version; do baseosctl $g --help; done` 全部退出 0/2 |
| S2 | 无人类散文 | 对每个子命令的 stdout 跑 `grep -qE ' (is|are|the|has|will) '` 应为空 |
| S3 | 三态退出码正确 | `cap has` 在 yes/no/unknown 上分别退出 0/1/2 |
| S4 | `--json` 输出可被 `python3 -m json.tool` 解析 | 每个子命令都跑一次 |
| S5 | 所有写操作幂等 | 每个写操作连跑两次，第二次退出 0 且状态相同 |
| S6 | 失败必有 stderr 原因 | 构造 5 种失败，断言 stderr 非空 |
| S7 | fake 树可测 | 无真机时 `BASEOS_SYS_ROOT=<tmpfs>` 下全部查询返回 0/3/4 |
| S8 | `version` 与 schema 文件一致 | `baseosctl version` 的 schema 值 == `/etc/pjos/*.json` 的 `schema` |
| S9 | `systemctl` shim 改为调 `baseosctl` 后行为不变 | `tests/test-systemctl-wifi.sh` 仍通过 |
