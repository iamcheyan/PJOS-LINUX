# 黄金太阳2 失落的时代：文本与 pack 构建记录

- 目标日版：`golden-sun-the-lost-age-ja.gba`，AGFJ01 rev0，SHA-256 `19dd48b74726f323cd829e226b60aa1b373c51fb2e840804efe2d2dc2891a890`。
- 文本源：Project Atlantis 的 `golden-sun-the-lost-age/translations/*.jsonl`，按日版 `string_id` 记录。
- 控制码：`0x01` 为 A 键分页，`0x03` 为换行，`0x02` 为消息结束。
- 数据集：`translation-work/work/gs2_text_zh.json`，11,377 个消息、13,181 条分页。
- 包：`gba/golden-sun-the-lost-age-ja.ja-zh.pack`，2,559 字形，约 610 KB，ROM gate 正确。
- 仍待：为 GS2 日版定位 `text_id`/页状态并编写适配器；当前只有文本包。

适配器所需的运行时状态/存档要求见：
`docs/37-retrobilingual-remaining-inputs.md`
