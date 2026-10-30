# BaseOS / PocketJS ADB 现场取证（2026-10-30）

本目录是在 RG34XX 当前连接状态下经 HX90 的 ADB 读取所得，跳过 M6 的 TF 卡刷写/首启验证；未写入设备存储或系统分区。

## 本次新抓取

- [`01-library-current.png`](01-library-current.png)：从设备 `/dev/fb0` 读取的当前画面，裁出可见的 720×480 面板区域。显示 PocketJS 启动器的 Apps 页面，顶部为 `WS 1/5 HOME`，列表显示 GAMES 3、MUSIC 1、VIDEOS 1，并选中“今すぐスキャン”。这是设备实际 framebuffer 截图，不是重绘图。
- [`raw/framebuffer-720x960-bgra.raw.gz`](raw/framebuffer-720x960-bgra.raw.gz)：原始 framebuffer 数据（解压后 720×960、32bpp、BGRA），保留供复核。

## 同次 ADB 观测

- 设备：BaseOS 1.4.0，目标 RG34XX；内核 4.9.170（来自 `/etc/baseos-release` 与运行时信息）。
- ADB：HX90 上 `adb devices -l` 显示目标为 `device`。
- 启动器：`launch_frontend.sh` 与 `pocket-linux-kms` 进程正在运行；启动日志显示包准入成功，运行时因无 DRM 节点回退至 `/dev/fb0`，报告 `display: fbdev (timer pacing)`。
- Library 画面列出 6 项；本次未触发扫描、启动游戏或改变设置。
- 尝试用 ADB 输入事件切换页面时画面没有变化，因此本次不把重复帧冒充成其他页面，也未能重新抓到 HOME、Settings、System 等页面。

## 既有页面证据（不是本次重新抓取）

仓库已有 [首次运行截图集](../2026-10-30-baseos-first-boot/README.md)，其中包括 HOME、设置真实值、System 概览、音量变化和重启自启动的历史截图。那些是先前取证，不代表这些页面在本次抓取时重新显示或逐项复验。

## 采集边界

本次只读 ADB 查询与 framebuffer 读取；没有执行 `dd`、刷写、安装、`adb push` 到设备或修改 TF 卡。M6 物理卡验证仍跳过。