# 任务：补全缩小帽未映射字模，让缺译句子进入 pack

日期：2026-11-17
读者：接手的智能体。不需要玩过《塞尔达传说：缩小帽》。
前置文档：`docs/33-retrobilingual-translation-repair.md`（必须先读，其中的禁止事项全部有效）、`tools/chinese_text_recovery/README.md`。

## 1. 背景与已核实的现状

用户在掌机上玩日版时，按 X 弹出中文翻译，仍有很多句子显示"暂无翻译"。2026-11-17 已核实：

- 设备上的 `/storage/.config/pocketjs/retrobilingual.pack` 与 `data/translations.rbpk` 的 md5 相同（`3550bf84bb33ba1e359465fc6eae64d1`），不是"修好了没部署"。
- pack 共 4,329 条（含 1 条 `FFFF` 兜底），已覆盖所有"有可见中文且无未映射字形"的行。
- **没进 pack 的原因有两类：**
  1. **476 行**的 `chinese_raw` 里含未映射字形 `[Gxx:yy]`。共 495 个不同字形，来自 Bank 9/10/11/12（约 483 个）和 Bank 1（12 个）。`pack.py` 按规则拒收这些行。
     - 缺 1 个字的有 247 行，缺 2 个字的有 166 行，缺 3 个及以上的有 63 行。
     - 多为 NPC 名字和生僻字，例如 Candy、Paige、Scratcher、Purry、Elsie。
     - 按 `source_id` 前两位统计，`09` 有 83 行，`0C` 有 41 行，`0B` 有 36 行，`4A` 有 20 行。
  2. **156 行**日文有可见文字（含 `[G`），但中文是空的。这是汉化 ROM 里对应位置没有中文，需要单独判断。
- 补字的收益（按出现次数从高到低）：前 50 个字救回 71 行，前 100 个救回 139 行，前 200 个救回 245 行，前 300 个救回 317 行，全部 495 个救回 476 行。

## 2. 目标

1. 为尽可能多的未映射字形确认对应汉字，写入 `data/glyph_mapping.json`。
2. 重建对齐数据和 pack，使原先 476 行里能解出完整句子的部分进入 pack。
3. 把最终没救回的字形和行留在报告里，不要硬凑。
4. 部署到掌机并验证。

## 3. 硬性规则（沿用文档 33，这里重申最关键的）

- 汉字只能来自汉化 ROM 的字模图片（`data/glyphs/G{bank}_{code}.png`）。禁止用机器翻译、大模型或英文去生成中文。英文只能用来判断先查哪个字。
- 每个映射必须对着放大后的字形图确认，不能只靠模板比对的分数。自动比对只用来生成候选。
- 禁止删掉 `[G..]` 标记后当作通过。仍含未映射字形的行保持 `pending`，不进 pack。
- 禁止全局替换 `chinese` 字段，禁止改 HUD 配色、菜单位置、按键映射、存档槽。
- ROM、整段文本、字模 PNG、设备密码不进 git（`data/tmc_*.json`、`data/chinese_utf8.json`、`data/glyphs/` 已被忽略，保持这样）。`data/glyph_mapping.json` 可以提交。
- 不要改页数（不得新增 `page_index`），不要改适配器逻辑。

## 4. 建议步骤

1. 复现统计。读取 `data/tmc_bilingual_aligned.json`，筛出 `unmapped_glyphs` 非空的行，统计每个字形的出现次数，确认是 476 行和 495 个字形。
2. 排序。按"补上后能救回多少行"贪心排序，先做收益最高的字形。
3. 生成候选。
   - 对每个字形，把 `data/glyphs/` 里的 PNG 与 `~/development/pocketshell/app/fonts/` 里的 Sarasa、Fusion Pixel 等 CJK 字体渲染出的常用字做比对，取前 5 个候选。
   - 结合该字形所在句子的日文、英文和已映射的其余字，缩小候选范围。名字类字形可借助同一名字在其他句子里的写法。
4. 人工确认。把字形放大成 PNG 看图，只确认有把握的字。没把握的留空，不要猜。
5. 增量写入 `data/glyph_mapping.json`，格式沿用现有条目（`"G11:38": "某"`）。每批写入后重跑解码。
6. 重建数据。使用 `tools/chinese_text_recovery/` 里的 `decode_chinese_text.py`、`rebuild_aligned_chinese.py`、`rebuild_dialogue_pages.py`、`sync_repaginated_pack_inputs.py`，顺序以 README 和文档 33 为准。
7. 重建 pack。`tools/retrobilingual/pack.py` 在含 `[G` 的行上会报错，保持这个行为。数据库状态和 `--include-all` 的用法按现有构建流程。
   - 运行时代码的上游在 `~/development/retrobilingual`，本任务通常不需要改它。
   - 先在宿主机用 `cd ~/development/retrobilingual && make test` 和仓库内的 `python3 tests/test-retrobilingual-host.py` 检查。
8. 部署。备份设备上的旧 pack，再替换 `/storage/.config/pocketjs/retrobilingual.pack`。设备操作按 `AGENTS.md`：优先 USB ADB，必要时用文档里的 SSH 命令。部署后核对设备文件与本地的 md5。
9. 单独处理那 156 行"日文有、中文空"：逐条判断是 ROM 本来没有中文，还是解码漏了。只在能确认原因时处理，其余写入报告。

## 5. 验收

- 报告写入 `docs/` 下新文件，包含：
  - 补前和补后的统计：未映射字形数、被拒行数、pack 条目数。
  - 新增映射清单（字形、汉字、确认依据），以及放弃的字形清单及原因。
  - 仍留在 `pending` 的行数。
  - 那 156 行的分类结果。
- 补后 pack 条目数应明显高于 4,329，且 `grep` 不到未映射标记被偷偷删掉的条目。
- 抽查至少 10 条新增句子，对照日文原文和英文，确认没有明显错字。
- 设备上的 pack md5 与本地一致，附部署命令输出。
- 不要把设备上"暂无翻译"消失当作成功标准，要用新增句子的 `source_id` 在 pack 里能查到作为标准。真机上的实际显示如未验证，在报告里写明。

## 6. 注意

- 提交说明里写清楚补了多少字、救回多少行。
- 如果汉化 ROM（`.orca/drops/塞尔达传说_缩小帽.gba`）或字模 PNG 不存在，不要猜路径，停下来说明缺哪个文件。
