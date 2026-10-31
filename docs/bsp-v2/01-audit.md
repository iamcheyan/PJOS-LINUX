# 01 — 当前架构问题审计（证据驱动）

> 本文件只陈述**当前仓库里可指认的事实**。每条结论后面括号里是 `路径:行号`。
> 没有行号的地方是"计数类事实"，后面给出产生该计数的命令，可复现。
> 设计本身在 `02`–`07`；本文件不做设计，只做审计。

审计基线：分支 `feature/bsp-v2`，起点 `main` @ `dc99d57`，`VERSION` = `1.5.2`。

---

## 0. 一句话结论

当前仓库已经**有**一套完整的"单 SoC 多板型"发行版，但**没有** BSP 这一层。
11 个 target（`devices.json`）共享同一份 overlay、同一份 harvest 清单、同一份内核补丁、
同一组写死的分区号；板级差异不是被"收敛到一个目录"，而是被**复制到 6 个互不相干的地方**，
其中 4 处是**逐板手写、靠人肉保持一致**的 11 条表。

第 2 台设备靠人肉可以维持；第 20 台必然失控，理由不是"工作量大"，而是
**同一事实存在 5 份副本且没有任何机制强制它们一致**（§3.2）。

---

## 1. 仓库里到底有几套"板级事实"

这是审计的核心发现。同一台设备的信息，在仓库里存在 **5 份独立的表**，全部按 target id 索引，
全部是 11 条，全部靠手工维护，**彼此之间没有交叉校验**：

| # | 位置 | 内容 | 条数 | 谁读它 |
|---|---|---|---|---|
| T1 | `devices.json:3-137` | 身份、bootlogo 尺寸、旋转、wifi/bluetooth | 11 | `tools/device_profile.py` |
| T2 | `manifest/kernel-gzip.json:4-` | boot0/U-Boot/package 的 SHA、偏移、boot 分区几何 | 11 | `tools/kernel_gzip.py` |
| T3 | `src/h700-speaker-amp/profiles.json:2-` | 厂商内核 Image SHA、config SHA、8 个私有符号偏移 | 11 | `tools/audio_module.py:36-45` |
| T4 | `experiments/h700-boot-speed/evidence/compatibility.json:targets` | boot0/package SHA、DRAM 候选表 | 11 | `experiments/h700-boot-speed/native/build.py:45` |
| T5 | `experiments/h700-boot-speed/native/panel-contract.json:models` | 面板 strap、pull-up、上电/复位时序 | 11 | `experiments/h700-boot-speed/native/build.py:92` |

复现命令：

```sh
python3 - <<'EOF'
import json
for p,k in [("manifest/kernel-gzip.json","profiles"),
            ("experiments/h700-boot-speed/evidence/compatibility.json","targets"),
            ("experiments/h700-boot-speed/native/panel-contract.json","models"),
            ("src/h700-speaker-amp/profiles.json",None)]:
    d=json.load(open(p)); k=k or None
    print(p, len(d[k] if k else d))
EOF
# 输出：全部 11 条，target id 集合完全相同
```

**为什么这阻碍多设备**：新增第 12 台设备要同时改 5 个文件，且没有任何检查会因为
"你在 T1 加了、忘了在 T3 加"而失败。`T3` 缺条目时 `audio_module.inputs()` 会抛
`unaudited audio kernel`（`tools/audio_module.py:38-39`），这是**唯一**一处硬失败；
`T2` 缺条目时 `kernel_gzip.py` 在 apply 阶段才失败；`T4`/`T5` 缺条目时 native loader
构建失败。也就是说：漏改的后果分散在 5 个不同阶段、报错信息互不相关。

---

## 2. 逐条问题（按"阻碍 20 台设备"的严重度排序）

### P0-1 — `overlay/` 是单份，且含 H700/SoC 专有逻辑

**事实**：`overlay/` 共 39 个文件，其中 **14 个**含板名或 SoC 名：

```sh
grep -rliE 'h700|axp2202|axp[0-9]|anbernic|rg28xx|rg34xx|rg35xx|rg40xx|rgcubexx|rgsp|sunxi|allwinner|8821|mali|rtl_bt' overlay/ | wc -l   # 14
find overlay -type f | wc -l                                                                                                          # 39
```

具体耦合点（行号级）：

| 位置 | 内容 | 性质 |
|---|---|---|
| `overlay/etc/init.d/rcS:2` | `# H700 base OS early init.` | 注释即身份 |
| `overlay/etc/init.d/rcS:11-12` | 写 `/sys/class/power_supply/axp2202-battery/os_sleep` = `16` | PMIC 型号 + SP 板专有 |
| `overlay/etc/init.d/rcS:66-71` | 挂 debugfs 以暴露 `/sys/kernel/debug/dispdbg`，注释明写"sunxi disp2 driver 唯一的显示输出控制面" | SoC 显示栈 |
| `overlay/etc/init.d/rcS:80-82` | 读 `axp2202-battery/boot_mode` 判充电开机 | PMIC 型号 |
| `overlay/etc/init.d/rcS:109` | `insmod /lib/modules/mali_kbase.ko` | GPU blob |
| `overlay/etc/init.d/rcS:115` | `insmod /lib/modules/h700_late_usb.ko` | H700 专有补丁 |
| `overlay/etc/init.d/rcS:189,221,240` | `rtl_btlpm.ko` / `8821cs.ko` / `rmmod 8821cs` | 具体 WiFi/BT 芯片 |
| `overlay/etc/init.d/rcS:209` | `/sys/class/misc/sunxi-wlan/rf-ctrl` | sunxi 私有节点 |
| `overlay/etc/init.d/rcS:380-381` | 执行 `h700-speaker-amp-load` | 板名进"通用"启动脚本 |
| `overlay/etc/profile:1,5` | `PATH=.../.system/h700/bin`、`export PLATFORM=h700` | 把板名导出给所有子进程 |
| `overlay/etc/inittab:1` | `# BusyBox init for BaseOS on H700.` | 注释即身份 |
| `overlay/usr/sbin/frontend-session:121,175-176` | 硬编码 `$SD/.system/h700/paks/MinUI.pak/launch.sh` | 前端路径里带板名 |
| `overlay/usr/sbin/frontend-session:136,141-143` | 硬编码 `.tmp_update/h700.sh` | 同上 |
| `overlay/usr/sbin/systemctl:3` | `# Covers exactly the calls NextUI's h700 scripts make:` | 兼容层绑定单一前端+单板 |
| `overlay/usr/sbin/boot-menu-held:2,6` | "vendor H700 DT-labelled MENU GPIO" + `/sys/kernel/debug/gpio` 文本匹配 | DT 标签匹配 |
| `overlay/usr/sbin/h700-speaker-amp-load` (整文件) | 文件名即板名 | 见 P0-3 |
| `overlay/usr/sbin/baseos-diag:118` | 注释引用 `work/h700-loader/v152-lp4` | 实验室路径 |
| `overlay/usr/sbin/baseos-diag:455` | `sed -n 's/^\(axp[0-9]*\).*/\1/p'` 识别 PMIC | PMIC 型号前缀 |
| `overlay/usr/sbin/baseos-diag:550` | dmesg 过滤词含 `sunxi-mmc\|disp\|lcd\|tcon\|axp` | SoC 驱动名 |
| `overlay/usr/sbin/baseos-charger:64` | `work_led=/sys/class/power_supply/axp2202-battery/work_led` | PMIC 型号 |
| `overlay/mnt/vendor/ctrl/setBluetooth.sh:4,11-12` | `insmod rtl_btlpm.ko` + `rtk_hciattach ... ttyS1` | 芯片 + UART 号 |
| `overlay/usr/sbin/usb-gadget-adb:13,20` | "sunxi OTG role manager"、"measured on rg40xxv, 4.9.170" | SoC 行为 + 板名 |

**为什么阻碍多设备**：`overlay/` 只有一份。A133（`docs/14` 描述的 Smart Pro）需要
不同的 PMIC、不同的显示控制面、不同的 WiFi 驱动。只有两条路：

1. 复制整个 `overlay/` → 两份漂移，且 `build-rootfs.sh` 必须知道该用哪份；
2. 在单份里堆 `if [ "$SOC" = ... ]` → 板级判断回到"通用"脚本。

两条路都让"新增设备不改 overlay"这条硬约束失效。

### P0-2 — `manifest/harvest.list` 单一全局，内容是 H700 的 ldd 闭包

**事实**：

- 文件第 1 行注释：`# H700 base OS stock harvest allowlist.`（`manifest/harvest.list:1`）
- 第 6-8 行写明基线来源：`the on-device ldd closure of every NextUI ELF + kept daemons (2026-07-19, RG40XXV stock V1.1.1.0)`（`manifest/harvest.list:6-8`）
- 142 行，全部是绝对路径，其中 3 条把**内核版本号写进路径**：
  `manifest/harvest.list:136-137`
  ```
  /usr/lib/modules/4.9.170/kernel/drivers/net/wireless/rtl8821cs/8821cs.ko
  /usr/lib/modules/4.9.170/kernel/drivers/bluetooth/rtl_btlpm.ko
  ```
- 清单里**唯一**的板级裁剪机制是三个布尔开关：`tools/prepare_stock.py:489-499`
  ```python
  def omission_allowed(path, category, profile):
      if category == "wifi" and path != "/usr/sbin/fsck.fat":
          return not profile["wifi"]
      if category == "bluetooth":
          return not profile["bluetooth"]
      if category == "modules":
          if path.endswith("/8821cs.ko"):   return not profile["wifi"]
          if path.endswith("/rtl_btlpm.ko"): return not profile["bluetooth"]
      return False
  ```
- 分类只认 4 个固定小节标题（`tools/prepare_stock.py:461-471`）：`wifi`、`bluetooth audio stack`、`kernel modules`、其余全归 `required`。

**为什么阻碍多设备**：`omission_allowed()` 的语义是"**这块板有没有 wifi**"，
而不是"**这块板的 wifi 栈由哪些文件组成**"。A133 的 WiFi 是另一套驱动（不同 soname、
不同 daemon、不同 firmware 目录），既不是"H700 的清单 + 删几条"，也不是
"H700 的清单 + 加几条"——**基线本身就不同**。

更硬的一点：`4.9.170` 是**内核版本号**，写死在 harvest 路径里。厂商内核一升级，
这两条路径就指向不存在的文件，`verify_harvest` 会以
`prepared harvest is missing required paths` 失败（`tools/verify_harvest.py:19-25`）——
失败信息不会告诉维护者"内核版本变了"，只会说"缺文件"。

### P0-3 — `src/` 的内核补丁以"内核 banner 字符串"做 ABI 校验

**事实**：`src/h700-speaker-amp/h700_speaker_amp.c:268-274`

```c
if (strcmp(init_uts_ns.name.release, H700_KERNEL_RELEASE) ||
    strcmp(init_uts_ns.name.version, H700_KERNEL_VERSION)) {
    ...
}
if (!banner || strcmp(banner, H700_KERNEL_BANNER) || !stub || ...
```

`H700_KERNEL_RELEASE/VERSION/BANNER` 由 `tools/audio_module.py:93-97` 在构建时从
**厂商内核 Image 的字节里**提取并生成头文件；8 个私有符号偏移来自
`src/h700-speaker-amp/profiles.json`（`tools/audio_module.py:98-101`）。

`profiles.json` 的 11 条是 **11 个互不相同的内核 Image**：

```sh
python3 -c "
import json,collections
d=json.load(open('src/h700-speaker-amp/profiles.json'))
print(len(d), len({v['image_sha256'] for v in d.values()}), len({v['config_sha256'] for v in d.values()}))"
# 11 11 3      → 11 个内核，3 个 config，11 组不同的符号偏移
```

**为什么阻碍多设备**：这不是"板级配置"，这是**内核 ABI 强绑定**。
每一台设备都要：审计它的 ASoC 布局 → 从 Image 里定位 8 个私有符号 → 写进
`profiles.json`。`tools/audio_module.py:7-10` 的 docstring 自己承认了这一点：

> An import CRC check alone cannot validate private ASoC layouts. profiles.json
> is a reviewed allowlist of exact Images; refreshing firmware requires auditing
> those layouts and the codec callbacks before adding a new Image hash.

也就是说：**每次厂商固件刷新 = 一次人工二进制审计**。11 台设备意味着 11 份这样的债务，
而且它们和发行版发版节奏绑在一起（`build-rootfs.sh:42` 每次 rootfs 构建都跑
`build-audio-module.sh`）。

### P0-4 — `devices.json` 字段太少，真实差异外溢到代码里

**事实**：`tools/device_profile.py:14-25` 定义了 10 个必填字段，全部是：
`id`、`model`、`stockmod_prefix`、`baseos_device`、`model_string`、
`bootlogo_width/height`、`panel_rotation_ccw`、`wifi`、`bluetooth`。

11 条 profile 里，**去掉身份字段后只剩 6 种不同组合**：

```sh
python3 - <<'EOF'
import json,collections
t=json.load(open("devices.json"))["targets"]
g=collections.defaultdict(list)
for p in t:
    k=tuple(sorted((a,b) for a,b in p.items() if a not in ("id","model","model_string","stockmod_prefix")))
    g[k].append(p["id"])
print(len(t), "profiles ->", len(g), "signatures")
EOF
# 11 profiles -> 6 signatures
# rg34xx ≡ rg34xxsp ; rg40xxh ≡ rg40xxv ; rg35xxplus ≡ rg35xxh ≡ rg35xxpro ≡ rg35xxsp
```

**为什么阻碍多设备**：6 种签名说明这个 schema 的**表达力**只有 6 档，
而真实差异至少有：面板几何、输入设备名、电源节点、音频 card/control、
显示后端、分区角色。这些差异现在都在代码里：

- 面板/显示：`src/fbsplash.c` 读 `BASEOS_PANEL_ROTATION_CCW`（`src/fbsplash.c:882`），
  但 bpp、密度、物理尺寸无处声明；
- 输入：`src/charger-wait.c:49-50` 按名字前缀 `axp` + 后缀 `-pek` 找电源键；
  `overlay/usr/sbin/boot-menu-held:8` 按 debugfs 文本匹配 `GPIO Key Menu`；
- 电源：`overlay/usr/sbin/baseos-charger:64` 写死 `axp2202-battery/work_led`；
- 音频：`overlay/usr/sbin/baseos-startup-sound:26-31` 写死 7 条 `amixer -c 0 sset`
  控制名（`digital volume`、`lineout volume`、`OutputL/M Mixer DACL/R`、`LINEOUT`、`SPK`）。

### P0-5 — `src/` 与 `overlay/` 里的分区号/设备节点是硬编码字面量

**事实**（分区号）：

| 位置 | 字面量 |
|---|---|
| `overlay/etc/init.d/rcS:41` | `/dev/mmcblk0p5`（rootfs slot A） |
| `overlay/etc/init.d/rcS:120` | `/dev/mmcblk0p6`（/data） |
| `overlay/etc/init.d/rcS:292-293,322` | `/dev/mmcblk1p1`、`/dev/mmcblk1`、`/dev/mmcblk0p7` |
| `overlay/etc/init.d/rcS:353,357` | `/dev/mmcblk0p7`（TF1 配置） |
| `overlay/usr/sbin/baseos-charger:11` | `/dev/mmcblk0p6` |
| `overlay/usr/sbin/baseos-update:30-31` | `DISK=/dev/mmcblk0`、`OWN_FAT=/dev/mmcblk0p7` |
| `overlay/usr/sbin/expand-storage:14-15` | `DISK=/dev/mmcblk0`、`CARD=/dev/mmcblk0p7` |
| `overlay/usr/sbin/usb-storage-mode:12-13` | `TF1_DATA=/dev/mmcblk0p7`、`TF2_DISK=/dev/mmcblk1` |
| `overlay/usr/sbin/baseos-startup-sound:8,13` | `/dev/mmcblk0p7` |
| `overlay/usr/sbin/baseos-boot-migrate:54-55,397-398` | `/dev/mmcblk0`、`/dev/mmcblk0p4` |
| `tools/gptslot.c:36-38` | `IDX_BOOT 3`、`IDX_ROOTFS 4`、`IDX_AFTER 5` |
| `tools/mkgpt.py:36` | `NUM_ENTRIES = 8` |
| `tools/prepare_stock.py:121` | `if entry_count != 8 or entry_size != 128` |

计数：

```sh
grep -rhoE '/(sys|proc|dev)/[A-Za-z0-9_./*-]+' overlay/ | sed 's/[0-9]\+/N/g' | sort -u | wc -l   # 37 种节点模式
grep -rc 'mmcblk' overlay/usr/sbin/* overlay/etc/init.d/rcS | grep -v ':0'                                     # 10 个脚本
```

**为什么阻碍多设备**：`tools/gptslot.c:3-5` 的注释把这件事说成"H700 boot chain 硬编码
`root=/dev/mmcblk0p5`"——这是**引导链的契约**，不是发行版的契约。一台用不同 U-Boot env
或不同分区序号的设备，`gptslot` 的 `IDX_BOOT=3 / IDX_ROOTFS=4` 直接不成立，
而 A/B 更新引擎（`overlay/usr/sbin/baseos-update`）整体建立在 `gptslot` 之上。

### P1-1 — Runtime 层目前是干净的；应用层不是

**事实（好的部分）**：`runtime/keyboardd` 完全不读硬件节点、不含板名：

```sh
grep -rn '"/sys\|"/proc\|"/dev\|h700\|H700\|anbernic' runtime/ | wc -l   # 0
```

它的能力模型是**按能力选择**、明确禁止按设备名匹配
（`runtime/keyboardd/keyboardd.go:41-53`）：

```go
// Capability describes an available input hardware class. Selection is driven by
// capabilities, never by device-name strings.
type Capability string
const ( CapTouch, CapDPad, CapGamepad, CapHardwareKeyboard )
```

**事实（坏的部分）**：应用侧不是。`docs/13-pocketjs-on-baseos.md:15-22` 记录的是
**应用自己探测**的结果表：

- `docs/13-pocketjs-on-baseos.md:19`：`DRM card not found in /dev/dri/card0..card1`（failure streak 6）
- `docs/13-pocketjs-on-baseos.md:20`：亮度节点"无 `/sys/class/backlight`、无 `/sys/class/leds`；存在 `/sys/class/disp/disp/attr`"
- `docs/13-pocketjs-on-baseos.md:16`：`event1 = ANBERNIC-keys`（按名字选 evdev）
- `docs/13-pocketjs-on-baseos.md:57`：compat shim 映射到"`/sys`、`amixer`、`wpa_cli`、`usb-storage-mode`"

**为什么阻碍多设备**：这三条（显示后端探测、按设备名选输入、直接读电源节点）
全部在**应用仓库**里。换设备就要改应用仓库——这直接违反"新增设备不改 PocketJS"。

**重要区分**：`keyboardd` 的 Capability 是**输入类别**（Touch/DPad/Gamepad/HardwareKeyboard），
由 provider 声明；`04-capability.md` 定义的 Capability 是**整机硬件有无**（wifi/touch/…）。
两者不是同一个概念，但**命名必须不冲突**——见 `04-capability.md` §6。

### P1-2 — 没有 Capability 声明；`wifi`/`bluetooth` 两个布尔值没有被运行时读取

**事实**：`BASEOS_WIFI` / `BASEOS_BLUETOOTH` 在构建时写进 `/etc/baseos-release`
（`build-rootfs.sh:129`），但**运行时没有任何脚本读它们**：

```sh
grep -rn 'BASEOS_WIFI\|BASEOS_BLUETOOTH' overlay/ | wc -l    # 0
grep -rn 'BASEOS_WIFI\|BASEOS_BLUETOOTH' . --include='*.sh' --include='*.py' --include='*.c' | grep -v '^./build-rootfs.sh'
# 只有 tests/test-frontend-session.sh 的 fixture 和 validate-on-device.sh 的比较
```

也就是说：能力被**烘焙进镜像**了，但唯一的使用者是"构建时的 harvest 裁剪"
（`tools/prepare_stock.py:489-499`）和"测试脚本的断言"。
运行时没有任何组件能回答"这台机器有没有蓝牙"。

`validate-on-device.sh:72-76` 只能靠**副作用**判断：

```sh
if [ "$BASEOS_EXPECTED_WIFI" = 1 ]; then
	chk "wifi module loaded (8821cs)"  "grep -q 8821cs /proc/modules"
	chk "wifi interface (wlan0)"       "test -d /sys/class/net/wlan0"
else
	chk "wifi legitimately absent"     "! grep -q 8821cs /proc/modules && ! test -d /sys/class/net/wlan0"
fi
```

### P1-3 — 没有 Feature 概念：能力与行为混在同一批布尔值里

**事实**：`wifi=true` 同时被用来回答两个不同问题：

1. "这台机器有没有 WiFi 硬件"（`devices.json` 语义）
2. "harvest 要不要收 `wpa_supplicant`/`8821cs.ko`"（`tools/prepare_stock.py:490-496`）

而"能干什么"这一类问题**完全没有表达**：能否做 BT sink/source、音量能否硬件控制、
能否旋转、能否 suspend、能否 RTC 唤醒。当前这些全部由**代码路径**隐含决定：

- suspend：`docs/05-runtime-power-network.md:16` — 前端直接写 `mem` 到 `/sys/power/state`；
- RTC 唤醒：只在实验记录里出现过一次（`docs/12-kernel-gzip.md:233`："woke on an RTC alarm"），
  发行版没有任何接口；
- 硬件音量：`src/charger-wait.c:14-16` 用 `DISP_LCD_SET_BRIGHTNESS` ioctl 调**亮度**，
  `overlay/usr/sbin/baseos-startup-sound:26-31` 用 `amixer` 调**音量**——两条完全不同的路径，
  应用层无法知道哪条存在。

### P1-4 — 没有 per-target 测试矩阵

**事实**：

- `build-all.sh:60-83` 对每个 target 跑同一串步骤（rootfs → qemu → native → image → update），
  但 `test-boot-qemu.sh` 是**通用 aarch64 virt 内核**（`test-boot-qemu.sh:4-6` 注释：
  "Hardware steps ... fail gracefully by design; this validates the init plumbing, not the drivers"）。
- 54 个 `tests/` 文件里，只有 `tests/test-baseos-config.sh:92` 遍历 `devices.json` 的全部 target；
  其余都是"当前这块板"的 fixture。
- 唯一区分 built / device-verified 的地方是 `validate-on-device.sh`，它需要**真机 + IP**
  （`validate-on-device.sh:5-7`），且内部断言写死 H700 节点：
  `validate-on-device.sh:50`（`mali_kbase`）、`:51`（`/dev/mali0`）、
  `:67`（`axp2202-battery/capacity`）、`:70`（`axp2202-battery/moto`）、
  `:88`（`h700_late_usb`）。

**为什么阻碍多设备**：`validate-on-device.sh` 本身**就是**一个 H700 专用脚本，
它的断言集合等于"H700 应有的样子"。第 12 台设备要么改这个脚本（板名进发行版根目录），
要么没有验收手段。

### P2-1 — 同一 target id 被三处以不同规则枚举

**事实**：

| 位置 | 枚举方式 | 加入 `rg50xx` 的后果 |
|---|---|---|
| `devices.json` | 手写数组 | 加一条即可 |
| `tools/boot_payload.py:19` | **硬编码 11 元组** | 必须手改，否则 `unsupported model` |
| `experiments/h700-boot-speed/native/build.py:99` | `sorted(compatibility).index(target) + 1` | 自动重编号 |

已验证：当前两者**恰好相等**，但机制不同：

```sh
python3 -c "
import json,sys; sys.path.insert(0,'tools')
from boot_payload import MODEL_IDS
c=json.load(open('experiments/h700-boot-speed/evidence/compatibility.json'))['targets']
print(MODEL_IDS == {t:i+1 for i,t in enumerate(sorted(c))})"   # True
```

**风险**：`MODEL_IDS` 是**写进引导协议**的整数（`tools/boot_payload.py:64` 把它
`struct.pack_into` 进 512B 描述符）。`build.py` 的算法是"按字母序排名"，一旦新增的
board id 排在中间（如 `rg50xx` < `rgcubexx`），**已有设备的 model id 会全部位移**，
而 `native_abi_id()` 把 `model_id` 算进 ABI 哈希（`tools/boot_payload.py:41`）——
已装机器的 fast loader 会全部失配。这是**协议级**的隐患，不是代码风格问题。

### P2-2 — 板名出现在"通用"文档里，新维护者会误当发行版事实

**事实**：`docs/` 里 15 篇文档中，`docs/00-boot-chain-and-partitions.md:13` 写
"The geometry below is the normalized **H700** layout"——把一块板的分区几何写成
"the" layout。`docs/08-usb-adb-and-otg.md:3` 写 "provides cable-based USB access
on **H700** devices"。

**为什么阻碍多设备**：文档是唯一能约束"第 51 台设备"时行为的载体。如果
"分区几何 = H700 几何"被当成事实，新设备就会默认套用 8 条目 GPT
（`tools/prepare_stock.py:121` 强制 `entry_count == 8`），而这类设备一旦 GPT 形状不同
就在 prepare 阶段被拒。

### P2-3 — `work/` 混放"厂商输入"与"构建产物"

**事实**：`tools/kernel_abi.py:298`、`tools/lib_image.py:40` 都直接读
`ROOT / "work" / target`；`build-rootfs.sh:18`、`build-image.sh:34` 同样。
`work/` 在 `.gitignore:12` 里。

**为什么阻碍多设备**：BSP 缓存（厂商输入）与构建产物无法单独清理/共享；
`cache-pack.sh` 不得不用"整段 zstd 流 + 固定成员顺序"来压缩 11 台设备的输入
（`cache-pack.sh:13-18`），注释写明"targets share most of their bytes ... collapses
~2.9 GB to ~133 MB"。这说明**共享的是字节，不是结构**——结构上的复用为零。

---

## 3. 量化总结

### 3.1 "新增一台设备要碰几个地方"

以 `docs/14-trimui-smart-pro-port.md:19-58` 自述的步骤为准（该文档已经承认了这个问题）：

| 步骤 | 文件 | 层 |
|---|---|---|
| 1 | 厂商 `.img` → `prepare-stock.sh` | BSP 输入 |
| 2 | `devices.json` 加 profile | 发行版根目录 |
| 3 | `manifest/harvest.list` 另开一份 | 发行版根目录 |
| 4 | `overlay/etc/init.d/rcS` 加 SoC 分支 | **通用启动脚本** |
| 5 | `src/<soc>-*` 新目录 + `profiles.json` | 内核补丁 |
| 6 | PocketJS 侧改探测 | **另一个仓库** |
| 7 | 测试 | 发行版根目录 |

`docs/14:21` 甚至要求 profile "必须包含：`baseos_device`、`boot_prefix`、`bootlogo`、
`capabilities`、`harvest`、`layout`"——但 `devices.json` 的 schema **没有** `boot_prefix`、
`capabilities`、`harvest`、`layout` 这四个字段（`tools/device_profile.py:14-25`）。
**文档已经在描述一个不存在的 schema。** 这是审计里最直接的"设计债证据"：
需求已经溢出，实现没有跟上，文档只好自己发明字段。

### 3.2 一致性的真实成本

11 台设备 × 5 张表 = 55 处手工登记。**零处**交叉校验。
新增 1 台设备 = 5 处新增 + 3 处代码分支 + 1 个应用仓库改动。

外推到 50 台：250 处手工登记。以"每处每年因厂商固件刷新需要复核一次"计，
每年 250 次人工核对——**这正是"无法长期维护"的定量含义**。

---

## 4. 审计结论

| # | 结论 | 证据位置 |
|---|---|---|
| 1 | 板级事实存在 5 份独立副本，零交叉校验 | §1（T1–T5） |
| 2 | `overlay/` 39 个文件里 14 个含板名/SoC 名 | §2 P0-1 |
| 3 | harvest 清单的裁剪维度是"有无 wifi"，不是"栈组成" | `tools/prepare_stock.py:489-499` |
| 4 | 内核补丁靠 banner 字符串校验，11 台 = 11 份二进制审计债 | `src/h700-speaker-amp/h700_speaker_amp.c:268-274`、`profiles.json` |
| 5 | profile schema 表达力只有 6 档，真实差异外溢到 6 个代码位置 | §2 P0-4 |
| 6 | 分区号/设备节点以字面量形式散落在 10+ 个脚本 | §2 P0-5 |
| 7 | Runtime 层干净；应用层自己探测硬件 | §2 P1-1 |
| 8 | Capability 被烘焙但无人读取；Feature 完全缺失 | §2 P1-2, P1-3 |
| 9 | 无 per-target 测试矩阵；唯一的真机验收脚本是 H700 专用 | §2 P1-4 |
| 10 | model id 枚举存在协议级位移风险 | §2 P2-1 |

下一步：`02-bsp-boundary.md` 定义 BSP 边界，`03-dal.md` 定义 DAL，
`04`/`05` 定义 Capability/Feature，`06` 定义 `baseosctl`，`07` 给出可独立合并的迁移步骤。
