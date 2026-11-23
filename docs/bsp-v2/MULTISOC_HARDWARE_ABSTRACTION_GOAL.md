# Goal：建立可扩展的多 SoC / 多板型硬件抽象

## Goal 信息

- **项目仓库**：`PJOS-LINUX`
- **当前基线**：仓库 `main` 当前 HEAD；开始前记录 commit 与 `git status --short --branch`
- **目标分支**：`feature/multisoc-hardware-abstraction`（先检查是否已存在；存在时审阅后续接，不覆盖）
- **参考设计**：`docs/bsp-v2/README.md`、`docs/bsp-v2/02-bsp-boundary.md` 至 `07-migration.md`
- **现状证据**：`docs/bsp-v2/09-h700-a133-adaptation-audit.md`
- **当前设备**：RG34XX/H700 系列；TrimUI Smart Pro/TG5040，设备树兼容串 `allwinner,a133`
- **产品目标**：之后增加新 SoC 或同 SoC 新板型时，硬件差异进入数据配置或 SoC/板级适配实现，上层服务和应用继续调用稳定语义接口。

## 目标

把 PJOS 中分散在 shell、C/Go 工具、构建脚本、PocketJS compat 层和应用中的硬件判断，逐步收敛为：

1. **SoC 层配置/适配**：描述 SoC 族共用的内核与驱动能力、设备接口类型、初始化步骤。
2. **板级 profile**：描述具体面板、按键接线、输入角色、背光接口、PMIC 变体、连接器和厂商固件/分区事实。
3. **硬件抽象层（DAL）**：把 profile 和底层驱动转换为稳定语义，例如 `input.power_key`、`input.gamepad`、`display.blank`、`display.brightness`、`power.battery`。
4. **上层消费者**：`rcS`、BaseOS 服务、PocketJS、运行时和游戏只调用 DAL/`baseosctl` 语义，不自行探测 SoC、写 `/sys`，也不假定 `/dev/input/eventN`。

硬件细节不能被“抽象掉”到不可见：每个事实必须能追溯到 SoC profile、board profile、驱动适配或明确的 `unknown`。商品型号仍可用于 UI 名称、固件文件匹配和日志，但不能成为散落在运行代码里的行为分支条件。

## 首批支持目标

### 1. H700 家族

保持 `devices.json` 当前列出的 11 个 BaseOS 目标可构建、可启动，行为保持现状。迁移时保留各厂商固件、分区和内核 ABI 的独立事实。

**重要约束**：11 个 H700 目标并不等于一个相同内核构建。`docs/bsp-v2/01-audit.md` 和 `src/h700-speaker-amp/profiles.json` 记录了不同固件内核映像/ABI。SoC 共性可以复用，但不能把某个 target 的内核哈希、符号偏移、面板或按键布局错误提升为所有 H700 共性。需要时增加 firmware/kernel-variant 层，由 board profile 引用。

### 2. A133 / TG5040

提供 TG5040 对应的 board profile、输入/电源/显示适配和构建目标。至少覆盖当前已测的 SD 卡运行模式；如果本地存在足够的厂商固件、分区表和依赖闭包，则继续完成独立 BaseOS image 构建与启动验收。

当前现场事实以 `docs/bsp-v2/09-h700-a133-adaptation-audit.md` 为准。禁止仅凭 “A133 Plus” 商品宣传或另一块 A133 板型推断未验证的驱动、PMIC、存储、休眠和分区行为。

若本地没有构建 A133 image 所需的厂商输入，必须完成 profile、DAL、卡侧 PJOS 运行路径和构建期检查，列出精确缺失文件及其来源需求；不得声称独立 BaseOS 固件已支持，也不得通过刷写设备 eMMC 绕过缺失条件。

## 设计约束

### SoC 与 board 的划分

- **SoC profile**：CPU 架构/SoC compatible、可共享的显示与输入 ABI、驱动/固件类别、SoC 初始化步骤、实际验证过的共性。
- **Board profile**：面板尺寸和旋转、背光接法、按键与 GPIO wiring、输入设备角色映射、PMIC 变体、音频路由差异、连接器、固件来源和分区布局。
- **Firmware/kernel variant**：当同 SoC 的厂商镜像有不同内核 ABI、模块偏移或固件内容时，单独表示并由 board/firmware target 引用。
- **运行时发现**：设备名、`compatible`、sysfs 节点、event 名可以用作 profile 选择或验证输入；不能把某一个产品名或 event 编号硬编码为功能本身。
- **保留通用实现**：只有硬件差异才进入 BSP/DAL。POSIX 通用行为不为“抽象而抽象”。

### 声明和错误语义

- Capability/Feature 使用 `yes`、`no`、`unknown` 三态；没有证据不得填 `yes`，`unknown` 不可当作 `no`。
- DAL/`baseosctl` 明确区分成功、不支持、未知/未验证、运行失败；沿用 `docs/bsp-v2/06-baseosctl.md` 中的退出码契约。
- profile 缺失、schema 不兼容、board 与 SoC 不匹配时必须显式报错。不得静默选 H700 默认值继续启动。
- 板级同一硬件服务最多启动一个 owner。启动器、系统服务、游戏进程之间不得重复监听并互相抢写背光/电源状态。

### 电源键与熄屏行为

- 电源键是系统级输入，必须由 BaseOS 服务在前台游戏占屏时继续处理。
- 短按的屏幕关闭/唤醒通过统一 `display.blank` 语义实现；熄屏不能杀游戏或停止网络/音频。
- 长按动作由 profile 明确声明；TG5040 当前需求为防止误关机，长按不得意外调用 poweroff。其他设备保留其已验证行为。
- 不得把 event 编号写入应用或公共脚本；从 profile 的设备匹配规则解析角色。

## 执行阶段

### 阶段 0：现状与基线

1. 审阅 `AGENTS.md`、BSP v2 文档、设备配置、构建脚本及当前相关代码。
2. 记录开始时的 HEAD、dirty files、可用固件输入、设备验证条件。
3. 将硬件相关字面量分类为 SoC、board、kernel/firmware variant 或真正通用；不因文件包含硬件词就机械搬迁。
4. 完成 H700 代表 target 与 TG5040/A133 的基线清单，注明事实来源和验证等级。

### 阶段 1：profile 与校验器

1. 建立 `bsp/` 目录和 schema/validator。
2. 将 H700 目标 profile 按现有 `devices.json` 做无损迁移，建立 SoC 共享层和必要的 per-target kernel/firmware variant。
3. 建立 `allwinner/a133` SoC profile 与 `tg5040` board profile；实测不全的字段用 `unknown`，不填猜测值。
4. 由构建系统校验未知字段、必填字段、目录 ID/SoC 引用、board override、Capability/Feature 依赖。
5. 迁移期间保持 `devices.json` 的现有使用方；明确其为兼容输入还是生成物，不能留下两个可独立修改的权威配置。

### 阶段 2：profile 合成与镜像生成

1. 合成顺序固定为通用发行版 overlay → SoC overlay → board overlay；board 优先级最高。
2. 构建时生成 `/etc/pjos/board.json`、`soc.json`、`caps.json`、`features.json`，并记录来源 profile/版本。
3. 保持 H700 rootfs 内容级基线不变，或逐项解释并批准每一处预期差异。
4. A133 独立镜像构建只有在厂商输入、分区、boot/kernel/DTB、harvest 和模块来源核实后才能启用。

### 阶段 3：DAL 与 BaseOS 服务

实现并接线 `docs/bsp-v2/03-dal.md`、`06-baseosctl.md` 定义的子系统。至少必须涵盖本任务直接涉及的 display、input、power；同时清点并迁移 audio、network、storage、LED/震动及 SoC 初始化中的设备假设。

- `rcS` 只负责调度通用服务，不再包含 SoC/板级节点、模块和按键映射分支。
- `baseos-hotkeys` 接受语义角色/解析后的 profile 参数；系统在游戏运行期间保持唯一监听。
- 熄屏状态、亮度保存/恢复、自动熄屏守护之间使用同一接口和状态文件，不互相点亮或覆盖。
- PocketJS compat shim 和其他消费者调用 `baseosctl`/稳定 API；迁移期兼容 fallback 必须有删除条件，不能永久双写两套来源。

### 阶段 4：PocketJS/runtime 消费 profile

1. 显示后端、分辨率、输入设备选择由系统 profile/接口提供。
2. 设备按键布局映射放在 profile/输入适配层；应用语义操作如确认、返回、菜单由通用层消费。
3. 搜索两个仓库中直接读硬件路径、探测产品名、假设 event 编号的所有消费方，逐项迁移或记录为明确的硬件驱动边界。
4. 新增第三个未适配 target 的 fake profile，证明新增 board 不需要修改上层应用或服务代码（仅测试夹具，不宣称真机支持）。

### 阶段 5：验证和交付

1. Fake-tree/schema 测试覆盖 H700、A133、未知值、缺节点、错误 profile、board override、重复服务启动。
2. H700：构建全部现有 target，验证关键服务/启动路径，并对照内容级基线；任一无真机验证的 target 明确标记为 built/QEMU/device-verified 三态之一。
3. TG5040：确认 SoC 与 board profile 选择正确；实测电源键短按熄屏、再按唤醒、游戏仍在运行；确认按键角色映射、1280×720 显示、音频/电池/网络基本状态。无实机条件的项目列为未验收，不用编译结果替代。
4. 如生成 A133 image：只在隔离介质或可恢复 SD 卡上验证；严禁写入 TG5040 eMMC、替换 bootloader、改写厂商分区或执行未经用户授权的刷机/重启操作。
5. 交付报告逐项列出 acceptance：PASS、BLOCKED（准确原因）、NOT VERIFIED；附命令/日志/图片路径和 artifact hash。

## 关键验收标准

- 新增一块同 SoC board，只新增 board profile/板级 overlay/测试，不修改现有 H700/A133 公共服务逻辑。
- 新增一个新 SoC 时，只新增该 SoC 的 profile、驱动适配和 overlay；现有板行为不被默默改变。
- 构建器不再通过分散的产品名 `if/else` 选择硬件动作；仅允许在 profile 选择、日志、UI 名称和厂商固件匹配边界使用型号身份。
- runtime/service/app 不含已迁移的裸 event 编号、具体背光/电池/音频 sysfs 路径；例外必须记录原因、所有者和移除条件。
- 每个运行期硬件服务均能报告选中的 SoC、board、profile 来源和解析出的设备角色，便于诊断。
- H700 既有目标无回归；TG5040 卡侧模式和 A133 profile 不被错误标成独立 BaseOS 固件已完成。
- 文档说明新增设备的操作流程：采集硬件事实 → 建 SoC/board profile → 校验 → 构建 → fake-tree/QEMU → 真机验收。

## 禁止事项

- 不得把 event 编号当稳定硬件标识；不得只用营销型号建立 runtime 行为分支。
- 不得因两块板都采用 AArch64/A53 就共用 GPU、显示、电源休眠、Wi-Fi 驱动或内核 ABI 假设。
- 不得把 SoC 节点存在等同于设备功能已验证；`unknown` 不得自动升级为 `yes`。
- 不得删除现有 `devices.json`、harvest、kernel profile 或 overlay，直到替代数据被校验、消费并有回滚路径。
- 不得覆盖当前工作区中与 goal 无关的修改；禁止 `reset`、`clean`、无审阅 `stash`、宽泛提交或把其他任务 WIP 混入提交。
- 不得下载、公开或提交私有固件、账号数据、游戏 ROM、密钥、设备日志中的身份凭据。
- 不得向设备 eMMC/内部固件分区写入；不经用户单独确认不得刷机、升级 bootloader 或做不可逆部署。

## 仓库协作与最终报告

- 在 `PJOS-LINUX` 原仓库协作，开始先检查 dirty state 和已有分支；不要另建 clone。
- 将本 goal 的变更与开始时已存在的用户修改严格分开。只提交 goal 所属文件/hunks；遵循仓库中文 commit 风格，推送到 `origin`，绝不推送 `upstream`。
- 按 `docs/bsp-v2/07-migration.md` 分批提交，保留每一步可回滚性；若基线/输入缺失，先交付已完成阶段和明确 blocker，不虚报全量适配完成。
- 最终总结必须回答：架构边界如何落地、H700/A133 分别完成到哪层、哪些功能有真机证据、A133 是否真的生成并启动了 BaseOS image、遗留风险、commit/remote SHA、如何回滚。
