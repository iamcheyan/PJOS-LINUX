# 剩余两项 RetroBilingual 交付所需的输入

本文只记录“还差什么、放到哪里、格式是什么”。已有三款包不受影响：

- 封印之剑、烈火之剑、黄金太阳2 的 `.ja-zh.pack` 已生成。
- 圣魔之光石只有日版适配器，没有 pack。
- 黄金太阳2 有 pack，但还没有运行时适配器。

---

## 一、圣魔之光石：为什么没有 pack

日版适配器已经完成，问题在**中文文本**：

- 汉化 ROM 运行时解出的对话缓冲区是自定义字形码，例如 `8B F1 88 F3 …`，不是 GBK/UTF-8。
- 公开渠道没有找到带日版消息 ID 的《圣魔之光石》完整中文脚本。
- 已尝试用《烈火之剑》的字形映射和 GBK 顺序插值解码，但两款汉化版的字库编码并不完全一致，解出来会出现错字/乱码。
- 因此不能诚实地生成 pack；强行生成只会让 HUD 显示错误文字。

### 需要准备（二选一即可）

#### 方案 A：带消息 ID 的中文文本（最推荐）

放到：

`resouces/series/fe-sacred-stones/translation-work/work/fe8_text_zh.json`

格式：

```json
{
  "entries": [
    {"source_id": "0A1B", "page_index": 0, "text": "第一页中文"},
    {"source_id": "0A1B", "page_index": 1, "text": "第二页中文"}
  ]
}
```

要求：

- `source_id` 必须是日版消息 ID（4 位十六进制），不是章节序号。
- `page_index` 必须和游戏里按 A 键的翻页一一对应。
- 一页内的换行用 `\n`。
- 如果文本里用 `[A]` 表示翻页、`[LF]` 表示换行，也可以直接给带标记的文本；构建脚本会转换。

#### 方案 B：字形码 → Unicode 映射表

放到：

`resouces/series/fe-sacred-stones/translation-work/work/fe8_glyph_map.tsv`

格式（制表符分隔，一行一个字）：

```text
92E9	需
93B8	要
8492	变
```

要求：

- 第一列是 ROM/缓冲区里实际出现的 4 位十六进制字形码（大小端按缓冲区原样）。
- 第二列是一个 Unicode 字符。
- 标点、空格、数字、拉丁字母也要包含，否则 HUD 会缺字。
- 如果只有字库图片或码表截图，也可以先放入同一目录，并写一份 `SOURCE.md` 说明来源和对应关系。

#### 还需要一份来源说明

同目录 `SOURCE.md` 写清楚：

- 文本/码表来自哪个汉化版本、作者或发布页。
- 对应日版 ROM 的 SHA-256。
- 是否允许再分发；不允许时只在本机使用。

---

## 二、黄金太阳2：为什么只有 pack、没有适配器

文本包已经按 Project Atlantis 的日版 `string_id` 生成，但适配器需要每帧知道：

1. 当前显示的是哪个 `string_id`；
2. 玩家按 A 后当前是第几页。

目前这两个运行时地址/状态还没有在 AGFJ01 rev0 上确认。没有适配器，pack 不会在 X 键时被查询，HUD 也就不会出现。

### 需要准备（任选其一）

#### 方案 A：对话中的即时存档（最快）

放到：

`resouces/series/golden-sun-the-lost-age/translation-work/work/saves/`

建议提供两个：

- `dialogue-page1.ss1`：某段对话第一页，等待按 A；
- `dialogue-page2.ss1`：同一段对话按一次 A 后的第二页。

同时附一个 `saves/README.md`，写明：

- 使用的 ROM 文件名和 SHA-256（必须是 `AGFJ01 rev0`）；
- 存档是 mGBA 的 `.ss1`/`.state`，还是游戏内 `.sav`；
- 画面上大概是什么剧情，方便核对。

有这两个状态，就可以直接对比 EWRAM，定位 `string_id` 和翻页字段。

#### 方案 B：允许继续自动跑输入

不需要文件，但需要明确允许继续用模拟器自动按键、反复运行来定位。黄金太阳2 开头有较长的名称输入/序章，自动推进需要更多时间。

#### 方案 C：已知内存地址

如果你已经从 mGBA Memory Search 找到：

- 当前 `string_id` 的 EWRAM 地址；
- 翻页/等待状态的地址或判定方式；

把地址和观测值写进：

`resouces/series/golden-sun-the-lost-age/translation-work/work/ADAPTER_NOTES.md`

---

## 三、最终上机验证（打包之后才需要）

需要确认：

- 掌机可通过 ADB 连接（当前是 hx90 桥接）；
- 允许推送 `mgba_libretro.so` 和 `.ja-zh.pack` 到 `/storage`；
- 允许注入 X 键并抓取显存截图。

这一步不影响本地生成 pack，但影响“掌机上真的显示中文”的最终验收。

---

## 四、不要准备什么

- 不需要重新提供日版 ROM；现有日版 SHA-256 已记录。
- 不需要提供完整汉化 ROM 给公开仓库；如果版权不允许，放本机工作目录即可。
- 不要用机器翻译或占位文本填满 pack；这会破坏“与游戏内 A 键翻页 1:1 对齐”的要求。
