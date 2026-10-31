# 18 — 自动熄屏、电源键、SELECT+START 退出

三个「按了没反应」的问题，根因各不相同。这一页记录实测结论，别照着猜。

## 1. 自动熄屏失效：读事件的循环把「设备消失」当成「一直有人按键」

`/usr/sbin/baseos-screen-idle` 的模型很简单：每个 `/dev/input/event*` 起一个阻塞
`dd`，读到 **任意一个 24 字节 input_event** 就 `touch /run/screen-idle.stamp`；
主循环看 stamp 有多旧，超过 timeout 就把亮度写 0。

问题在 `dd` 失败的时候。原来的写法是：

```sh
while :; do
    timeout 3600 dd if="$dev" bs=24 count=1 of=/dev/null 2>/dev/null
    touch "$STAMP"        # ← 不管读没读到东西
done
```

设备节点消失（uinput 虚拟手柄退出、USB 键盘拔掉）之后，`dd` 立刻返回失败，
循环变成每秒上千次 `touch`。stamp 永远新鲜，熄屏永远不发生，同时白烧 CPU
（实测 `sys` 38%）。

现场证据（一台已经「不熄屏」的机器）：

```
$ tail /tmp/baseos-screen-idle.log
00:08:30 watching /dev/input/event3        ← uinput 设备出现
00:14:29 panel off after 10s idle
00:15:29 panel on after input
                                           ← 此后 11 分钟没有任何一行：stamp 被刷爆
$ ls /dev/input/event*
event0 event1 event2                       ← event3 已经不在了
$ top -b -n1 | head -4
CPU: 0% usr 38% sys ...                    ← 空转的读循环
```

修法：只有真的读到 24 字节才刷新 stamp；读失败先刹车，节点真没了就结束这个
reader，主循环把死掉的设备从 `READERS` 里删掉，插回来还能重新监听。
另外用 `/run/baseos-screen-idle.pid` 保证只有一个实例——前端重启时旧的会被替换，
不会叠出好几个互相抢面板的进程。

## 2. 电源键没反应：BaseOS 里根本没人监听 KEY_POWER

ROCKNIX 在 systemd 里把它交给 logind：

```
projects/ROCKNIX/packages/sysutils/systemd/package.mk
  sed -e "s,^.*HandlePowerKey=.*$,HandlePowerKey=suspend,g" ...
```

即短按 = suspend to RAM；`rocknix-power-key` 再处理「正在播放媒体」的情况：
媒体播放中就只关背光（`bl_power`）并 grab 手柄，让播放继续。

BaseOS 没有 systemd、没有 logind，也没有任何进程打开 `axp2202-pek`
（`/dev/input/event0`，`N: Name="axp2202-pek"`），所以按键事件被丢掉。
`/sys/power/state` 只有 `freeze mem`，H700 的 suspend/resume 不可靠，不能直接照抄
ROCKNIX 的 suspend。

新增 `/usr/sbin/baseos-hotkeys`（`src/baseos-hotkeys/main.go`，静态 aarch64，
CGO_ENABLED=0 交叉编译）：

| 动作 | 行为 |
|---|---|
| 短按电源键（< 2 s） | 面板关灯（亮度写 0）、写 `/run/panel.off` 标记；系统照常运行，正在播的音频/下载不受影响 |
| 再短按一次 | 恢复 `/run/panel.level` 里记下的亮度，删掉标记 |
| 任意手柄按键（睡眠期间） | 同样唤醒，恢复亮度（手感和掌机一致） |
| 长按电源键（≥ 2 s） | `/usr/sbin/baseos-poweroff`（真正的关机） |
| SELECT + START（400 ms 内） | `SIGTERM` 当前 PocketJS 运行时；`frontend-session` 会把它重新拉起来，等于「强制退出当前程序」回到启动器 |

标记文件是给 screen-idle 看的：`/run/panel.off` 存在时它完全不碰亮度节点，
避免「刚关灯又被自动熄屏循环点亮」的打架。

## 3. 面板亮度节点不是单个数字

`/sys/class/disp/disp/attr/enhance_bright` 的内容是 `"127 127"`（两个字段）。
用 `Atoi(整个文件)` 读会失败，第一版 daemon 因此把「关灯」误判成「灯亮着」，
连按电源键只会反复关灯。现在取第一个字段。

## 4. 部署位置：卡上优先，镜像兜底

- 镜像里（本仓库 overlay）：`/usr/sbin/baseos-screen-idle`、`/usr/sbin/baseos-hotkeys`，
  由 `/etc/init.d/rcS` 在 `USB_STORAGE_MODE=0` 时启动，按 `device/name`
  找 `axp2202-pek` 与 `ANBERNIC-keys` 两个节点。
- 卡上（可以不刷机就修）：`/storage/System/baseos-screen-idle`、
  `/storage/System/bin/baseos-hotkeys`。`System/launch_frontend.sh` 每次拉起前端时
  按 pidfile 结束镜像版，再启动卡上的版本——所以改行为只要换卡上的文件。

## 5. 实测记录（2026-10-31，RG34XX / BaseOS 1.5.2）

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 自动熄屏 | 静置 12 s 后 `cat enhance_bright` | `0 0`，日志 `panel off after 10s idle` |
| 任意键唤醒 | `sendkey /dev/input/event1 305 1/0` | 亮度回到 127，日志 `panel on after input` |
| 电源键关灯 | `sendkey /dev/input/event0 116 1/0` | `0 0` + `/run/panel.off` |
| 电源键开灯 | 同上再按一次 | 127，标记消失，日志 `power: screen on` |
| 睡眠中按键唤醒 | 关灯后 `sendkey ... 304` | 127，日志 `wake: panel on (level 127)` |
| SELECT+START | `sendkey event1 310 1` + `311 1` | 运行时 pid 消失，4 s 后新 pid 出现，日志 `combo: SELECT+START -> SIGTERM` |
| 设备消失后不空转 | 移除 uinput 设备后观察 stamp 与 CPU | stamp 不再刷新，reader 退出，无空转 |
| 长按关机 | 未做（会真的断电，留待用户手动验） | — |

## 6. 第二次修正：真正的「关灯」不是那个亮度节点

第一版把 `enhance_bright` 写 0 当关屏，读回来是 `0 0`，但面板**亮度一点没变**——那个节点
是图像增强参数，不是背光。用户实测「按了没反应」就是这么来的。

H700 的 vendor 内核没有 `/sys/class/backlight`，也没有 `bl_power`；能真正关断面板的是
framebuffer 的 **FBIOBLANK ioctl**（`/dev/fb0`，`FB_BLANK_POWERDOWN=4`）。新增
`baseos-panel off|on|level N`（`src/baseos-panel`，静态 aarch64）：`off` 发 ioctl，
失败才退回写亮度节点；`on` 发 `FB_BLANK_UNBLANK` 并恢复 `/run/panel.level`。

`baseos-screen-idle` 和 `baseos-hotkeys` 现在都优先调 `baseos-panel`，没有 helper 才退回旧路径。

### 还有一个坑：镜像里和卡上的 helper 会同时活着

rcS 启动镜像里的 `/usr/sbin/baseos-screen-idle`，`launch_frontend.sh` 又启动卡上的版本。
两个 idle 进程各有自己的 `blanked` 状态，互相把面板点亮，表现就是「永远不熄屏」。
现在 launch 脚本按 **cmdline** 杀掉所有同名进程（镜像版 + 卡版），再各启动一个卡版；
helper 自己还有 pidfile 单实例保护。

注意：`kill_matching` 的模式不能出现在你正在执行的 `adb shell` 命令行里，否则它会把自己
那个 shell 一起杀掉（试过，输出直接断掉）。

## 7. 最终方案：/dev/disp 的背光 ioctl（真关屏，4 秒开机不变）

前面所有弯路都记在上面，结论只有一条：**这颗 vendor 内核能关背光，只是不在 sysfs 上，而在
`/dev/disp` 的 ioctl 里**。

线索来自本仓库 `experiments/h700-boot-speed/uboot-trace-notes/emit.py`：vendor u-boot 的
`disp_ioctl` 用 `0x104/0x105` 做背光开/关。内核的 disp 驱动沿用同一套命令号：

| cmd | 名称 | 实测 |
|---|---|---|
| `0x103` | `DISP_CMD_LCD_GET_BRIGHT` | 返回 `50`（当前亮度，真实值） |
| `0x104` | `DISP_CMD_BACKLIGHT_ON` | 返回 0 |
| `0x105` | `DISP_CMD_BACKOFF_OFF` | 返回 0，背光真的断电 |

**参数形态是关键**：`ioctl(fd, cmd, 数值)` 一律 `EFAULT`/`EPERM`；必须传
`ioctl(fd, cmd, &{sel, value})` —— 两个 u32 的指针。改成指针之后三条命令全部正常。

`baseos-panel` 现在就是：

```go
args := [2]uint32{0, 0}
syscall.Syscall(SYS_IOCTL, fd, 0x105, uintptr(unsafe.Pointer(&args[0])))  // 关背光
syscall.Syscall(SYS_IOCTL, fd, 0x104, uintptr(unsafe.Pointer(&args[0])))  // 开背光
```

- 自动熄屏：`baseos-screen-idle` 超时后调 `baseos-panel off`（`timeout` 取
  `/storage/.config/baseos/screen-idle.conf` → 现在 1m）
- 电源键：短按走同一对 ioctl；长按 2 秒 `baseos-poweroff`；SELECT+START 杀前端
- 唤醒：`baseos-panel on` 开背光 + 刷新 `/run/screen-idle.stamp`，否则 idle 守护下一秒会再关

不需要换 mainline 内核，开机时间仍是前端 1.65 s 就绪。

### 仍未做

- 设置页的亮度滑条写的还是 `enhance_bright`（图像增强），没接到 `0x102 LCD_SET_BRIGHT`
  （直传数值时返回 EPERM，要再试指针形态）。
- 前端内置的「睡眠黑屏 overlay」保留着，作为背光开关失败时的兜底。
- 长按关机没在真机上验过（会真的断电）。
