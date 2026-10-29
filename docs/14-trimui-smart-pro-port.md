# TRIMUI Smart Pro (A133 Plus) Porting Guide to BaseOS

## Device Specifications
- **SoC**: Allwinner A133 Plus (Cortex-A53 @ 1.8-2.0GHz)
- **GPU**: PowerVR GE8300
- **RAM**: 1 GB LPDDR4
- **Screen**: 4.96" IPS, 1280×720, 16:9
- **Storage**: 8GB eMMC + MicroSD
- **Connectivity**: WiFi, Bluetooth
- **Battery**: 5000mAh

## Critical Prerequisites (Cannot Skip)

### 1.厂商 StockMod (内核+分区表)
- 必须从官方固件提取 `boot-prefix.img`（含内核+分区表）
- 无此项 BaseOS 完全无法启动
- 备注：RG34XX 有这份，Smart Pro 需要确认是否有官方 StockMod 固件

### 2.设备 profile (devices.json)
- 必须在 `devices.json` 中添加 rg34xx 同系列的 profile 配置
- 必须包含：`baseos_device`、`boot_prefix`、`bootlogo`、`capabilities`、`harvest`、`layout`
- 面板尺寸：1280×720，16:9

### 3.GPT 几何 (source.json)
- 必须从厂商 StockMod 读取 GPT 几何
- prepare 阶段会校验，缺一不可

### 4.输入设备映射
- 必须实测 `/dev/input/eventN` 编号
- 确认哪个设备是键盘设备（如 `ANBERNIC-keys`）
- 启动器使用 `--input /dev/input/eventN`

### 5.分辨率与 viewport 改动
- RG34XX 是 720×480，Smart Pro 是 1280×720
- 必须改 `pocket.runtime-config.ts` 中 profile 的 logical viewport
- 选项：改 viewport 大小 或 黑边展示

### 6.内存考量
- 1GB LPDDR4 是否够跑 PocketJS 运行时 + 卡片动画
- 建议先做压力测试

### 7.启动器无关代码
- 启动器代码本身是设备无关的
- 真正绑定设备的只有：`--fb /dev/fb0`（fbdev 回退路径）和 `--input /dev/input/eventN`（输入编号需实测）

## 具体工作步骤（按顺序）

1. **固件准备**：从厂商获取 StockMod `.img`，提取 `boot-prefix.img` 和 rootfs
2. **准备阶段**：`prepare-stock.sh`，生成 `boot-prefix.img`、`stock-harvest.tar`、`source.json`
3. **构建 BaseOS**：`build-tools.sh` → `build-rootfs.sh` → `build-image.sh`，生成 `baseos-rg34xx.img`
4. **刷卡**：`flash-card.sh` 写入 microSD
5. **首启验证**：开机检查是否进启动器，日志检查 `failure streak`
6. **启动器改动**：
   - 改 `launch_frontend.sh`：DRM 可选、fbdev 回退、输入设备、compat PATH
   - 加 compat shim：音量/电量/Wi‑Fi/服务等
   - 改 viewport：viewport 从 360×240 改为 1280×720 的对应设置
7. **扫描器改写**：busybox sh/awk 版本，保持 `library.json` 结构
8. **单镜像**：内置 System/ + 首启同步 hook（expand-storage 后把 System/ 拷到卡上）

## 已实测的事实基线

- **设备**：TRIMUI Smart Pro (A133 Plus)，内核 4.9.170
- **显示**：只有 `/dev/fb0`，无 `/dev/dri`，`/sys/class/drm` 为空 → 只能用 fbdev
- **输入**：`/dev/input/eventN`，需实测编号
- **glibc**：最高 `GLIBC_2.35`，我们的二进制要 2.39/2.44 → 必须用 musl 静态编译
- **运行时**：`pocket-linux-kms --help` 报 GLIBC 版本错误 → 必须用 musl 静态或 bookworm 容器
- **前端日志**：`DRM card not found in /dev/dri/card0..card1`，failure streak 累积 → 启动不起来
- **亮度节点**：无 `/sys/class/backlight`，无 `/sys/class/leds`；存在 `/sys/class/disp/disp/attr`
- **系统工具**：有 `amixer`、`aplay`、`wpa_cli`，无 `python3`、`systemctl`、`rocknix-*`
- **分区**：p7（vfat BASEOS，已扩到 28G）
- **启动**：`frontend-session` 执行 `launch_frontend.sh`，失败 3 次 sleep 30s，第 4 次 sleep 30s

## 设备无关代码

启动器代码本身是设备无关的：
- 不依赖特定 SoC、屏幕分辨率
- 真正绑定设备的只有：`--fb /dev/fb0`（fbdev 回退路径）和 `--input /dev/input/eventN`（输入编号需实测）

## OMP Goal 阶段（M1→M6）

M1 运行时能加载 → musl 静态编译或 bookworm 容器
M2 画面出现在面板 → `--fb /dev/fb0 --input /dev/input/event1`
M3 开机自动进启动器 → 改 `launch_frontend.sh`
M4 状态栏/设置显示真实值 → compat shim
M5 Library 能扫到内容 → sh/awk 扫描器
M6 单镜像 → System/ + 首启同步 hook

## 判断是否可行

- **有 StockMod**（厂商官方固件） → 能做，具体看分区/GPT 是否匹配
- **没有 StockMod** → 这条路走不通

如果你手头有 TRIMUI Smart Pro 的官方固件，我可以直接帮你开始第一步；没有，这条线就走不通。

## 备注

- 启动器代码本身是设备无关的（不依赖特定 SoC/屏幕）
- 真正绑定设备的只有 fbdev 路径和输入编号
- 内存 1GB 是否够跑 PocketJS 运行时存疑，建议先测试
- 启动器代码改动主要在启动脚本和兼容层，不改渲染逻辑
- ROCKNIX 卡保持不动，任何 BaseOS 失败都不影响 ROCKNIX 卡