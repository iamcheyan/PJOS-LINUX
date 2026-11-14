# PocketShell 启动器 UI 当前交接

更新：2026-11-14（日本时间）  
工作区：`~/development/PJOS-LINUX` 与 `~/development/pocketshell`

## 目标与重要差异

用户要求按照提供的 GBA 风格参考图开发 RG34XX 启动器，并已授权继续通过 SSH 操作已开机掌机。目标是顶部像素状态栏、尺寸一致且居中的游戏封面轮播、封面生成的暗色模糊背景、标题和底部手柄提示；逻辑画布 480×320，设备面板 720×480。

**当前主分支的实际 UI 与参考图不一致。** 最新 PocketShell 提交 `94244beb` 是 Material 3 风格重设计，使用矢量游戏卡片和环境模糊背景；并非用户要求的 GBA 大颗粒像素风。勿把现有截图或“UI 完成”提交说明误当成参考图验收通过。下一步必须先对照用户给的截图和当前包，确认/修正差异，再做设备部署与验收。

## 当前代码与产物状态

- PocketShell 独立仓库：`~/development/pocketshell`，HEAD `94244bebf182d4302a43a9b94eaf68811b3a6947`，工作树干净。
- 固件仓库：本仓库 HEAD `738966b9a09cba3ec703b7ffd9815522a5c190fc`，工作树干净；父提交包含 UI/OSK 包更新和桌面模拟截图。
- 启动器源码在 PocketShell 仓库；固件侧包含运行时补丁、启动集成及镜像包。单独重建其中一边不会自动更新另一边或掌机。
- `dist/pocketshell.pocket` 和 `overlay/usr/share/pocketshell/System/pocketjs/apps/boot.pocket` 当前 SHA-256 均为 `f2eddd4eee3767b9b4cf4438f8c8c72eee951500c9c87f67bbc563487c4e2c41`，各约 54 MB。
- 当前本地 `work/pocketjs-runtime/pocket-linux-kms` SHA-256 为 `9ef817b02be8770db25738716d405e5cea5a3b21013ed45e35bcd0155faa9652`。部署前须确认它与上述包 profile 匹配，并通过部署脚本的 admission 检查；不要只凭文件存在就部署。
- `work/rg34xx/` 中的完整镜像、ZIP、OTA 和 rootfs 产物，以及它们声称的校验值见 [之前的部署交接](evidence/2026-11-14-pocketshell/HANDOFF_DEPLOYMENT.md)。该文档中“07:19 设备离线”的结论与更早的设备截图提交存在时间/连通性差异；不要把它当成当前连通性结论，也不要在未复核镜像内容、包版本和设备状态前刷整卡或执行 OTA。此次 UI 工作优先使用应用级部署脚本。

## 已有验证证据

- 桌面模拟截图在 [2026-11-14-pocketshell](evidence/2026-11-14-pocketshell/)：主页、多个封面选择、设置、系统信息、终端和虚拟键盘。截图说明其为桌面模拟产物，不等于掌机输出。
- 仓库历史提交 `177f25d` 包含 `docs/evidence/2026-11-14-pocketshell/device-final-20261114-0309.png`，记录一张 03:09 的设备 framebuffer 截图；该 PNG 不在当前 HEAD 工作树中，可用 `git show 177f25d:docs/evidence/2026-11-14-pocketshell/device-final-20261114-0309.png` 取出查看。它证明当时有过设备抓屏，**不证明当前包已部署，也不证明最新 Material 3 包在设备上的状态**。
- `make`/SDK 桌面模拟截图曾验证主页、按键选择、设置、系统页面和键盘交互；完整验证记录见 [部署交接](evidence/2026-11-14-pocketshell/HANDOFF_DEPLOYMENT.md) 与 [根 AGENTS.md](../AGENTS.md)。必须重新运行与当前代码匹配的检查，方可将其作为当前验收证据。
- 用户最初的参考要求和 480×320/720×480 渲染、游戏库、背景与设备约束汇总在 [根 AGENTS.md](../AGENTS.md)；其 RG34XX SSH 与 framebuffer 操作说明也在该文件。

## 设备连接与安全操作

- 目标机主机名 `rg34xx`，SSH 用户 `root`、端口 22。真实 LAN 地址和密码不写进本交接文档；从 AGENTS 指定的本地资料/环境变量读取。不要尝试猜测口令。
- AGENTS 记录的非交互 SSH 登录需用 `sshpass` 和 `PJOS_DEV_PW`，并指定 `/tmp/pjos-debug-known-hosts`；不要用 `BatchMode=yes`，也不要以裸 `ssh` 的失败判断 SSH 不可用。先核对已记录主机指纹，再确认远端 `hostname; id` 为 `rg34xx`/root。
- 2026-11-14 09:09 JST 本回合检查 `adb devices -l` 为空，连接 AGENTS 历史记录中的 `<device-lan-ip>:22` 返回 `No route to host`；此探测只说明当时主机到该地址没有路由，尚未完成认证，不代表设备密码错误。`PJOS_DEV_PW` 当时未设置。重新确认设备 IP/局域网连通后，使用 AGENTS 记录的 SSH 命令；设备端写入前须先备份。保留 Wi-Fi 作为远程调试通道，不要关闭。
- PocketShell 提供 `scripts/deploy-rg34xx.sh`、`scripts/deploy-ssh.sh` 和 `scripts/install-rg34xx.sh`；先用 `--check` 做只读/准入检查，再按部署脚本备份后部署。检查当前部署脚本及其参数，不要直接刷整卡或跑 OTA。
- 部署后确认活动进程和实际安装文件；在 720×960 双缓冲 `/dev/fb0` 读取 framebuffer，按 `/sys/class/graphics/fb0/pan` 选取 720×480 可见页。设备 adbd 不支持 `exec-out`，使用 AGENTS 记录的 `dd` + `adb pull` 或 SSH/SCP 流程。最后在实机验证封面尺寸/居中、左右切换、A 启动、B 返回、START 选项、状态栏和底部提示，并保存截图。

## 交接后的执行顺序

1. 读取用户提供的目标参考图和本文件、根 `AGENTS.md`，对比当前桌面模拟图/包；明确 Material 3 与 GBA 像素参考的差距。
2. 在 PocketShell 源码中按目标实现 UI，保留既有设置、系统页面、终端、输入和游戏启动行为；不触碰无关 PJOS 系统模块。
3. 构建并跑已有 UI/桥接/包准入检查，在 720×480 虚拟 framebuffer 下截取当前版本截图，逐项对照验收标准。模拟器结果标注为模拟器，不冒充实机。
4. 核对生成包与匹配运行时，执行设备部署 `--check`。建立 SSH 后确认机器身份、设备当前版本和备份位置。
5. 备份后应用级部署；实机抓屏和手柄验收通过后，更新此文档中的日期、commit、产物哈希、测试结果及尚存问题。

## 未完成事项

- 使视觉语言严格回到用户要求的 GBA/GBC 大颗粒像素样式，并以原参考图逐项检查布局、图标、尺寸、间距、颜色和背景。
- 确认当前工作树/本地生成物/镜像中包版本一致，运行最新测试与虚拟机检查。
- 在本回合重新验证 SSH 可达性并读取掌机实际运行状态；目前只确认 ADB 列表为空。
- 备份并部署正确的包/匹配运行时到 RG34XX，进行实机 framebuffer 与手柄操作验收。
- 用户要求全部完成前持续推进；现有 goal 仍 active。
