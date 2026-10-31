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
