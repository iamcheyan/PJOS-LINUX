# RG34XX USB ADB 故障记录与恢复

## 设备与现象

- 设备：RG34XX，BaseOS 开发镜像；Wi-Fi SSH 地址 `<device-lan-ip>`。
- USB ADB 序列号：`<device-serial>`；USB VID/PID：`18d1:4e42`。
- 2026-11-12，Wi-Fi SSH 可登录，`/usr/sbin/adbd` 正常运行，但 Debian 上 `adb devices -l` 最初为空，设备端 UDC 状态为 `not attached`，configfs `g1/UDC` 为空。
- 设备没有 TCP 5555 监听是预期行为：此镜像仅开放 USB ADB。`adb connect <device-lan-ip>:5555` 返回拒绝不能作为 adbd 故障证据。

## 根因

设备的 `/etc/init.d/dev` 在启动时后台运行 `/usr/sbin/usb-gadget-adb setup`。此脚本创建 configfs gadget、挂载 FunctionFS、运行 `adbd` 并绑定 UDC，但不持续监控断连，也不强制切换 sunxi OTG role。

本次现场状态和启动日志表明 USB gadget 已经历连接后断开：

- `adbd` 进程存在，FunctionFS 已挂载，configfs 下 `g1` 及 `ffs.adb` 配置存在；
- `/sys/kernel/config/usb_gadget/g1/UDC` 最初为空，UDC `/sys/class/udc/5100000.udc-controller` 报告 `not attached`；
- `dmesg` 记录启动早期一次 `failed to start g1: -19`，之后 Android USB 状态到达 `CONNECTED`、`CONFIGURED`，随后 `DISCONNECTED`；
- 脚本注释说明 sunxi OTG manager 在 VBUS 断开时清除 UDC 绑定。后续接线可能被 OTG manager 判为 host role，用户态不能安全覆盖这个决策。

因此问题是 USB gadget/OTG 连接状态丢失，不是 `adbd` 进程崩溃或 Wi-Fi ADB 服务未启用。

## 本次恢复记录

在 RG34XX 已有 USB 供电、但当前 UDC 未绑定时，通过已验证的 Wi-Fi SSH 执行：

```sh
/usr/sbin/usb-gadget-adb setup
```

该命令按设备脚本既有逻辑重新配置并尝试绑定 gadget，不写 sunxi role 控制节点。随后状态变为：

```text
/sys/kernel/config/usb_gadget/g1/UDC: 5100000.udc-controller
/sys/class/udc/5100000.udc-controller/state: configured
```

Debian 主机验证：

```text
$ lsusb
Bus 002 Device 004: ID 18d1:4e42 Google Inc. Nexus 7 (debug)

$ adb devices -l
<device-serial>    device usb:2-1 product:occam model:Nexus_4 device:mako
```

因此在本次现场，重跑 setup 即恢复 USB ADB 枚举与 shell transport。

## 排障步骤

1. 先执行 `adb devices -l`；如果目标 serial 已处于 `device`，直接用 ADB 调试。ADB 不可用时使用 `AGENTS.md` 中记录的 `sshpass` 命令登录设备，并确认 `hostname` 为 `rg34xx`、`id` 为 `uid=0(root)`。裸 `ssh` 不会自动提供密码；不要使用 `BatchMode=yes` 验证密码登录。
2. 检查设备进程和 gadget：

   ```sh
   pidof adbd
   cat /sys/kernel/config/usb_gadget/g1/UDC
   cat /sys/class/udc/5100000.udc-controller/state
   grep 'usb-ffs/adb' /proc/mounts
   dmesg | grep -iE 'configfs-gadget|USB_STATE|functionfs'
   ```

3. USB-only ADB 不监听 TCP 5555；通过 Debian 的 `lsusb`、`adb devices -l` 验证有线枚举。
4. 如果 `adbd` 正常但 `g1/UDC` 为空，可先执行 `/usr/sbin/usb-gadget-adb setup`，再检查 UDC state 和主机 ADB 列表。本次设备现场已验证此恢复方式有效。
5. 若仍未枚举，接好 USB 数据线后重启设备，再检查。脚本规定的可靠流程是先连接主机线再开机；disconnect 后重启并保持线缆连接。

## 安全注意

不得通过排障脚本读取或写入以下 sunxi OTG role 文件：

- 写 `usbc0/otg_role` 会使写入进程永久卡在不可中断 D 状态；
- 读取 `usbc0/usb_device`、`usb_host`、`usb_null` 会触发 role 切换，可能卡死端口；
- 不要强行切换到 peripheral role，也不要添加无条件轮询重绑的常驻 watcher。USB-C 口必须继续支持正常 host 外设。下述增强只处理内核事件，并且仅在安全读回的 role 已经是 `usb_device` 时恢复。

详细设计和硬件约束见 [USB adb、mass storage 与 H700 OTG](08-usb-adb-and-otg.md)。本记录反映 2026-11-12 这台 RG34XX 的现场验证，不能代替其他 H700 型号的硬件验证。

## 设置开关与事件恢复增强（源码）

原有恢复只是一条手动 `setup`，没有保证后续热插拔自动恢复；旧的设置服务还拒绝关闭 ADB。现增加：

- `usb-gadget-adb status`：读持久策略，返回 `on`/`off`。开关状态与线缆是否插入分开判断。
- `usb-gadget-adb enable`：删除 `/data/no-adb`，每次都请求后台、有界的 setup；即使开关已经开启，重复开启仍可手动救援。不会开启 TCP 5555。
- `usb-gadget-adb disable`：创建 `/data/no-adb`，后台串行解绑并移除 ADB interface、停止 adbd。若先前组合了 mass storage，则保留原 LUN 并重新绑定 storage-only，不重新选择或挂载存储。
- setup 和开关应用共享 `/run/usb-adb-setup.lock`，开关先保存最新期望值，后台工作在拿到锁后重新读取，避免旧的开启请求覆盖后来的关闭。
- `rocknix-services set adbusb.enabled on|off`：供设置适配层调用；兼容旧 `toggle` 命令。
- `/sbin/hotplug`：内核原已配置此 helper 路径，但现场文件缺失。新增 helper 对 power-supply/UDC 事件进行条件恢复，检查 boot-ready、持久开关、既有 ADB function、空 UDC、USB online 和 `otg_role=usb_device`；不写 role、不操作 read-trigger 节点、不常驻轮询。`init.d/dev` 在首次 setup 完成后创建 ready 标记，防止早期冷插拔抢先选定 USB 模式。

### 部署路径

设备当前根分区读回为 `ext4 rw`，不需要为现场验证重新刷整张卡。先备份，再统一部署：

- `overlay/usr/sbin/usb-gadget-adb` → `/usr/sbin/usb-gadget-adb`
- `overlay/usr/sbin/hotplug` → `/usr/sbin/hotplug`（`/sbin` 链接到 `/usr/sbin`）
- `overlay/etc/init.d/dev` → `/etc/init.d/dev`
- `overlay/usr/share/pocketshell/System/compat/bin/rocknix-services` → `/storage/System/compat/bin/rocknix-services`
- 配合新版设置适配器的 `SETTING adb` 路由；该适配器由设置修复统一部署。

当前启动已完成时，安装后可创建 `/run/usb-adb-hotplug-ready` 激活后续事件恢复；新镜像在启动中自动创建。启用路径异步执行，短暂的开关状态与 transport 切换过程应分开验证。

### 验证与限制

2026-11-12 后续整合已部署上述脚本，并在 Wi-Fi SSH 保持在线时完成软件开关验证：`disable` 后状态 off、adbd 停止、主机 ADB 列表为空；`enable` 后状态 on、adbd 重启、UDC 为 configured，经过几秒主机重新枚举后恢复 `device`。真实物理拔插仍未验证。统一进度见 [故障与修复进度](25-rg34xx-debug-progress.md)。

自动测试：

```sh
sh tests/test-usb-gadget-adb.sh
python3 tests/test-usb-adb-hotplug.py
python3 tests/test-adb-service.py
```

覆盖初始组合、重复 setup、关闭/重开、无绑定时关闭、保留原存储 LUN、已开启时重复开启仍请求 setup，以及 host role/离线/未完成启动/开关关闭时不恢复。

**边界**：此改动保证符合条件的 device-role 事件会请求自动恢复，不承诺修正 vendor 内核把数据线判为 host role 的情况，也不承诺仅充电线可传数据。软件 off→on 已实测，实际插线即恢复仍需在 SSH 保持在线时做真实拔插测试；不要把本地测试通过写成物理拔插已经完成。
