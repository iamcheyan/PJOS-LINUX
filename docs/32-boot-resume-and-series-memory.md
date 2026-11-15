# 开机恢复与系列版本记忆（纵切片）

日期：2026-11-15  
状态：代码与主机侧测试完成；**未做真机验证**，未迁移卡上 ROM/存档。

## 开机恢复上一次前台程序

- 新设置键 `bootResume`，默认 `off`，持久化到 `/storage/.config/pocketjs/ui-settings.conf`。
- `baseos-settings` 支持读取/写入 `bootResume`，以及通用 `series.<series-id>.lastVariant`。
- `apply-pocketjs-settings.py` 将 `bootResume` 接入 SETTING 读写，并提供 `STATE bootResume` 与通用系列键的只读 arm；没有新增 `zeldaLastRom` 等专用键。
- `launch_frontend.sh` 仅在 `bootResume=on` 时消费 `resume.state`。消费前校验：
  - ROM 必须是存储区内的现存 `.gba/.gb/.gbc` 文件，不能包含 `.`/`..` 路径段；
  - App 必须匹配现有包 ID 规则且 `apps/<id>.pocket` 存在；
  - 标记损坏、目标缺失或非法时删除标记并启动器回退。
- `baseos-save-state` 仍只在真正的前台会话中记录恢复目标；正常退出只清理 `active`，不把已退出目标当成活动程序。
- `baseos-reboot` 在重启前调用 `baseos-save-state`，使正常重启也能遵循 `bootResume`。

## 系列版本记忆

- `launcher-catalog.ts` 对每个扫描到的系列读取 `SETTING series.<series-id>.lastVariant`。
- 有效记录会把对应 variant 移到列表首位，并把该 id 暴露为 `recentVariant`；光标从第 0 项开始，因此默认选中该版本。
- 无记录或记录失效时，回退 `series.json` 的 `default`，再回退扫描顺序首项；失效记录不会显示“最近游玩”。
- `launchSeriesItem` 通过通用键写回 `series.<series-id>.lastVariant`，同时保留原有 ROM resume 标记。
- 扫描器 `pocketshell-games` 现在透传 `variants[].default: true`。
- UI 移除了固定系列标题、固定封面和固定 `zeldaLastRom` 分支；最近标记、副标题和语言通过 i18n 键输出。

## 主机侧验证

全部通过（无真机、无设备部署）：

```sh
python3 tests/test-boot-resume.py          # 7 passed
python3 tests/test-baseos-settings.py      # 12 passed
python3 tests/test-settings-runtime-patch.py # 2 passed
python3 tests/test-save-state.py           # 3 passed
python3 tests/test-game-cover-scan.py      # 3 passed
sh tests/test-power-intent.sh              # passed
python3 tests/test-launcher-runtime-precedence.py # passed
python3 tests/test-runtime-selection.py    # passed
cd ~/development/pocketshell && ~/.bun/bin/bun test tests # 17 passed
```

拉取启动器构建也已通过：

```sh
cd ~/development/pocketshell && sh scripts/build.sh
```

产物：`dist/pocketshell.pocket`（构建成功，未部署）。

## 仍未完成

- 真机上的开机/重启恢复、正常退出回启动器、损坏/删除目标回退。
- 卡上 `series/` 目录迁移与真机系列置顶效果。
- 字幕覆盖层、X 菜单和可分页译文（按用户要求暂缓）。
