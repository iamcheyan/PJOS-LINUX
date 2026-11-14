# RetroBilingual 运行时集成（代码级）

状态：实现与 AArch64 构建完成；按用户要求暂停真机验证。

## 已实现

| 功能 | 实现位置 | 行为 |
|---|---|---|
| 日版身份门控 | `src/retrobilingual.c` `rb_pack_load()` | 先比对 ROM 大小/CRC32 让钩子只在目标日版生效；载入 pack 时再计算 ROM SHA-256，必须等于 pack 记录的 `16ac…b38`。任一不符则不显示任何 UI。 |
| 对话资源索引 | `rb_dialogue_read()` | 读取 EWRAM `0x02000050` 的 `gMessage`：`state & 0x7F` 为活动，偏移 `+8` 为 16 位 `textIndex`。 |
| 分页跟踪 | `rb_dialogue_read()` | 同一 `textIndex` 下，渲染状态由 `WAIT(3)` 进入 `ROLL(4)` 时页号 +1；对话关闭或资源索引变化时复位。 |
| 离线译文查询 | pack 文件 | 按 `text_id + page` 精确查找；pack 只由已审核（`review_status='approved'`）映射构建。无命中显示内置「暂无翻译」条目。 |
| 快捷键拦截 | `retrobilingual_process_input()` | X 短按由 `inputCallback` 直接轮询（X 不在 mGBA 的 GBA 键映射里），打开菜单；字幕 chord 默认 L1+Select，与 driver.cfg 的 GBA 键位一一映射后检测，不用轮询整个手柄。 |
| 菜单输入屏蔽 | 同上 | 菜单/字幕打开时 `*keys = 0`，游戏收不到任何按键；关闭时恢复。 |
| 暂停/恢复 | `rb_pause()` / `rb_resume()` + `retrobilingual_should_run_frame()` | 打开菜单或显示字幕时快照 mCore 状态并跳过 `core->runFrame()`；关闭时 `core->loadState()` 恢复同一帧，避免字幕错位。 |
| 同帧渲染 | `retrobilingual_draw()` | 在 mGBA `video_cb` 之前直接写入 GBA 240×160 RGB565 帧：字幕为底部半透明横幅；菜单为居中面板。无外部窗口、无 `/dev/fb0` 争用。 |
| 快捷菜单 | `RB_MENU` | 短按 X 打开：resume / quick save / quick load / subtitles on-off / hotkeys。 |
| 快捷存读档 | `rb_quick_save()` / `rb_quick_load()` | 使用 mCore 状态 API，写入 `/storage/.config/pocketjs/retrobilingual-quick.state`；不改 ROM，也不覆盖 RetroArch 的 `saves`/`states` 目录。 |
| 快捷键重绑 | `RB_BINDINGS` | 菜单进入 hotkeys，选择动作后按 A 进入捕获，再按 1–2 个物理键保存到配置；显示当前 `id,id`。 |
| 配置持久化 | `rb_config_load()` / `rb_config_save()` | `/storage/.config/pocketjs/retrobilingual.conf`，键：`subtitle_enabled`、`bind_save`、`bind_load`、`bind_subtitle`。 |
| 字体图集 | `tools/retrobilingual/pack.py` | 构建期用 PocketShell 的 OFL `SarasaUiSC-Regular.ttf` 只栅格化已审核译文用到的字符（12×12、1bpp）；`FusionPixel-12px-monospaced-zh_hans.ttf` 是启动器的子集，缺少「你/好/无」等字，不能用于任意字幕。不打包 TTF，不提交 ROM 文本。 |

## 按键与冲突

| 物理键 | RetroArch 绑定（本仓库 `driver.cfg`） | 说明 |
|---|---|---|
| X | 无（`input_save_state_btn="nul"`） | 保留给 core 的菜单键；不再触发 RetroArch quick-save。 |
| Y | `input_load_state_btn="3"` | 保留 RetroArch 快速读档。 |
| L1 | 无（移除 slow motion 绑定） | 作为默认字幕 chord 的一部分到达 core。 |
| Select | `input_player1_select_btn="6"` | 与 L1 组成字幕 chord；单按时仍传给游戏。 |
| R1 | `input_toggle_fast_forward_btn="5"` | 保持快进。 |
| Select+Start 长按 | `baseos-hotkeys` | core 不拦截；避免覆盖退出组合。 |
| L2/R2 | 亮度 | core 不绑定。 |

字幕 chord 在 core 内识别后，按下期间会把 `keys` 清零，避免 Select/L 传入游戏；松开后恢复。菜单键 X 不在 GBA 键映射中，游戏天然收不到。

## 构建与打包

```sh
# 1) 构建带 overlay 的 mGBA core（AArch64，输出到 overlay/.../libretro/）
sh tools/build-retrobilingual-mgba-h700.sh

# 2) 从已审核映射 + UTF-8 中文文本构建运行时 pack
python3 tools/retrobilingual/pack.py \
  --database translations.db \
  --texts approved-zh.json \
  --source-rom-sha256 16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38 \
  --output retrobilingual.pack
```

`pocket-game-play` 现在会先计算 `.gba` 的 SHA-256，仅当哈希等于目标日版时才改用 `mgba-retrobilingual_libretro.so`；其他 ROM 继续使用原 `mgba_libretro.so`。部署可用 `tools/deploy-retrobilingual.sh`（默认只做 `--check`，实际安装会先备份到 `/storage/pjs/retrobilingual-backup-<时间>/`，并可选传 `--pack retrobilingual.pack`）：该脚本未在本轮执行，设备验证按用户要求暂停。

## 未完成的数据依赖

1. **中文译文的 Unicode 化**：现有汉化 ROM 文本仍是字形字节码，没有可靠 code→Unicode 映射；`pack.py` 因此要求一份外部 `approved-zh.json`（真实、已审核的 UTF-8 译文）。没有它就不能生成可读字幕——这是当前唯一阻断显示真实中文的数据缺口。
2. **映射审核为 0**：当前数据库只有 3,747 条 `pending` 候选，没有 `approved` 记录；按“只用真实且已审核映射”，pack 构建会拒绝空集。
3. **第二份汉化 ROM（BZMP）** 文本表位置未验证，未纳入。
4. **上下文（context_id）暂未参与运行时选择**：pack 以 `text_id + page` 为键，数据库虽保留 `context_id`，但运行时没有从事件脚本读取上下文；同一文本 ID 在不同剧情下需要不同译文时，当前只能取单一映射。
5. 真机输入、字幕显示、暂停恢复、菜单导航与截图均未验证（用户要求暂停设备测试）。

## 主机侧验证（无需设备）

`python3 tests/test-retrobilingual-host.py` 用真实编译的 `src/retrobilingual.c`、合成 ROM/pack/EWRAM 验证：pack 的 ROM 门控、`WAIT→ROLL` 分页、默认 L+Select 进入字幕并暂停、字幕帧绘制、再次 chord 恢复、X 打开菜单并暂停、X 关闭恢复。当前通过。
