# BaseOS 上首次跑起 PocketJS 启动器（2026-10-30）

设备：Anbernic RG34XX（H700，内核 4.9.170），系统 **Base OS 1.4.0**，卡上 `System/` 为 PocketJS 前端。
这些截帧都是从 `/dev/fb0`（720×480，32bpp）直接读出后转 PNG，不是重建的示意图。

| 文件 | 证明了什么 |
|---|---|
| `01-home-cards.png` | 卡片启动器出现在面板上：HOME 工作区，Terminal / Files / XMPlayer 三张卡，选中框在 Terminal；顶部 `WS 1/5 HOME`、Wi‑Fi/蓝牙/SSH/ADB/MTP、电量 100%；标题是日文「ターミナル」，说明日文字体与语言设置都生效 |
| `02-carousel-next.png` | 按右方向键后卡片焦点移动（轮播与按键链路可用） |
| `03-carousel-prev.png` | 按左方向键回到前一张 |
| `04-settings-real-values.png` | 设置页显示**真实状态**而非占位：Brightness 50%、Volume 100%、Wi‑Fi OFF、Bluetooth OFF、Timeout 30m、SSH ENABLED、页码 1/17 |
| `05-system-overview.png` | 系统页实时遥测：CPU 1512MHz / 52C、RAM 76/997MB (8%)、存储 0.1G/27.5G、`OS 1.4.0 (h700)`、`KERNEL 4.9.170 aarch64` |
| `06-settings-volume.png` | 调整音量后设置页数值随之变化（状态是活绑定，不是静态渲染） |
| `07-autostart-after-reboot.png` | 重启后由 `frontend-session` 自动拉起启动器，无需人工干预 |

## 运行时事实

- 输出：`DRM unavailable ... trying framebuffer` → `display: fbdev (timer pacing)`
- 输入：`/dev/input/event1`（`ANBERNIC-keys`）
- 包准入：`package admitted: ... (rocknix-h700-kms)`
- 运行时：aarch64 **musl 静态**构建（`ELF 64-bit LSB executable, ARM aarch64, statically linked`，无 `GLIBC_*` 版本依赖）

## 还没做的

- Library 页能够打开，但内容索引尚未在 BaseOS 上跑通（扫描器仍是 Python 实现，BaseOS 无 `python3`）
- 游戏/媒体条目点击后只能提示 `No player configured`（BaseOS 上没有模拟器/播放器）

细节见 [docs/13-pocketjs-on-baseos.md](../13-pocketjs-on-baseos.md)。
