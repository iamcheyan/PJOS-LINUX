# Wi-Fi 与已安装程序的启动（系统侧）

这份文档只讲系统做什么、为什么这么做。界面侧的接口契约在 `pocketshell` 仓库的
`docs/WIFI-BRIDGE-CONTRACT.md`，两边以那份为准。

## 1. Wi-Fi 的落点

| 东西 | 位置 |
|---|---|
| supplicant 启动 | `rcS`（开机）+ 桥里的 `wifi_ensure()`（按需） |
| 配置与已保存网络 | `/storage/.config/wpa_supplicant.conf`（`update_config=1`） |
| 客户端工具 | `/storage/System/compat/bin/wpa_cli`、`wpa_supplicant`、`udhcpc` |
| 界面 | 启动器（`pocketshell`）；系统不带任何 Wi-Fi 界面 |

启动器说 `WIFI\tconnect\t<ssid>\t<psk>`，桥执行：

```
wpa_cli -i wlan0 add_network
set_network <id> ssid "<ssid>"
set_network <id> psk "<psk>"      # 开放网络改 key_mgmt NONE
enable_network <id> / select_network <id> / save_config
轮询 status → COMPLETED 后 udhcpc 拿地址
```

**PSK 走 stdin 而不是 argv。** 早先的实现把密码作为 `wpa_cli` 的命令行参数，任何用户
`ps` 都能看到明文；现在整段脚本通过管道喂给 `wpa_cli` 的交互模式，参数表里只剩命令本身。
`wpa_cli` 若不支持 stdin 脚本，仍保留 argv 回退路径（有注释标记）。

### 返回值

`connected:<ssid>` / `need-psk` / `auth-failed` / `not-found` / `timeout` /
`error:<detail>`。`auth-failed` 的判据是 supplicant 把该网络标成 `DISABLED`
（密码错误后它会短暂禁用网络）；`not-found` 来自连接前的扫描比对。

### 其余命令

`WIFI\tdisconnect`、`WIFI\tforget\t<ssid>`（`remove_network` + `save_config`）、
`WIFI\tsaved`（`list_networks` 的 SSID 列）、`WIFI\tip`。

## 2. 已安装程序怎么启动

卡片上放包：`/storage/apps/<id>.pocket`（10 个移植好的程序已就位）。

启动器发 `LAUNCH\t<id>`，桥：

1. 校验 id 只含 `[A-Za-z0-9._-]` 且 `/storage/apps/<id>.pocket` 存在，否则 `error:missing:<id>`；
2. 把 id 写进 `System/pocketjs/active`；
3. 让出一个 0.4 s 后 `kill -9` 自己的后台进程 → supervisor 重启 `launch_frontend.sh`；
4. `launch_frontend.sh` 读到标记 → 用 `--package <该包>` 起运行时（仍走 admission 检查）；
5. 子包退出 → 删标记 → supervisor 再起启动器。

**为什么不让启动器自己 fork**：fbdev 只有一个，runtime 独占 `/dev/fb0` 并抢占输入；
两个运行时同时存在会互相涂屏、抢按键。让 supervisor 做唯一的进程所有者，切换就是一次
干净的“退出→重启”，失败也只是回退到启动器。

`APPS\tlist` 返回当前真正装着的 id 列表（每行一个），启动器用它决定显示哪些卡片。

## 3. 版本号

`/etc/baseos-release` 里除 `BASEOS_*` 外还有：

```
PJOS_SDK_VERSION=0.15.0     # 启动器包编译所用的 PocketJS SDK
POCKETJS_ABI=12             # runtime 导出的绑定代际
```

桥把这两项连同 `BASEOS_BUILD`、内核、型号一起给 SYSTEM 页，所以界面上能直接看到
`PocketJS 0.15.0 (abi 12)`，而不是一个笼统的名字。
