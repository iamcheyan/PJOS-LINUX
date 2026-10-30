# 03 — DAL 边界与接口定义

> DAL（Device Abstraction Layer）把 BSP 声明的"设备节点"翻译成"稳定语义"。
> 它解决 `01-audit.md` P0-5（分区号/节点字面量散落）、P1-1（应用层探测硬件）、
> P1-3（能力与行为混淆）。
>
> 本文件定义 7 个子系统的**接口签名**与**映射表**。接口是契约：
> 上层（BaseOS Services / Runtime / Application）只允许调用这里的函数名，
> 不允许出现任何 `/sys`、`/proc`、`/dev` 路径。

---

## 1. DAL 的定位与形态

### 1.1 它在哪一层

```
Application (PocketJS)      ← 只见 baseosctl JSON
        ↓
Runtime (keyboardd, ...)    ← 只见 DAL 函数 或 baseosctl
        ↓
BaseOS Services (rcS, ...)  ← 只见 DAL 函数
        ↓
DAL                         ← 只见 board.json / soc.json 里的 nodes
        ↓
BSP (bsp/.../soc.json)      ← 只见真实节点路径
        ↓
Hardware
```

**DAL 是唯一允许出现 `/sys`、`/proc`、`/dev` 的发行版层**（BSP 的 `soc.json`
里也允许，因为那是"事实声明"）。

### 1.2 形态：库，不是守护进程（v1）

**决定**：DAL v1 是 **POSIX sh 函数库 + 少量静态 C 辅助程序**，不是常驻守护进程。

理由（证据驱动）：

1. 现有 39 个 overlay 文件里 23 个已经在用 sh 直接读节点（§6 的映射表），
   改成"调库函数"是**局部替换**，风险最低；
2. 常驻进程引入新的失败模式：它挂了，整机失去硬件访问。当前设计里
   `frontend-session` 是 `::respawn:`（`overlay/etc/inittab:4`），
   再来一个常驻进程会让"哪个进程负责硬件"变成两个答案；
3. 需要一个**跨进程**能力的只有 Application，而它走 `baseosctl`（`06`）——
   一次性命令，不需要守护进程；
4. 未来若要事件订阅（例如 HDMI 热插拔通知），再加 `baseosd`，
   届时 DAL 的**函数签名不变**，只是多一个客户端。

**待用户拍板**：是否需要 `baseosd`（见 `README.md` 决策点 D3）。

### 1.3 库的位置与加载方式

```
/usr/lib/baseos/dal.sh          # 主入口，source 后得到全部 dal_* 函数
/usr/lib/baseos/dal/*.sh        # 每子系统一个文件，dal.sh 按需 source
/etc/pjos/board.json            # 构建时生成：有效配置（soc + board 深合并后）
/etc/pjos/soc.json              # 构建时生成：SoC 原始声明（诊断用）
/etc/pjos/caps.json             # 构建时生成：见 04
/etc/pjos/features.json         # 构建时生成：见 05
```

调用方：

```sh
. /usr/lib/baseos/dal.sh
dal_init || exit 1              # 解析 /etc/pjos/board.json 一次，导出 DAL_* 变量
dal_display_info
```

`dal_init` 失败（JSON 缺失/损坏/未知 schema）时**必须**返回非 0 并让调用方
决定降级——DAL 不允许"猜一个默认值继续跑"。这一条直接对应
`01-audit.md` P1-2 的教训：`BASEOS_WIFI` 烘焙进镜像却无人读取，因为
"没有它也能跑"。

### 1.4 统一约定

| 约定 | 规则 |
|---|---|
| 函数名 | `dal_<subsystem>_<verb>`，全小写，下划线分词 |
| 只读查询 | 输出 `key=value` 行（一行一项），**不输出人类散文** |
| 写操作 | 参数化，成功返回 0，失败返回非 0 且 **stderr 一行原因** |
| 未知能力 | 返回 **3**（`unknown`），与"失败"（1）严格区分 |
| 不支持 | 返回 **4**（`unsupported`），即 profile 声明 `no` |
| 幂等 | 所有写操作必须幂等：重复调用与调用一次结果相同 |
| 原子性 | 写节点用"写临时值再写目标值"不适用；改为"先校验可写再写" |
| 阻塞 | DAL 函数**不得**无限阻塞。所有等待必须有上界，且上界由调用方传入 |
| 依赖 | 只依赖 busybox applet + `/usr/lib/baseos/dal/` 内的辅助程序 |

退出码全表见 `06-baseosctl.md §5`；DAL 与 `baseosctl` **共用同一套退出码**。

---

## 2. 子系统总表

| # | 子系统 | 语义 | 状态 | 现有实现位置 |
|---|---|---|---|---|
| 1 | display | 显示输出、分辨率、亮度、旋转、输出切换 | 部分（探测式） | `src/fbsplash.c`、`src/charger-wait.c`、`overlay/etc/init.d/rcS:66-71` |
| 2 | audio | 播放设备、音量、静音、路由 | 部分（写死控制名） | `overlay/usr/sbin/baseos-startup-sound:26-31` |
| 3 | input | 输入设备枚举、按键、电源键、MENU | 部分（名字匹配） | `src/charger-wait.c:49-50`、`overlay/usr/sbin/boot-menu-held:8` |
| 4 | power | 电池、充电器、LED、suspend、关机 | 部分（PMIC 型号写死） | `overlay/etc/init.d/rcS:11,80`、`overlay/usr/sbin/baseos-charger:64`、`src/axp-off.c` |
| 5 | network | WiFi、蓝牙、接口状态、mDNS | 部分（驱动名写死） | `overlay/etc/init.d/rcS:189-251`、`overlay/mnt/vendor/ctrl/setBluetooth.sh` |
| 6 | storage | 分区角色、卡槽、扩容、USB 存储模式 | 部分（分区号写死） | `overlay/usr/sbin/expand-storage:14-15`、`overlay/usr/sbin/usb-storage-mode:12-13` |
| 7 | led | 指示灯、震动 | **缺失** | `overlay/usr/sbin/baseos-charger:64`（只有 work_led） |

---

## 3. display

### 3.1 接口

```sh
# 能力与几何
dal_display_info
# 输出（key=value）：
#   backend=fbdev|drm
#   width=720
#   height=480
#   bpp=32
#   rotation_ccw=0
#   logical_width=720
#   logical_height=480
#   vsync=timer|pageflip
#   brightness_min=0
#   brightness_max=255
#   brightness=180
#   brightness_control=ioctl|sysfs|none
# 退出：0 成功；3 无法确定（例如 fb 节点存在但 ioctl 不支持）
dal_display_node
# 输出：/dev/fb0 或 /dev/dri/card0（**唯一**允许向 Runtime 泄露节点的地方，
# 因为 Runtime 必须 open() 它；这是 display 子系统的显式例外，见 §3.3）
dal_display_brightness_get     # 输出 0..255；3 unknown
dal_display_brightness_set N   # 0 成功；1 失败；3 unknown；4 unsupported
dal_display_blank on|off       # 0/1/3/4
dal_display_output list        # 每行 output=<name> connected=yes|no active=yes|no
dal_display_output_set <name>  # 切换 LCD/HDMI；4 当 profile 声明 hdmi=no
```

### 3.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 | 备注 |
|---|---|---|---|
| framebuffer | `/dev/fb0` | `docs/13-pocketjs-on-baseos.md:15`（`/dev/dri` 不存在） | 只有 fbdev |
| 显示控制器 ioctl | `/dev/disp` | `validate-on-device.sh:53`（`test -c /dev/disp && test -c /dev/fb0`） | `DISP_LCD_SET/GET_BRIGHTNESS` = 0x102/0x103 |
| 亮度（备用） | `/sys/class/disp/disp/attr/enhance_bright` | `docs/13-pocketjs-on-baseos.md:20` | 与 ioctl 并存，需实测哪条生效 |
| 亮度（sysfs 通用） | `/sys/class/backlight/*/brightness` | `overlay/usr/sbin/baseos-charger:44` | H700 上**不存在**，该循环是空转 |
| 输出切换 | `/sys/kernel/debug/dispdbg/{command,param}` | `overlay/etc/init.d/rcS:66-71` | 需要 debugfs 挂载 |
| HDMI 热插拔 | `/sys/class/extcon/hdmi/state` | `validate-on-device.sh:56` | 只有 H700 有 |
| 面板几何 | `/sys/class/graphics/fb0/{virtual_size,bits_per_pixel}` | `overlay/usr/sbin/baseos-diag:532`、`validate-on-device.sh:57-60` | 校验用，不用于渲染 |
| 旋转 | `BASEOS_PANEL_ROTATION_CCW` in `/etc/baseos-release` | `src/fbsplash.c:882` | 迁移后读 `/etc/pjos/board.json` |

**关键决定**：`dal_display_info` 的 `width/height/rotation` 来自 **profile**，
不是来自 framebuffer。理由：`validate-on-device.sh:54-60` 已经把它当"profile 应该
等于硬件"的断言——profile 是契约，硬件是事实，两者不符要报警而不是静默采用硬件值。

`dal_display_brightness_set` 的实现优先级：

```
1. profile.power/display 声明 brightness_control=ioctl → 用 /dev/disp ioctl
2. 声明 sysfs → 写 profile 给的节点
3. 都没有 → 返回 3 (unknown)，不猜
```

对应现状：`overlay/usr/sbin/baseos-charger:44-54` 现在遍历
`/sys/class/backlight/*/brightness` 与 cpufreq governor，在 H700 上 backlight
目录不存在，循环**静默空转**——这是"猜"的典型形态，DAL 必须消除它。

### 3.3 为什么 display 允许向 Runtime 泄露一个节点路径

Runtime（`pocket-linux-kms`）必须自己 `open("/dev/fb0")` 并 `mmap`，
这是 fbdev 的编程模型决定的，DAL 无法代劳（除非做共享内存代理，
那会把整个渲染路径搬到 DAL，违背分层）。

所以规则精确化为：

> **Runtime 只能通过 `dal_display_node` 获得节点路径，不得自己拼路径、不得探测。**

`dal_display_node` 的输出来自 `board.json` 的 `display.node`，
是一个**稳定语义查询**，不是探测。这满足"Runtime 不知道设备类型"：
它知道"这块屏的帧缓冲是某个路径"，不知道是 H700 还是 A133。

---

## 4. audio

### 4.1 接口

```sh
dal_audio_info
#   card=0
#   card_name=audiocodec
#   mixer=amixer|alsactl|none
#   volume_control=digital volume
#   volume_min=0
#   volume_max=63
#   volume=63
#   mute_control=none|"<name>"
#   route_controls=OutputL Mixer DACL,OutputR Mixer DACR,LINEOUT,SPK
#   amp_module=h700_speaker_amp
#   amp_loaded=yes|no|unknown
dal_audio_volume_get             # 输出 0..100（归一化）；3 unknown
dal_audio_volume_set 0..100      # 0/1/3/4
dal_audio_mute on|off            # 0/1/3/4
dal_audio_route_default          # 应用 profile 的 route_controls（开机/播放前）
dal_audio_cards                  # 每行 card=<n> name=<name>；用于诊断
```

### 4.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| 声卡 | `/proc/asound/cards` 中 name 含 `audiocodec` | `validate-on-device.sh:64` |
| 音量控制名 | `digital volume`（max 63） | `overlay/usr/sbin/baseos-startup-sound:26` |
| 线路输出音量 | `lineout volume`（max 31） | `:27` |
| 路由开关 | `OutputL Mixer DACL`、`OutputR Mixer DACR`、`LINEOUT`、`SPK` | `:28-31` |
| 功放模块 | `/lib/modules/h700_speaker_amp.ko` + 参数 `apply=1 headphone_pop_fix=0|1` | `overlay/usr/sbin/h700-speaker-amp-load:6,24` |
| 耳机 pop 选项来源 | `/run/baseos.conf` 的 `headphone_pop_fix=` | `overlay/usr/sbin/h700-speaker-amp-load:12-19` |
| 混音器保存/恢复 | `alsactl`（跨 suspend） | `docs/05-runtime-power-network.md:17` |

**关键决定**：音量**归一化到 0..100**，由 DAL 按 `volume_min/max` 换算。
理由：`digital volume` 是 0..63、`lineout volume` 是 0..31，两个原始量程
不能同时暴露给应用。应用问"音量多少"，答案必须是同一个语义单位。

**迁移对应**：`overlay/usr/sbin/baseos-startup-sound:26-31` 的 7 条
`amixer -c 0 sset` 变成一次 `dal_audio_route_default`；控制名从
`board.json` 的 `audio.controls` 读。

---

## 5. input

### 5.1 接口

```sh
dal_input_list
# 每行：node=/dev/input/event1 name=ANBERNIC-keys kind=keyboard|power|gamepad|touch
dal_input_node <kind>            # 输出该 kind 的节点；3 找不到；4 profile 声明没有
dal_input_power_node             # 电源键节点；3/4
dal_input_menu_held              # 0=按住 1=未按住 3=无法判断 4=该板无 MENU
dal_input_key_state <kind> <KEY_NAME>   # 输出 pressed=0|1；3/4
```

### 5.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| 事件设备 | `/dev/input/event0..2` + `js0` | `docs/13-pocketjs-on-baseos.md:16` |
| 键盘 | `event1`，`EVIOCGNAME` = `ANBERNIC-keys` | 同上 |
| 电源键 | `EVIOCGNAME` 前缀 `axp` + 后缀 `-pek` | `src/charger-wait.c:49-50` |
| MENU 冷启动 | `/sys/kernel/debug/gpio` 中 `\|GPIO Key Menu ) in lo` | `overlay/usr/sbin/boot-menu-held:8` |
| MENU 备用 | evdev `BTN_MODE`（**不可靠**，`EVIOCGKEY` 状态陈旧） | `overlay/usr/sbin/boot-menu-held:3-4` 注释 |

**关键决定（这条必须有证据支撑，不能靠"探测"）**：
`boot-menu-held:3-4` 明写"input driver advertises BTN_MODE but its EVIOCGKEY
state is stale, so the active-low GPIO level is the only reliable one-shot
source at cold boot"。所以 `dal_input_menu_held` 在 H700 上**必须**用 GPIO 路径，
而且这是一条**板级事实**，写进 `board.json` 的 `input.menu_gpio_label`。

新板如果没有 GPIO 文本可匹配、但 evdev 可靠，就在它的 `board.json` 里
声明 `menu_source: evdev`。DAL 按声明选路径，不按"先试 A 再试 B"。

### 5.3 与 keyboardd 的关系

`runtime/keyboardd` 已经用 Capability 选择输入模式
（`runtime/keyboardd/keyboardd.go:41-53`，明确"never by device-name strings"）。
DAL 的 `dal_input_list` 是它的**数据来源**，不是替代：

```
keyboardd 启动 → 调 baseosctl input list → 得到 kind 集合 → 选 provider
```

这样 `keyboardd` 仍然不认识板，只是从"自己扫 evdev"变成"问系统"。

---

## 6. power

### 6.1 接口

```sh
dal_power_battery
#   present=yes|no
#   capacity=87
#   status=Discharging|Charging|Full|Not charging|Unknown
#   voltage_uv=3980000
#   health=Good|Unknown
dal_power_charger
#   online=0|1
#   name=axp2202-usb
dal_power_supplies            # 每行 supply=<name> type=<Battery|USB|Mains|...>
dal_power_boot_reason
#   reason=normal|charger|unknown
dal_power_led on|off|auto     # 4 当 profile 无 led
dal_power_suspend             # 0 成功；3/4；不阻塞
dal_power_off                 # 幂等；走 BSP 的 PMIC 路径
dal_power_reboot
dal_power_rtc_alarm_get       # 输出 alarm_epoch=<n>|none；3/4
dal_power_rtc_alarm_set <epoch>  # 0/1/3/4
```

### 6.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| 电池 | `/sys/class/power_supply/axp2202-battery/{capacity,status}` | `validate-on-device.sh:67`、`overlay/usr/sbin/baseos-diag:482` |
| 充电器 | `/sys/class/power_supply/*usb*` 或 `*ac*` 的 `online` | `overlay/usr/sbin/baseos-diag:483` |
| 开机原因 | `axp2202-battery/boot_mode`（`1` = 充电开机） | `overlay/etc/init.d/rcS:80-82`、`src/native-health.c:26` |
| 开机原因（备用） | `/proc/cmdline` 含 `bootreason=charger` | `overlay/etc/init.d/rcS:86-87` |
| work LED | `axp2202-battery/work_led` | `overlay/usr/sbin/baseos-charger:64-65` |
| 震动 | `axp2202-battery/moto` | `validate-on-device.sh:70` |
| suspend | 写 `mem` 到 `/sys/power/state` | `docs/05-runtime-power-network.md:16` |
| SP suspend 策略 | `axp2202-battery/os_sleep` = `16` | `overlay/etc/init.d/rcS:11-12` |
| RTC | `/sys/class/rtc/rtc0/since_epoch` | `overlay/usr/sbin/baseos-charger:19` |
| RTC 写入 | `hwclock -u -w` | `overlay/usr/sbin/baseos-ntp-notify:12` |
| 硬关机 | PMIC 寄存器 0x27（只认 `axp2202`） | `src/axp-off.c:18,26,REG` |

**关键决定**：`dal_power_boot_reason` 把两条来源合并成一个枚举。
现在的代码是 `rcS:80-89` 先读 PMIC、失败再读 cmdline——这是**正确的降级顺序**，
DAL 保留它，但把两条路径都声明在 `board.json` 的 `power.*` 里。

**关键决定**：`dal_power_off` **不**直接写寄存器，而是调用 BSP 提供的
`bsp_power_off`（迁移后 `src/axp-off.c` → `bsp/allwinner/h700/tools/axp-off`）。
理由：`src/axp-off.c:24` 的注释写着"only add measured parts"（`KNOWN_PARTS`
只有 `axp2202`）——这是**逐 PMIC 的实测白名单**，属于 BSP 事实。

### 6.3 `rtc_alarm` 的现状（诚实标注）

`docs/12-kernel-gzip.md:233` 记录了一次"woke on an RTC alarm"的实验，
但**发行版里没有任何 RTC 唤醒接口**。因此：

- Feature `rtc_alarm` 在 H700 上的初始取值必须是 **`unknown`**，不是 `yes`。
- 只有当 `dal_power_rtc_alarm_set` 在真机上被验证过（设定 → suspend → 按时唤醒），
  才允许把 `board.json` 改成 `yes`。

这条写进 `05-feature.md` 的"取证规则"：**Feature 的 `yes` 必须有实测证据**。

---

## 7. network

### 7.1 接口

```sh
dal_network_info
#   wifi_present=yes|no|unknown
#   wifi_iface=wlan0
#   wifi_state=up|down|absent
#   wifi_ip=<address>|none
#   bt_present=yes|no|unknown
#   bt_state=up|down|absent
#   bt_hci=hci0|none
dal_network_wifi_up               # 0/1/3/4；含 BSP 声明的等待与重试策略
dal_network_wifi_down
dal_network_wifi_scan             # 每行 ssid=... signal=... security=...
dal_network_bt_up                 # 0/1/3/4
dal_network_bt_down
dal_network_mdns_refresh          # 委托给 baseos-mdns
```

### 7.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| WiFi 接口 | `/sys/class/net/wlan0` | `overlay/etc/init.d/rcS:223,238,247` |
| WiFi 控制器 | `/sys/class/misc/sunxi-wlan/rf-ctrl/{scan_device,power_state}` | `overlay/etc/init.d/rcS:209-212` |
| WiFi 驱动 | `/lib/modules/8821cs.ko` | `overlay/etc/init.d/rcS:221`、`build-rootfs.sh:97-98` |
| WiFi 工具 | `wpa_supplicant`、`wpa_cli` | `manifest/harvest.list:104-107` |
| BT 唤醒驱动 | `/lib/modules/rtl_btlpm.ko` | `overlay/etc/init.d/rcS:189` |
| BT 传输 | `rtk_hciattach -n -s 115200 ttyS1 rtk_h5` | `overlay/mnt/vendor/ctrl/setBluetooth.sh:12` |
| BT 守护 | `/usr/libexec/bluetooth/bluetoothd` | `overlay/usr/sbin/systemctl:66` |
| BT 音频 | `bluealsa`、`bluealsa-aplay` | `manifest/harvest.list:120-121` |
| mDNS | `avahi-daemon` + `ip -4 addr show dev wlan0` | `overlay/usr/sbin/baseos-mdns:28-32` |

**关键决定**：`dal_network_wifi_up` **必须**封装 `rcS:185-251` 那段
80 行的时序逻辑（stale SDIO 丢弃、两次尝试、慢电台标记）。这段逻辑是
H700 特有的**时序事实**，不是"通用 WiFi 初始化"。它属于 BSP：

- 声明：`soc.json` 的 `hw_init` 里 `step: load-wifi`，带
  `pre: discard-stale-sdio`、`retry: {unload: true, hold_ms: 5000}`；
- 实现：`bsp/allwinner/h700/overlay/usr/lib/baseos/dal/wifi.sh`；
- 上层：`dal_network_wifi_up` 只负责"调 BSP 提供的实现，返回语义结果"。

这样 `rcS` 从 393 行降到约 150 行，且 A133 的 WiFi 初始化写在
`bsp/allwinner/a133/` 里，互不影响。

---

## 8. storage

### 8.1 接口

```sh
dal_storage_roles
#   boot_disk=/dev/mmcblk0
#   rootfs=<active slot device or role>
#   data=/dev/mmcblk0p6
#   primary=/dev/mmcblk0p7
#   tf2=/dev/mmcblk1|none
#   layout=baseos-ab-v1
dal_storage_role <boot|rootfs|data|primary|tf2>   # 输出设备路径；3/4
dal_storage_info
#   rootfs_mounted_ro=yes|no
#   data_free_mb=118
#   primary_free_mb=27000
#   tf2_present=yes|no
dal_storage_expand                 # 幂等；0=已满 1=已扩容 2=错误
dal_storage_usb_mode prepare       # 导出可安全卸载的设备
dal_storage_usb_mode status
dal_storage_card_mount             # 挂载前端卡到 /mnt/sdcard；0/1
```

### 8.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| 启动盘 | `/dev/mmcblk0` | `overlay/usr/sbin/baseos-update:30`、`expand-storage:14` |
| rootfs（slot A） | `/dev/mmcblk0p5` | `overlay/etc/init.d/rcS:41`、`tools/gptslot.c:4` |
| `/data` | `/dev/mmcblk0p6` | `overlay/etc/init.d/rcS:120` |
| 主 FAT 分区 | `/dev/mmcblk0p7` | `expand-storage:15`、`usb-storage-mode:12` |
| 第二卡槽 | `/dev/mmcblk1`、`/dev/mmcblk1p1` | `overlay/etc/init.d/rcS:292,322`、`usb-storage-mode:13` |
| 分区角色（编号） | `boot=4, rootfs=5, UDISK=6, primary=7` | `tools/gptslot.c:36-38`、`overlay/etc/fstab:2-4` |
| GPT 条目数 | 8 | `tools/mkgpt.py:36`、`tools/prepare_stock.py:121` |
| 卡槽供电状态 | `/sys/devices/platform/soc/sdc2/mmc_host/mmc*/ios`（debugfs） | `overlay/etc/init.d/rcS:278-280` |

**关键决定：角色，不是编号。**

`dal_storage_role rootfs` 的答案**不是** `mmcblk0p5`，而是"当前活动的
A/B 槽位设备"，由 BSP 的 `storage.roles` + A/B 状态计算得出。
今天 `gptslot` 已经做了这件事（`tools/gptslot.c:20-22`：

> `slot_base = boot.end + 1`；`slot_sectors = rootfs.end - rootfs.start + 1`；
> `active = A if rootfs.start == slot_base else B`

），DAL 只是把它包一层，让调用方问"rootfs 在哪"而不是"p5 在哪"。

**为什么这是 P0-5 的解药**：`01-audit.md §2 P0-5` 列出 10 个脚本里的
`mmcblk0pN` 字面量。迁移后它们全部变成 `dal_storage_role data` 之类。
新增一台分区序号不同的设备时，改的是它自己的 `board.json` 的 `storage.roles`，
**一个脚本都不用改**。

---

## 9. led

### 9.1 接口

```sh
dal_led_list                    # 每行 name=<n> kind=status|work|charge
dal_led_set <kind> on|off|auto  # 4 当 profile 无此 led
dal_led_vibrate <ms>            # 0/1/3/4
```

### 9.2 节点 → 语义映射

| 语义 | H700 上的真实来源 | 证据 |
|---|---|---|
| work LED | `axp2202-battery/work_led` | `overlay/usr/sbin/baseos-charger:64-65` |
| 震动 | `axp2202-battery/moto` | `validate-on-device.sh:70` |
| 通用 LED class | `/sys/class/leds/*` | **H700 上不存在**（`docs/13-pocketjs-on-baseos.md:20`："无 `/sys/class/leds`"） |

**这是"缺失子系统"的诚实处理**：H700 没有 `/sys/class/leds`，
只有 PMIC 暴露的两个非标准属性。所以 `dal_led_*` 在 H700 上的实现是
"读 profile 的 `power.led` / `power.vibration`，写那两个属性"，
而不是"遍历 `/sys/class/leds`"。

`dal_led_list` 在 H700 上输出两行（`work`、`charge` 若存在），
在 A133 上可能输出标准的 `leds` 类。**接口相同，实现由 BSP 决定。**

---

## 10. 全量映射表：现状字面量 → DAL 调用

这张表是迁移的工作清单。每一行都是 `01-audit.md` 里指认过的字面量。

| 现状（文件:行） | 字面量 | 迁移后 |
|---|---|---|
| `overlay/etc/init.d/rcS:11-12` | `axp2202-battery/os_sleep` = 16 | `dal_power_suspend_policy`（BSP 实现） |
| `overlay/etc/init.d/rcS:41` | `/dev/mmcblk0p5` | `dal_storage_role rootfs` |
| `overlay/etc/init.d/rcS:80-82` | `axp2202-battery/boot_mode` | `dal_power_boot_reason` |
| `overlay/etc/init.d/rcS:109` | `insmod mali_kbase.ko` | `soc.json hw_init[load-gpu]` |
| `overlay/etc/init.d/rcS:115` | `insmod h700_late_usb.ko` | `soc.json hw_init[load-late-usb]` |
| `overlay/etc/init.d/rcS:120` | `/dev/mmcblk0p6` | `dal_storage_role data` |
| `overlay/etc/init.d/rcS:185-251` | WiFi 时序块（80 行） | `dal_network_wifi_up` |
| `overlay/etc/init.d/rcS:292-322` | `/dev/mmcblk1p1`、`/dev/mmcblk0p7` | `dal_storage_role tf2`/`primary` |
| `overlay/etc/init.d/rcS:377-382` | `h700-speaker-amp-load` | `dal_audio_amp_attach` |
| `overlay/usr/sbin/baseos-charger:11` | `/dev/mmcblk0p6` | `dal_storage_role data` |
| `overlay/usr/sbin/baseos-charger:19` | `/sys/class/rtc/rtc0/since_epoch` | `dal_power_rtc_get` |
| `overlay/usr/sbin/baseos-charger:44-54` | `/sys/class/backlight/*`、cpufreq | `dal_display_brightness_set` |
| `overlay/usr/sbin/baseos-charger:64` | `axp2202-battery/work_led` | `dal_led_set work on` |
| `overlay/usr/sbin/baseos-diag:455,478` | `axp[0-9]*` 前缀扫描 | `dal_power_supplies` |
| `overlay/usr/sbin/baseos-diag:532` | `/sys/class/graphics/fb0/*` | `dal_display_info` |
| `overlay/usr/sbin/baseos-diag:537` | `/sys/class/udc/*/state` | `dal_storage_usb_mode status` |
| `overlay/usr/sbin/boot-menu-held:6-8` | `/sys/kernel/debug/gpio` 文本匹配 | `dal_input_menu_held` |
| `overlay/usr/sbin/expand-storage:14-15` | `mmcblk0`、`mmcblk0p7` | `dal_storage_expand` |
| `overlay/usr/sbin/baseos-update:30-31` | `mmcblk0`、`mmcblk0p7` | `dal_storage_role boot`/`primary` |
| `overlay/usr/sbin/usb-storage-mode:12-13` | `mmcblk0p7`、`mmcblk1` | `dal_storage_usb_mode` |
| `overlay/usr/sbin/baseos-startup-sound:8,13` | `/dev/mmcblk0p7` | `dal_storage_role primary` |
| `overlay/usr/sbin/baseos-startup-sound:26-31` | 7 条 `amixer -c 0 sset` | `dal_audio_route_default` |
| `overlay/usr/sbin/baseos-boot-migrate:54-55,397-398` | `mmcblk0`、`mmcblk0p4` | `dal_storage_role boot` |
| `overlay/usr/sbin/baseos-mdns:28` | `ip -4 addr show dev wlan0` | `dal_network_info` |
| `overlay/mnt/vendor/ctrl/setBluetooth.sh:11-12` | `insmod rtl_btlpm`、`ttyS1` | `dal_network_bt_up` |
| `overlay/usr/sbin/frontend-session:106` | `/dev/mmcblk1p1`、`/dev/mmcblk0p7` | `dal_storage_card_mount` |
| `src/charger-wait.c:49-50` | `axp*` + `-pek` 名字匹配 | `dal_input_power_node` |
| `src/native-health.c:26` | `axp2202-battery/boot_mode` | `dal_power_boot_reason` |
| `src/native-health.c:251` | `/dev/mali0` | `dal_display_gpu_ready`（新增） |
| `src/axp-off.c:18,26` | `axp20x-i2c`、`axp2202` | `bsp_power_off`（BSP 内部） |

---

## 11. DAL 不做什么

明确的**非目标**，避免范围膨胀：

| 不做 | 为什么 | 谁做 |
|---|---|---|
| 不实现渲染 | fbdev/DRM 编程模型要求 Runtime 自己 mmap | Runtime |
| 不管策略 | "没电了要不要关机"是产品决策 | BaseOS Services |
| 不做设备热插拔事件订阅（v1） | 需要常驻进程；当前无消费方 | 未来 `baseosd` |
| 不做电源管理状态机 | 现在由前端与 rcS 分别处理 | 维持现状 |
| 不解析配置文件（`baseos.conf`） | 那是 BaseOS Services 的职责 | `baseos-config` |
| 不写日志 | 日志格式是发行版策略 | `boot-log.sh` |

---

## 12. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `dal_init` 每次调用都解析 JSON，busybox sh 下慢 | 中（rcS 预算 < 1s，`rcS:2-3`） | 构建时把 JSON 预渲染成 `DAL_*` shell 变量文件，`dal_init` 只 `source` 一个文件（无解析） |
| 归一化音量掩盖了原始量程，调试时看不到真值 | 低 | `dal_audio_info` 同时给 `volume` 与 `volume_raw` |
| `dal_display_node` 泄露路径，被滥用为"通用节点查询" | 中 | 该函数是**唯一**例外，lint 检查其它 `dal_*` 的返回值不含 `/dev/` |
| WiFi 时序块迁入 BSP 后，H700 行为若变化无法快速对比 | 高 | 迁移步骤保留旧路径一个版本（`07` 的 M6 双跑对比） |
| 7 个子系统的接口一次定死，后续发现不够用 | 中 | 接口只增不改；新增函数是 minor，改语义是 major（`06 §7`） |
| `dal_power_off` 委托给 BSP，若 BSP 缺失则无法关机 | 高 | `dal_power_off` 在 BSP 实现缺失时退回 `busybox poweroff`（内核关机），并记录 |

---

## 13. 验收标准

| # | 标准 | 判据 |
|---|---|---|
| D1 | 7 个子系统都有 `dal_<sub>_info` | `for s in display audio input power network storage led; do dal_${s}_info >/dev/null; done` 全部返回 0 或 3/4 |
| D2 | overlay 里不再有 `/sys`、`/proc`、`/dev` 字面量（display 例外除外） | `grep -rE '/(sys|proc|dev)/' overlay/` 只命中 `dal/*.sh` 与注释 |
| D3 | 每个 DAL 函数在 fake 树上可测 | `bsp/boards/<id>/tests/` 用 `BASEOS_SYS_ROOT` 指向 tmpfs（沿用 `overlay/usr/sbin/usb-gadget-adb:36-54` 的既有模式） |
| D4 | 未知能力返回 3，不支持返回 4 | 在无电池的 fake 树上 `dal_power_battery` 返回 3，不是 1 |
| D5 | 写操作幂等 | 连续两次 `dal_display_brightness_set 100` 结果相同且都返回 0 |
| D6 | `dal_storage_role rootfs` 跟随 A/B 翻转 | 用 `tests/test-gpt-slot.sh` 的 fixture，flip 后答案变化 |
