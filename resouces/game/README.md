# RG34XX 游戏与翻译资源

本目录镜像自 HX90 上连接的 RG34XX `/storage/content/games`，按原相对路径保留。最新源树有 **6 个游戏系列**，不是 5 个：多出来的是《黄金太阳：失落的时代》。掌机镜像中的 38 个文件包括 12 个 GBA 版本、12 张 ROM 同名封面、6 张系列封面、6 个 `series.json`，以及 `misc/tool.pocket` 和 `snes/test.sfc`。空的 `gb/gba/gbc/homebrew` 等目录也保留。

`ROM_SHA256SUMS.txt` 是 12 个 GBA 版本的 SHA-256 清单。掌机资源与 HX90 staging 做过 checksum 对比；工作文件存放在每个游戏自己的 `translation-work/` 下，源目录仍保留在原位置。

## 游戏清单与翻译进度

| 目录 | 掌机版本数 | 当前进度 |
| --- | ---: | --- |
| `series/zelda-minish-cap/` 塞尔达传说：缩小帽 | 2 | **已完成**，已有审核映射、ROM 字形码表与运行时 pack |
| `series/golden-sun/` 黄金太阳：开启的封印 | 2 | 进行中；有日文源 ID 的中文文本与 pack，干净日版现已同步；实机实体 X/干净 ROM 验收仍待完成 |
| `series/golden-sun-the-lost-age/` 黄金太阳：失落的时代 | 2 | 尚未翻译 |
| `series/fe-binding-blade/` 火焰之纹章：封印之剑 | 2 | 尚未翻译；已有中日 ROM 提取素材和源 ZIP |
| `series/fe-blazing-blade/` 火焰之纹章：烈火之剑 | 2 | 尚未翻译；已有中日 ROM 提取素材和源 ZIP |
| `series/fe-sacred-stones/` 火焰之纹章：圣魔之光石 | 2 | 尚未翻译；已有中日 ROM 提取素材和源 ZIP |

每个 `series/<slug>/` 都保留掌机的系列封面、ROM 版本、版本封面及元数据。Golden Sun 当前 clean JP ROM 为 `golden-sun-ja.gba`，SHA-256 `088bedae4bad8b67e87ff10035a898d3639f3182d486fe5a5d113bab223e0a26`。

## 缩小帽日中翻译是怎么实现的

这是 mGBA core 上的 RetroBilingual HUD 翻译，不是把中文改进 ROM。流程分三部分：

1. [TMC adapter 源码](series/zelda-minish-cap/translation-work/source/tmc.c)按日版 ROM SHA-256 门控，只对目标 ROM 启用。它读取 EWRAM `0x02001404` 的 16 位 `textIndex` 和 `0x02001489` 的渲染状态；同一 ID 下只有 `WAIT(3) -> ROLL/NEXT(4)` 才让页号加一。
2. 审核映射和 UTF-8 中文文本保存在 `translation-work/data/retrobilingual.db`、`approved-zh.json`、`tmc_bilingual_aligned.json` 等文件中。`glyph_mapping.json` 把游戏字形码映射到 Unicode；`glyphs/` 和审核报告保存字形校对证据。
3. [translations.rbpk](series/zelda-minish-cap/translation-work/data/translations.rbpk) 是编译后的运行时包。它有 12×12、1bpp 字形图集，1,770 个字形、4,922 个 ID/分页条目，header 的 ROM gate 为 `16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38`。运行时按 `text_id + page_index` 查找字幕，X 键打开 HUD。

源码逻辑在 `~/development/retrobilingual/core/adapters/tmc.c` 和 `core/retrobilingual.c`；本归档保存了 adapter/pack 脚本副本以及数据、报告和 pack，便于离线备份。当前掌机 `/storage/.config/pocketjs/retrobilingual.pack` 的 SHA-256 为 `ad793e0abfffe6d5176cb06199d1d2416c475a04ba84ab586d2414b694412c7e`，与本地 TMC pack 相同。该设备路径是**全局单一 pack**；换成其他游戏的 pack 会替换当前 pack。

## 如何备份缩小帽翻译

完整翻译工作文件已经放在：

`resouces/game/series/zelda-minish-cap/translation-work/`

做一份可恢复的压缩备份：

```sh
mkdir -p "$HOME/development/backups"
stamp=$(date +%F)
backup="$HOME/development/backups/minish-cap-translation-$stamp.tar.gz"
tar -czf "$backup" -C resouces/game/series/zelda-minish-cap translation-work
sha256sum "$backup"
```

单独备份设备当前正在使用的 pack（ADB 接在 HX90 上）：

```sh
ssh hx90 'adb -s 5c0010894414c802512 pull \
  /storage/.config/pocketjs/retrobilingual.pack /tmp/retrobilingual.pack'
scp hx90:/tmp/retrobilingual.pack \
  resouces/game/series/zelda-minish-cap/translation-work/data/device-retrobilingual.pack
```

恢复时，把备份中的 `translations.rbpk` 推回 `/storage/.config/pocketjs/retrobilingual.pack`；部署前先核对 pack header 的 ROM SHA-256 与当前运行 ROM 一致。全体游戏资源也可用同样方式备份：

```sh
tar -czf "$HOME/development/backups/pjos-games-$(date +%F).tar.gz" \
  -C resouces game
```
