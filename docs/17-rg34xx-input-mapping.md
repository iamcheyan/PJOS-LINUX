# 17 — RG34XX 按键映射（PocketJS evdev 层）

BaseOS 在一张 RG34XX 上运行 PocketJS 启动器时，曾出现**实体 A/B 互换**以及
**Start/Select、X/Y、L1/R1、L2/R2、Menu 无响应或功能错位**。根因不在 PSOS 内核，
也不在启动器界面，而在 PocketJS 的 Linux evdev 解码表：它按 ROCKNIX mainline
H700 设备树编写，而 BaseOS 启动的是**厂商 4.9 设备树**，两套 `linux,input-code`
分配不同。

## 1. 证据：本机设备树

`soc@03000000/gpio_keys` 下每个按键都有厂商给出的 label 与 code（本机实测）：

| 节点 | 实体按键 | code | 常量 |
|---|---|---|---|
| `keyA` | A | `0x130` | `BTN_SOUTH` |
| `keyB` | B | `0x131` | `BTN_EAST` |
| `keyX` | X | `0x132` | `BTN_C` |
| `keyY` | Y | `0x133` | `BTN_NORTH` |
| `keyL1` | L1 | `0x134` | `BTN_WEST` |
| `keyR1` | R1 | `0x135` | `BTN_Z` |
| `keySEl` | Select | `0x136` | `BTN_TL` |
| `keyStart` | Start | `0x137` | `BTN_TR` |
| `keyMenu` | Menu | `0x138` | `BTN_TL2` |
| `keyL2` | L2 | `0x13A` | `BTN_SELECT` |
| `keyR2` | R2 | `0x13B` | `BTN_START` |

对照 ROCKNIX mainline 的 `sun50i-h700-anbernic-rg35xx-plus.dts`（RG34XX 的父设备树），
`BTN-A` 是 `BTN_EAST`、`BTN-B` 是 `BTN_SOUTH` —— **与厂商表正好相反**。上游
PocketJS 把 `304` 解成 CROSS（取消）、`305` 解成 CIRCLE（确认），于是按住实体 A
会触发"返回"，表现为 A/B 反了；`310/311`（本机是 Select/Start）被当成 L/R 扳机，
`306/312/314/315` 完全不在解码表里，因此那些键等于死键。

## 2. 修法

`src/apply-pocketjs-input.py` 在构建期改写 pinned PocketJS 的
`platforms/linux/evdev/src/lib.rs`，用上表把 code 映射到 PocketJS 的按钮位：

```
304 → CIRCLE(A，确认)      305 → CROSS(B，取消)
306 → SQUARE(X)            307 → TRIANGLE(Y)
308 → LTRIGGER(L1)         309 → RTRIGGER(R1)
310 → SELECT               311/312 → START
314 → ZL(L2)               315 → ZR(R2)
```

脚本同时补齐 musl 目标的 ioctl 可移植性（`request(...) as _`），并在锚点不匹配时
**直接失败**，避免上游版本升级后静默发布未打补丁的运行时。键盘别名（方向键、
Enter/Space/Z/X）保持原有语义不变。

## 3. ABI：必须是 musl 静态

`build-rootfs.sh` 装进 SYSTEM 的运行时来自 `work/pocketjs-runtime/pocket-linux-kms`，
必须满足设备 glibc 上限：BaseOS 是 **glibc 2.35**，而 ROCKNIX 交叉工具链产出的
二进制要求 **GLIBC_2.44**，在设备上直接报
`version 'GLIBC_2.44' not found` 无法启动。因此运行时用
`build-pocketjs-runtime-musl.sh` 构建（arm64 Debian 宿主 + `aarch64-unknown-linux-musl`
静态目标，`crt-static`），与设备上原本可用的二进制同一 ABI。

宿主必须用 glibc 镜像：`rquickjs-sys` 的 bindgen 会 `dlopen` libclang，静态 musl
宿主做不到（报 `Dynamic loading not supported`）。

## 4. SYSTEM 如何让它生效

前端本身放在可写的 `primary` 分区（`/mnt/sdcard/System/`），只更新 SYSTEM 不会
改动它。因此 `frontend-session` 在启动外置前端之前：

1. 比较 `/usr/share/baseos/pocketjs/pocket-linux-kms` 与卡上副本；
2. 不同则复制到同目录临时文件、`chmod`、**读回比对**、再 `mv` 原子替换；
3. 任一步失败就保留卡上原文件并在启动日志记录，绝不留半截可执行文件。

于是 `baseos-update` 写入的 A/B SYSTEM 槽同时带来新的输入解码器，且回滚槽会带回
旧运行时。

## 5. 验证

```sh
# 运行时 ABI 与 profile 接纳
adb shell /mnt/sdcard/System/pocketjs/bin/pocket-linux-kms --help
adb shell /mnt/sdcard/System/pocketjs/bin/pocket-linux-kms \
  --package /mnt/sdcard/System/pocketjs/apps/boot.pocket --check

# 映射回归（宿主，6 项解码器单测）
cargo test -p pocket-linux-evdev

# 设备侧：实体按键逐个按下，确认启动器行为与按钮语义一致
```

`--check` 必须打印 `package admitted: rocknix-h700-kms`；运行时与 `.pocket` 是
profile 配套关系，替换其一时必须同时确认接纳。
