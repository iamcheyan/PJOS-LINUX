# TrimUI Smart Pro (TSP) 免刷机双系统适配工程方案与实施指南

本文档详细记录了将 **PJOS (BaseOS)** 系统移植并落地到 **TrimUI Smart Pro (Allwinner A133Plus)** 掌机的完整技术方案、运行原理、安全注意事项、目录结构规划以及具体的工程实施步骤。

---

## 一、双系统运行原理与安全保障机制

### 1. 为什么“绝不会变砖”？（主板零写入保证）
- **核心逻辑**：
  TrimUI Smart Pro 拥有板载 eMMC 存储（`/dev/mmcblk0`）与外置 MicroSD (TF) 卡槽（`/dev/mmcblk1p1`，挂载在 `/mnt/SDCARD`）。
  本方案中，**所有的 PJOS 系统文件、二进制、启动器、模拟器配置与游戏数据全部存放在这张 32GB 的外置 TF 卡中**。
  整个适配过程中，**绝不对掌机主板 eMMC 进行任何形式的固件擦写、分区修改或 bootloader 刷入**。
- **双系统自动识别与挂载机制**：
  TrimUI 官方固件的启动脚本 `/usr/trimui/bin/runtrimui.sh` 内置了“SD 卡优先执行”的官方钩子逻辑：
  ```sh
  SDCARD_TRIMUI_DIR=/mnt/SDCARD/trimui
  if [ -d $SDCARD_TRIMUI_DIR ] ; then
      # 如果 TF 卡存在 /mnt/SDCARD/trimui 目录，则执行 TF 卡自定义主程序
      ${SDCARD_TRIMUI_DIR}/app/MainUI
  else
      # 否则执行板载官方系统的 MainUI
      /usr/trimui/bin/MainUI
  fi
  ```
- **双系统体验**：
  - **插卡开机**：系统自动检测到卡内的引导入口，**无缝启动 PJOS 系统**；
  - **拔卡开机**：系统检测不到卡内目录，**直接进入 TrimUI 官方原厂系统**；
  - **软切换回原厂**：在卡内引导脚本中增加按键侦测（如开机按住 SELECT 或卡内放入 `.boot_stock` 标记），即可在不拔卡的情况下自由切回官方系统；
  - **崩溃容错**：即使卡内代码报错或程序异常崩溃，引导脚本会优雅捕获错误并自动回退拉起官方原厂 UI，不会产生死机或黑屏。

---

## 二、实机硬件审计与已验证事实

通过 ADB 对当前接入的 TrimUI 实机进行了点对点技术验证，以下关键硬件链条已 100% 验证通过：

| 硬件模块 | 硬件规格与节点 | 实机测试结论与证据 |
| :--- | :--- | :--- |
| **CPU / 架构** | 全志 Allwinner A133Plus (`sun50iw10p1`), 4x Cortex-A53 @ 1.6GHz, 1GB LPDDR4 | 64 位 ARMv8 架构，兼容现有 AArch64 静态编译二进制 |
| **屏幕与显示** | 4.96 英寸 IPS 屏, **1280 × 720** (16:9), 驱动 `er68576`, 输出节点 `/dev/fb0` (32-bit BGRX) | **已实测验证**：编写测试程序直写显存并截图（[docs/evidence/2026-11-21-trimui-smart-pro/fb0-test-pattern.png](docs/evidence/2026-11-21-trimui-smart-pro/fb0-test-pattern.png)），成功在 1280×720 下绘制深青底色与绿色点阵边框 |
| **手柄与输入** | 物理按键 + 双模拟霍尔摇杆，系统运行 `trimui_inputd`，映射为 Xbox 360 手柄协议 (`/dev/input/event3`) | **已实测验证**：测试程序非阻塞打开 `TRIMUI Player1` (fd=3) 成功，标准 Linux evdev 协议 |
| **音频输出** | ALSA 驱动，声卡 0 `audiocodec` (`sun50iw10codec-0`), 包含 `HpSpeaker` 与 `Headphone` 混音节点 | **已实测验证**：ALSA PCM 硬件节点就绪，内置 `aplay` 与 `tinyplay` 工具正常响应 |
| **引导钩子** | `/mnt/SDCARD/trimui/app/MainUI` 自定义入口 | **已实测验证**：模拟重启后成功打印 `run from sdcard` 与 `=== PJOS Boot Intercepted ===`，且 3 秒后安全交回官方系统 |

---

## 三、32GB TF 卡目录架构规划

卡内采用分层解耦的目录组织方式，兼顾 PJOS 运行、RetroArch 模拟器与用户 ROM 存储：

```text
/mnt/SDCARD/
├── trimui/                     # TrimUI 原厂固件约定的 SD 卡自启目录
│   └── app/
│       └── MainUI              # [核心] PJOS 双系统引导主脚本 (负责环境初始化与进程调度)
├── System/                     # PJOS 系统核心目录 (对标 BaseOS 系统结构)
│   ├── bin/
│   │   └── pjos-dpad           # 输入按键与全局快捷键调度守护进程
│   ├── pocketjs/               # PocketJS 前端运行环境
│   │   ├── bin/
│   │   │   └── pocket-linux-kms # AArch64 静态编译运行时 (内置 fbdev 引擎)
│   │   └── apps/
│   │       └── boot.pocket     # PocketShell 1280x720 宽屏启动器包
│   ├── compat/                 # 兼容与模拟器层
│   │   ├── bin/
│   │   │   └── retroarch       # AArch64 Linux 独立版 RetroArch
│   │   └── share/
│   │       └── retroarch/
│   │           ├── cores/      # 模拟器核心 (mgba_libretro 等)
│   │           └── driver.cfg  # 宽屏居中、无模糊点阵与 SDL2/ALSA 音频配置
│   └── config/
│       └── pjos.conf           # PJOS 运行偏好与启动项配置
├── Roms/                       # 游戏 ROM 目录 (GBA, FC, SFC, MD, PS 等)
│   └── GBA/
├── Imgs/                       # 游戏封面目录 (像素化封面与原版封面)
│   └── GBA/
└── pjos-boot.log               # 启动日志 (记录开机、进程调度与运行状态)
```

---

## 四、具体工程落地实施步骤

### 步骤 1：构建适配 TrimUI 的 PocketJS 运行时与 Profile
1. **定义 Profile**：
   在 SDK 中建立 `trimui-tsp-fbdev` 硬件 Profile：
   - 物理视口（Physical Viewport）：`1280 × 720`
   - 逻辑视口（Logical Viewports）：`[[360, 240]]` 或 `[[640, 360]]`
   - 渲染呈现（Presentations）：`["fit", "integer-fit"]`
2. **导出 Runtime Profile 并编译**：
   使用 AArch64 交叉编译器编译包含 `pocket-linux-fbdev` 驱动的静态二进制，确保其能够在无 DRM KMS 连接器的 Allwinner DISP2 环境下无缝 fallback 到 `/dev/fb0`。

### 步骤 2：调整 PocketShell 启动器宽屏布局并编译打包
1. **视口与配置调整**：
   调整 `pocket.json` 与布局样式，支持 16:9 比例在 1280×720 下的居中与宽屏展示。
2. **编译打包**：
   使用 Bun 与 SDK 工具链编译生成 `pocketshell.pocket`。

### 步骤 3：准备 RetroArch 与 RetroBilingual 宽屏模拟套件
1. **GBA 1280×720 呈现策略**：
   - GBA 原生 240×160，在 1280×720 屏幕下采用 **4× 整数缩放（960×640）居中加边框** 或 **4.5× 全高（1080×720）**。
   - 配置 `driver.cfg` 关闭双线性平滑（`video_smooth = "false"`），保持点对点锐利点阵。
2. **音频驱动绑定**：
   配置 `audio_driver = "sdl2"`，设备绑定 ALSA `hw:0,0`。
3. **输入按键映射**：
   配置 `/dev/input/event3` 对应的 Xbox 360 键位映射（A/B/X/Y、肩键、左模拟摇杆）。

### 步骤 4：在 32GB TF 卡上组装并部署完整系统
1. 创建 `/mnt/SDCARD/trimui/app/`、`/mnt/SDCARD/System/` 等目录。
2. 部署运行时 `pocket-linux-kms`、启动器 `boot.pocket` 与 RetroArch 组件。
3. 部署引导脚本 `MainUI`：
   - 负责检测关机/重启/原厂切换按键；
   - 保持官方底层硬件守护进程（`trimui_inputd` 提供摇杆支持，`trimui_scened` 提供屏幕亮度控制）；
   - 拉起 PJOS 前台启动器。

### 步骤 5：实机启动与系统全功能验收
1. 启动掌机，验证是否无缝直接进入 PJOS 启动器；
2. 验证左模拟摇杆与十字键的界面导航响应；
3. 验证卡片轮播（Carousel）、像素化封面开关与系统设置；
4. 放入测试 GBA ROM，验证游戏运行、声音播放与 RetroBilingual 滤镜切换；
5. 验证安全回退（拔卡开机恢复官方原版，插卡开机进入 PJOS）。
