# 18 — 空闲自动关屏（只关背光）

BaseOS 在掌机上一直亮屏，和手机的使用习惯不符。`/usr/sbin/baseos-screen-idle`
在**没有输入达到设定时长**后把面板背光写 0，下一次任意按键立即恢复原亮度。

它只做一件事：写背光节点。不挂起、不停服务、不卸载存储、不降频，所以黑屏期间
播放、下载和前端渲染都继续运行 —— 按用户要求"只是屏幕不亮，别的不要影响"。

## 配置

按优先级读取：

| 文件 | 键 | 说明 |
|---|---|---|
| `/storage/.config/baseos/screen-idle.conf` | `timeout = 30s` | BaseOS 侧覆盖 |
| `/storage/.config/pocketjs/runtime.conf` | `[sleep]` 段 `timeout = 30s` | 启动器「屏幕超时」设置直接生效 |

取值沿用启动器的词表：`never`、`10s`、`30s`、`1m`、`5m`、`15m`、`30m`、`1h`。
**两者都没有配置时默认 30 秒**，新卡开箱即"像手机一样"自动熄灭。

`never` 表示不关屏（脚本不会留下半黑的面板）。

## 背光节点

BaseOS 没有 `/sys/class/backlight`。厂商 4.9 内核把面板亮度放在显示属性节点上，
脚本按候选列表探测（`/sys/class/disp/disp/attr/enhance_bright` 优先，其次
`lcd_bright`，最后退回 `backlight` class）。**找不到可写节点时只记日志并退出**，
不会去猜路径写坏别的属性。

启动时读一次当前亮度作为"常亮电平"保存；如果读到 0（例如上次异常关闭），
按 `max_brightness` 的一半恢复，避免把 0 当成常亮值而永久黑屏。

## 空闲检测

每个 `/dev/input/event*` 各起一个阻塞 reader（`dd bs=24 count=1`，一次恰好一个
`input_event`），读到事件就刷新 `/run/screen-idle.stamp`。evdev 支持多读者，
因此这不影响前端继续读取同一设备。主循环每秒比较时间戳与超时值，决定点亮或熄灭；
每 30 秒重新枚举一次设备，插拔手柄后也能被识别。

## 启动位置

`overlay/etc/init.d/rcS` 在启动音之后、`dev` 之前后台启动，USB 存储维护模式跳过
（那时屏幕由维护提示占用）。脚本由 `build-rootfs.sh` 一并 chmod 并纳入可执行断言。

## 验证

```sh
# 设备上：确认守护进程与节点
pgrep -af baseos-screen-idle
cat /tmp/baseos-screen-idle.log          # 记录所用节点、常亮电平、熄灭/恢复时刻

# 静置 30 秒后
cat /sys/class/disp/disp/attr/enhance_bright   # 期望 0
# 按任意键后
cat /sys/class/disp/disp/attr/enhance_bright   # 期望回到启动时的电平
```
