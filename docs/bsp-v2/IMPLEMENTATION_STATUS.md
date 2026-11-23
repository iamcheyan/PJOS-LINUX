# 多 SoC 适配：实现与验收

## 架构边界

- `bsp/allwinner/<soc>/soc.json` 与 SoC 钩子描述共用接口和初始化；`bsp/boards/<id>/board.json` 与板级 overlay 描述面板、输入角色、按键映射、电源策略。H700 板分别引用已审计的内核变体，不能用另一台板的符号偏移替代。
- `devices.json` 是兼容导出；`python3 tools/device_profile.py generate-legacy` 从 BSP 投影固件目标，旧调用方仍读 schema 1。构建拒绝不一致的导出。卡侧目标不进入固件矩阵。
- 通用 → SoC → 板级顺序合成 overlay。镜像中的 `/etc/pjos/` 带四个 JSON、只读 DAL 投影和输入映射。`baseosctl version` 和启动日志报告身份与来源，诊断可用 `baseosctl input list --nodes` 查看已解析节点。
- `rcS` 或厂商 SD 卡的 `MainUI` 启动唯一 `baseos-hotkeys`。守护进程的生命周期不依赖游戏；文件锁拒绝重复实例。短按调用 `display blank toggle manual`；长按由板声明 `poweroff` 或 `ignore`。自动熄屏经同一 DAL 锁与状态，不解除手动熄屏，不停止进程、音频或网络。硬件与输出行为仍按下表验收。

## 验收矩阵

| 范围 | 状态 | 证据 |
|---|---|---|
| Profile 校验、深合并、第三块 fake board | PASS | `python3 tools/bsp_validate.py all`、`tests/test-bsp-profiles.py`、`tests/test-bsp-build-integration.py`；无新增板名分支。 |
| 熄屏状态、亮度恢复、短按/长按、重复 owner | PASS（fixture） | `tests/test-dal-baseosctl.py`、`tests/test-screen-idle.py`、`go -C src/baseos-hotkeys test -race -count=1`；不代替实体键测试。 |
| H700 原有 11 个目标的准备输入 | PASS | `verify-target.sh` 逐板校验，`work/acceptance/fleet-input-results.log`；不等于构建或启动。 |
| H700 全 11 目标 stock-boot rootfs/QEMU/SD 镜像/更新包/更新回环 | PASS（`b32c151`） | `work/final-acceptance/attempt-20261123T045900185934Z/evidence.json` 记录 55 步通过、33 个产物哈希；全 11 个 rootfs 烘焙 `b32c151`。当前输入状态辅助程序的代表板在 `work/final-acceptance/representative-20261123T064754866386Z/evidence.json` 对 `adff262` 完成 5 步；全 11 目标需在最终 SHA 重建，不能把前版结果冒充本版。 |
| H700 内容级基线与真机启动 | PASS（内容差异已分类）/ NOT VERIFIED（真机） | 用同一批厂商输入、同一共享工具和匹配 runtime 在干净 `2423f9c` tree 重建 11 台 rootfs：`work/final-comparison/*-base.manifest`。本版差异仅在 `work/acceptance/fleet-changed-rootfs-paths.txt` 所列 BSP/DAL/启动/前端文件及其父目录；未对新镜像做真机启动。 |
| 两种 PocketJS runtime | PASS（宿主构建及 QEMU user-mode） | 两个静态 AArch64 runtime 分别用匹配包完成 3 帧逻辑执行（720×480、1280×720），日志 `work/acceptance/{h700,tg5040}-runtime-final.log`。不算系统启动。 |
| TG5040 卡侧载荷 | PASS（宿主） | `tools/build_card.py --profile /tmp/trimui-profile/pocket-profile.json --inspector <SDK>/tools/pocket-pack.ts --runtime work/tg5040-runtime-final --package <匹配包> --output work/tg5040-delivery-input` 验证包的 profile hash/ABI/1280×720 和必须有 `input.map`；生成 `trimui/app/MainUI`、`System/profile`、DAL/输入辅助程序及匹配包。`work/acceptance/tg5040-delivery-input.manifest` SHA-256=`b5e5f9c18d719e5e471240d30f0eb8e5c4776b6952f788f04f3cdebf2b7a8579`；只在新目录生成，不挂载或写设备。 |
| TG5040 真机查询 | PASS（只读） | 将当次 DAL 与生成 profile 解包到厂商系统的 `/tmp`，执行 `version`、`display info`、`input node/key-state`、`power battery/charger`、`audio info`、`network info`。`work/acceptance/tg5040-input-readonly.log` 显示 A133/TG5040、1280×720、电源键与手柄角色、KEY_POWER 未按下、电池在充电及 WLAN。未检验扬声器实际出声或联网吞吐；读数属于某时刻，不是持续状态保证。 |
| TG5040 实体键熄屏/再按唤醒，游戏及音频网络不停止，长按不关机 | NOT VERIFIED | 新卡侧载荷未替换设备上的活动 System；现有厂商到 SD 的证据见 [卡侧启动报告](../40-trimui-smart-pro-dual-boot-implementation-plan.md)。没有改变设备启动状态。 |
| A133 独立 BaseOS image | BLOCKED | `build-rootfs.sh tg5040` / `build-image.sh tg5040` 显式拒绝 card 模式。没有生成或启动 A133 固件。 |

### 缺少的 A133 构建输入

目前只有厂商 TinaLinux 运行事实和 SD 软件包；要启用独立镜像，至少需要以下**对应 TG5040、同一已知厂商版本**的可核对输入。不从设备 eMMC 读出、覆盖或复制引导链来绕过这些门禁。

| 本地输入 | 来源与验收要求 |
|---|---|
| `work/tg5040/source.json` | 可分发/已获授权的厂商固件来源、版本、校验和，原始分区表、扇区几何、各可启动/可写角色。不能沿用 H700 的 GPT 角色。 |
| `work/tg5040/boot-prefix.img` 或经核实的等价启动输入 | 厂商支持的可恢复 SD 启动链，包含 bootloader/env、对应 kernel 与板级 DTB；需要逐项校验来源和哈希。 |
| `bsp/allwinner/a133/harvest.list` 与 `work/tg5040/stock-harvest.tar` | 从同版厂商 rootfs 验证提取，明确 glibc/固件/模块闭包和来源，不能复用 H700 清单；补充相应内核 ABI 审计表。 |

### 新板与回滚

1. 采集设备树兼容串、面板可见几何、输入名称/键码、供电背光和模块/分区来源。证据不足则填 `unknown`，不根据营销名称推定。
2. 选择现有 SoC 或在 `bsp/<vendor>/<soc>/` 放置新适配器；只在板目录声明 wiring、overlay、固件模式和内核变体。固件模式需要实际的准备输入与 SoC 构建/初始化钩子。使用 `generate-legacy` 刷新兼容导出。
3. 运行 profile 校验和 fake-tree 覆盖，构建后比对内容 manifest，分别做 QEMU 用户空间和可恢复 SD 真机验收。真机用对应 profile 的 `version` 和角色诊断，验证电源键在游戏过程中仍工作。
4. 回滚源码时按提交逆序 `git revert`，不重写共有历史。H700 回滚到已验证的前版镜像/更新包，不能混用新旧 profile 和服务。TG5040 保留原 SD `System` 与 `trimui/app/MainUI` 成对备份，切回原文件或用已有的 `.boot_stock` 开关。无需改动 eMMC、bootloader 或厂商分区。

剩余驱动边界及移除条件见 [消费者清单](CONSUMERS.md)。`display output set` 与尚未验证的 RTC 唤醒/震动等动作不视为已适配。
