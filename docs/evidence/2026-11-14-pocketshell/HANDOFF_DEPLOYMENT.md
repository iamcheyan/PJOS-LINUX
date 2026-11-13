# RG34XX 固件交付与实机部署交接文档

- **构建产物日期**：2026-11-14 07:18 (JST)
- **目标设备**：BaseOS RG34XX (Allwinner H700, 720×480 面板, 主机名 `rg34xx`)
- **交接标识**：`PJOS_FINAL_HANDOFF_ORDERED_20261114`

---

## 一、 最新可分发交付物与校验和

所有交付物均基于最新提交（`pocketshell: 94244be`, `PJOS-LINUX: 17d85f1`）编译生成：

| 交付文件 | 大小 | 时间戳 | 说明 |
| :--- | :--- | :--- | :--- |
| `work/rg34xx/baseos-rg34xx.img` | 1,498,415,104 字节 (1.4 GB) | 07:08 | 官方完整 GPT 分区镜像 (Slot A/B, Ext4 rootfs) |
| `work/rg34xx/baseos-rg34xx-1.5.3.img.zip` | 125,524,809 字节 (120 MB) | 07:18 | 包含上述当前镜像的可分发压缩包 (重新生成) |
| `work/rg34xx/baseos-rg34xx-1.5.3.bosupd` | 91,688,960 字节 (88 MB) | 07:08 | 官方 OTA 增量更新包 (Decompressed slot SHA256 校验通过) |
| `work/rg34xx/rootfs.tar` | 292,556,800 字节 (279 MB) | 07:07 | 完整根文件系统存档 (已通过 GPU 模块瘦身与闭包检查) |

### 核心程序 `boot.pocket` 校验核对
经 `/usr/sbin/debugfs` 从当前 `baseos-rg34xx.img`（Inode 1136）直接 dump 提取校验，与本地源码及暂存包完全一致：
- **SHA-256**：`f2eddd4eee3767b9b4cf4438f8c8c72eee951500c9c87f67bbc563487c4e2c41`
- **文件大小**：56,649,832 字节

---

## 二、 当前设备连通性探测（物理离线记录）

在 2026-11-14 07:19 执行了实时通道探测：
1. **USB ADB 探测**：
   - 执行 `adb devices -l`：未发现设备（`List of devices attached` 为空）。
   - 宿主机未枚举到 USB `18d1:4e42` 控制器。
2. **Wi-Fi SSH 探测**：
   - 探测历史已知设备 IP `<device-lan-ip>`：100% 丢包（未通电或未接入无线局域网）。
   - 局域网存活主机均非目标掌机。

**结论**：实体设备当前处于物理离线/未通电状态。按规范严格保留客观离线事实，绝不伪造部署与真机测试记录。

---

## 三、 部署前置条件

1. **TF 卡刷机前置条件**：
   - 准备一张 MicroSD / TF 卡（建议 16GB 以上）。
   - 插入读卡器并确认目标设备节点（如 `/dev/sdX` 或 `diskN`）。注意刷机会格式化整卡。
2. **在线部署前置条件（ADB 优先）**：
   - 掌机插入 MicroSD 卡并接通 Type-C 数据线开机。
   - 确认宿主机识别到 USB 设备：`adb devices -l` 出现设备序列号且状态为 `device`。
3. **Wi-Fi 备援部署前置条件**：
   - 掌机接入与控制端相同的局域网。
   - 确认 SSH 端口 22 开放，通过 `ssh root@<device-ip>` 可以正常建立会话。

---

## 四、 确切部署命令

### 方案 A：全新刷卡（推荐整机全新部署）
使用项目官方刷卡脚本将刚生成的完整镜像写入 TF 卡：
```bash
cd ~/development/PJOS-LINUX
# 查看可用磁盘
lsblk
# 执行刷卡（将 /dev/sdX 替换为实际 TF 卡节点）
./flash-card.sh rg34xx /dev/sdX
```

### 方案 B：在线 OTA 更新包升级（掌机在线时推荐）
当掌机已开机并连通 ADB 或 SSH 时，直接推送 `.bosupd` 并在设备端执行原生更新：
* **通过 USB ADB 执行**：
  ```bash
  cd ~/development/PJOS-LINUX
  adb push work/rg34xx/baseos-rg34xx-1.5.3.bosupd /storage/
  adb shell "baseos-update /storage/baseos-rg34xx-1.5.3.bosupd && reboot"
  ```
* **通过 Wi-Fi SSH 执行**：
  ```bash
  cd ~/development/PJOS-LINUX
  sshpass -p "$PJOS_DEV_PW" scp work/rg34xx/baseos-rg34xx-1.5.3.bosupd root@<device-ip>:/storage/
  sshpass -p "$PJOS_DEV_PW" ssh root@<device-ip> "baseos-update /storage/baseos-rg34xx-1.5.3.bosupd && reboot"
  ```

### 方案 C：应用与运行时脚本化部署（快速热替换）
如仅需部署最新启动器及配套库：
```bash
cd ~/development/pocketshell
# ADB 方式
./scripts/deploy-rg34xx.sh
# 或 SSH 方式
PJOS_DEVICE_IP=<device-ip> PJOS_DEV_PW=<password> ./scripts/deploy-ssh.sh
```

---

## 五、 设备上线后验证清单与指令

设备开机并升级完成后，执行以下步骤核验真实硬件行为：

1. **版本与系统核查**：
   ```bash
   adb shell "hostname; uname -a; cat /etc/os-release"
   ```
   - 预期输出：`rg34xx`，Linux 内核 `4.9.170`，`BASEOS_VERSION=1.5.3`。

2. **活动 Framebuffer 真实抓屏核查**：
   `/dev/fb0` 为 720×960 双缓冲，需根据 `pan` 抓取有效帧：
   ```bash
   adb shell "cat /sys/class/graphics/fb0/pan"
   # 读取偏移量（例如 0,480）
   adb shell "dd if=/dev/fb0 of=/tmp/frame.raw bs=4096 count=675"
   adb pull /tmp/frame.raw /tmp/frame.raw
   convert -size 720x960 -depth 8 bgra:/tmp/frame.raw -crop 720x480+0+480 +repage docs/evidence/2026-11-14-pocketshell/device-live-verified.png
   ```

3. **功能性实操核对**：
   - **主页**：观察卡片轮播底部的环境高斯发光背景，确认无真实照片、全矢量封面。
   - **音量 / 亮度 OSD**：按音量滚轮或按键，屏幕顶部弹出 Material 胶囊 OSD 实时反馈；长按 L2/R2 平滑增减背光。
   - **终端 & 虚拟键盘**：启动终端，输入框激活全宽 720px 键盘，测试按键、输入 `uname -a` 或 `date`、回车执行并显示命令返回。
   - **Kanade 视频播放器**：播放视频确认无明显卡顿；在主页单按 B 键提示「再按一次 B 退出应用」，连续双击 B 键弹出「退出 Kanade？」确认窗口，测试「取消」留存与「确认退出」返回启动器。
