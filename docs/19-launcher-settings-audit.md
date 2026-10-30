# 19 — 启动器设置项审计（BaseOS / RG34XX）

旧版设置界面里很多开关在 BaseOS 上是空壳：它们调用 ROCKNIX 的
`rocknix-settings` / `heya-control` / `rocknix-services` / `systemctl`，这些在
BaseOS 上要么不存在，要么指向不存在的内核节点。本文记录每一项的真实状态、
修法，以及仍然缺失的能力。

## 逐项状态

| 设置项 | 界面动作 | BaseOS 实情 | 处理 |
|---|---|---|---|
| 亮度 | `CONTROL brightness` | 无 `/sys/class/backlight`；`heya-control brightness` 写入无效 | 桥接直接写 `/sys/class/disp/disp/attr/enhance_bright`（0–255，最低 10） |
| 音量 | `CONTROL volume` | mixer 控件名是 `LINEOUT`，不是 `Master` | `LEVEL/CONTROL volume` 依次尝试 Master、LINEOUT、Playback、DAC |
| Wi-Fi | `CONTROL wifi` | `wpa_supplicant` 从未启动，`rocknix-settings` 不存在 | 桥接按需拉起 supplicant，新增 `WIFI scan/connect/status/off` |
| 蓝牙 | `CONTROL bluetooth` | 只有 `bluetoothctl`，**没有 `bluetoothd`/bluez** | 移除开关；要恢复必须先给 BaseOS 加 bluez 包 |
| 屏幕超时 | `SLEEP <timeout>` | 写 `/storage/.config/pocketjs/runtime.conf` 失败（目录不存在），`systemctl try-restart` 无 systemd | 桥接先建目录；`baseos-screen-idle` 每秒重读该文件，实测 10 秒精确熄屏 |
| 语言 | `LANGUAGE` | 正常（写 `/storage/pocketshell/launcher/settings.json`） | 保留并提到设置首页 |
| SSH | `SERVICE ssh.enabled` | `dropbear` 存在，shim 能真正起停 | 保留 |
| ADB over USB | `SERVICE adbusb.enabled` | shim 拒绝切换（会断当前调试会话） | 只读显示 |
| samba/syncthing/http/ftp/rsyncd/telnet/devbridge | 同名键 | 无守护进程 | 从界面移除 |

## 仍然缺失（需要单独工作）

1. **蓝牙**：需要把 bluez（`bluetoothd` + dbus 依赖）打进 rootfs，或改为按需
   起 `bluetoothd`。当前 `bluetoothctl` 单独存在但没有守护进程，任何扫描/配对
   都不可能成功。
2. **系统更新**：旧版有“更新”入口。BaseOS 的 `baseos-update` 已能识别卡上的
   `.bosupd`，可以增加一个 `UPDATE status|apply` 桥接命令暴露到设置里。
3. **主机名 / 时区**：可写 `/storage/baseos.conf`（重启生效），时区需要
   `/etc/localtime` 可写或 tzdata 目录。
4. **存储管理**：格式化/扩容目前只有 `expand-storage` 脚本，未暴露到 UI。

## 验证命令

```sh
# 亮度
echo 60 > /sys/class/disp/disp/attr/enhance_bright; cat /sys/class/disp/disp/attr/enhance_bright
# 音量
amixer sget LINEOUT | tail -2
# Wi-Fi
wpa_cli -i wlan0 scan; wpa_cli -i wlan0 scan_results
# 熄屏
printf '[sleep]\ntimeout = 10s\n' > /storage/.config/pocketjs/runtime.conf
#   静置 10 秒后：cat /sys/class/disp/disp/attr/enhance_bright  → 0 0
```

## 应用列表审计

`launcher-catalog.ts` 里的 17 个条目只有 `terminal` 能在 BaseOS 运行。其余要么
调用不存在的 `/usr/bin/heya-tool`、`/usr/bin/evtest`、`mc`、`nano`、`XMPlayer`、
`pocketshell-games`、`cloud-backup`，要么桥接 `LAUNCH` 依赖 `systemd-run`。它们
被 `RUNNABLE` 集合挡住，不再出现在界面里；等对应二进制进 rootfs 后再逐个放行。
