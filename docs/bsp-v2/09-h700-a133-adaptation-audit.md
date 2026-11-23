# H700 与 A133 设备适配现状审计

日期：2026-11-23  
范围：PJOS-LINUX/BaseOS、PocketShell 启动链、当前 TG5040 设备。此文记录当前事实与迁移边界，不把“编译过”或“卡上临时运行”写成固件支持。

## 结论

目前 BaseOS 固件构建面向 `devices.json` 中的 11 个 H700 目标。TG5040 尚未成为 `build-all.sh` / `devices.json` 中的 BaseOS 固件目标；它现在通过厂商 TinaLinux 启动脚本，从 SD 卡运行 PJOS 的 `MainUI` 和 Zircon。这是应用层/卡侧适配，不能等同于可刷写的 A133 BaseOS 固件。

仓库已经有多 SoC 的 BSP v2 设计文档，但没有 `bsp/` 配置目录、profile 加载器或 DAL 实现。近期 TG5040 电源键修复中的 `rcS` 和 `MainUI` 分支是兼容补丁，仍含板级节点/输入名字；它不是完成后的 SoC 抽象。

## 当前设备的实测事实

本审计从当前连接的 TG5040 只读读取了设备树、内核、输入和主要硬件节点：

| 项目 | TG5040 现场读数 | 归属建议 |
|---|---|---|
| SoC 兼容串 | `allwinner,a133`、`arm,sun50iw10p1`；设备树 model 为 `sun50iw10` | SoC profile（marketing 名称 A133 Plus 不作为硬件判据） |
| CPU 架构 / 内核 | AArch64；Linux `4.9.191` | SoC / kernel ABI profile |
| 显示 | `/dev/fb0`，32 bpp，逻辑/可见面板 1280×720 | framebuffer ABI 可归 SoC；分辨率、旋转归板级面板 |
| 背光 | `/sys/class/led/tg5040_exterme_brightness` | 板级控制路径；通过 DAL 暴露亮度语义 |
| 输入节点 | event0 `sunxi-keyboard`；event1 电源键；event2 音频插孔；event3 `TRIMUI Player1` | SoC 提供设备发现机制；板级声明具体角色与按键映射，运行时不依赖 event 编号 |
| 电池/充电 | `axp2202-battery`、`axp2202-usb` | PMIC/SoC 共享基线候选；仍需 A133 其他板的交叉验证后才能提升到 SoC 共性 |
| 音频 | ALSA card `audiocodec` | SoC 驱动候选；混音器控制和路由可能是板级差异 |
| 网络接口 | `wlan0`、`wlan1` | 仅证明接口存在；驱动、固件、用途和功能仍需单独归档/验证 |

事件节点编号只作为现场诊断记录，不能写成系统契约。按设备名字匹配也只适合发现设备的过渡实现；长期契约应是 `input.power`、`input.gamepad` 等角色及其映射配置。

## 两类设备当前覆盖范围

| 子系统 | H700 / RG34XX 家族 | A133 / TG5040 | 当前缺口 |
|---|---|---|---|
| 固件目标与启动链 | `devices.json`、H700 构建脚本和厂商镜像路径 | TinaLinux + SD 卡 `MainUI`，没有 A133 BaseOS target | 需要单独的 A133 BSP、stock image/分区来源及构建目标 |
| 按键与手柄 | `ANBERNIC-keys`、H700 GPIO/D-pad 工具和按键配置 | `sunxi-keyboard`、PMIC 电源键、`TRIMUI Player1`；PocketJS 有 TrimUI 专用映射 | 映射仍散落在 `src/apply-pocketjs-input.py`、`baseos-hotkeys`、`MainUI` 和应用配置里 |
| 电源键/熄屏 | H700 hotkeys 默认 event0/event1 及 `baseos-panel` 路径 | 设备实际电源键在 event1，背光走 TG5040 节点；固件 `rcS` 尚未成为权威运行路径 | 需要统一的电源事件监听和 DAL `display.blank`；TG5040 短按熄屏/再按唤醒还需实体键验收 |
| 显示 | H700 使用 sunxi `dispdbg`/`baseos-panel` 路径，屏幕因型号变化 | fbdev 1280×720；背光 sysfs 与 H700 不同 | 面板几何属 board；显示控制器驱动和能力属 SoC；运行时 profile 尚未统一 |
| 音频 | H700 有专用 speaker amp 模块/混音配置 | A133 现场有 `audiocodec`，但无完整音量/路由实测 | 不能把 H700 功放模块或控制名作为 A133 默认值 |
| 电池/网络/USB/存储 | H700 构建和服务路径已有大量假设 | 现场能看到部分兼容节点，但尚未验证端到端功能和 A133 分区/启动更新路径 | capability/feature 必须区分“节点存在”与“功能已验证” |

## 代码位置中的设备耦合

- `devices.json` 只列 H700 的 11 个目标，没有 TG5040；`build-rootfs.sh` 的输入仍是旧设备 profile。
- `docs/bsp-v2/README.md` 已定义 `bsp/<vendor>/<soc>/` + `bsp/boards/<board>/` + DAL，但 README 明确记载该阶段只有设计和 schema。
- `src/apply-pocketjs-input.py` 通过 `TRIMUI` 字符串区分手柄映射；`src/apply-pocketjs-panel.py` 和多处 bridge patch 直接识别 TG5040 背光节点。
- `src/baseos-hotkeys/main.go` 有 H700 默认节点参数；TG5040 依靠启动命令覆盖参数。
- 当前 `overlay/etc/init.d/rcS` 的近期改动按背光节点选择 TG5040 分支；这是可工作的兼容判断，不是 SoC/board profile 消费。
- `build-pocketjs-runtime-musl.sh` 仍校验 RG34XX 的 720×480 runtime profile，不能据此声称已经有 A133 固件构建路径。
- `docs/14-trimui-smart-pro-port.md` 保留了早期阶段的部分过时陈述（例如 StockMod 尚未确认）；当前 ADB 实测已证明 TG5040 可从 SD 启动卡侧 PJOS，但这仍未生成或验证 A133 BaseOS 固件。

## 建议的适配边界

1. **SoC profile**：CPU 架构、内核 ABI、GPU/显示/USB/Wi-Fi/音频驱动栈、可复用 sysfs/设备接口及初始化步骤。先分别建 `allwinner/h700` 与 `allwinner/a133`；只有经过另一块同 SoC 板验证的事实才上移到 SoC 层。
2. **Board profile**：面板分辨率/旋转、背光实现、按键 wiring、输入设备角色匹配、板载连接器、板级 PMIC 变体、分区布局及固件前缀。RG34XX 与 TG5040 分别有自己的 board profile。
3. **通用服务与应用**：只消费语义（例如 `power-key`、`gamepad`、`display.blank`、`display.brightness`），不直接拼 `/dev/input/eventN`、商品名或某块板的 sysfs 路径。构建时把有效 profile 编入 `/etc/pjos/`，运行时由 DAL 校验和提供语义接口。
4. **验证状态**：`unknown`、已构建、QEMU 验证、真机验证分开记录；SoC 相同不能代替板级按键/屏幕/电源实测。

## 推荐迁移顺序

1. 先按 BSP v2 的 M2 建 H700 与 A133 SoC 数据，以及 RG34XX/TG5040 board profile；从 `devices.json` 机械迁移现有 H700 身份字段，TG5040 未实测的字段标为 `unknown`。
2. 让构建器从 board profile 生成有效 `/etc/pjos/board.json`，保持现有 H700 镜像行为不变；A133 profile 暂不宣称可刷写，直到 stock 镜像、分区表、harvest 和初始化链齐备。
3. 将电源键/熄屏先接入 DAL：系统只启动一个 hotkeys 服务，profile 提供 power-key 发现规则、gamepad 角色、背光控制能力和长按策略。删除 `MainUI`、`rcS`、PocketJS 对 event 编号和板名的重复假设。
4. 再移植网络、音频、存储和 runtime build；为每个 SoC 建 fake-tree 构建检查，并在每块板单独完成实机验证。

当前修复的短按熄屏代码属于迁移第 3 步之前的兼容实现。它没有改变固件构建目标，也没有让 A133 成为完整 BaseOS firmware target。
