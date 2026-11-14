# RetroBilingual 中文汉化文本恢复工具套件

本目录包含从 BZMJ 汉化 ROM (`塞尔达传说_缩小帽.gba`) 中提取字模、建立汉字映射、批量解码 3,828 条 UTF-8 中文文本的完整自动化工具集。

---

## 一、 工具清单

1. **`extract_glyphs.py`**：
   - 依据已破解的 BZMJ 字库重定向表（`0xDC9F00`），将 ROM 中的全部 1,196 个字模解包并导出为单字 16×16 / 8×16 的 PNG 图片。
   - 输出至 `data/glyphs/G{bank}_{code}.png` 与 `data/glyphs/index.json`。

2. **`match_glyphs.py`**：
   - 自动解析 Bank 1 的标准 ASCII 字母、英文符号、常用全角标点，以及 Bank 3 的游戏按键图标。
   - 读取并写入 `data/glyph_mapping.json`。

3. **`decode_chinese_text.py`**：
   - 读取 `data/glyph_mapping.json` 与 BZMJ ROM，将 3,828 条字节码文本批量转换为 UTF-8 中文字符串。
   - 输出至 `data/chinese_utf8.json`，并统计当前成功解码率与剩余未映射字形。

4. **`build_review_html.py`**：
   - 生成可视化审查网页 `data/review.html`，展示每个字形的放大位图、出现频次、游戏上下文例句以及当前映射结果。

---

## 二、 后续智能体执行操作指南（节省 Token 工作流）

如果后续指派其他智能体推进字形录入，只需让其执行以下步骤：

### 步骤 1：确认基础提取
```bash
python3 tools/chinese_text_recovery/extract_glyphs.py
python3 tools/chinese_text_recovery/match_glyphs.py
```
此时 `data/glyph_mapping.json` 中已包含了 195 个基础字符。

### 步骤 2：识别与填充汉字映射
- 智能体可直接读取 `data/glyphs/index.json` 中 Bank 4、5、6、7 的汉字。
- 结合游戏对话上下文（例如查看 `data/chinese_utf8.json` 或 `data/review.html` 中高频出现的词汇，如“塞尔达”、“林克”、“帽子”、“咕咕鸡”），或者调用模板比对/本地识别，向 `data/glyph_mapping.json` 中增量补充映射项：
  ```json
  {
    "G4:01": "明",
    "G5:01": "量",
    "G6:01": "来",
    "G7:01": "斯"
  }
  ```

### 步骤 3：验证解码与产出最终库
```bash
python3 tools/chinese_text_recovery/decode_chinese_text.py
```
观察输出的 `Fully decoded entries` 比例。当主要对话解码完成后，将核准的译文导入 `approved-zh.json`，运行现有数据门控：
```bash
python3 tools/retrobilingual/validate_pack_inputs.py
```
验证通过后即可调用 `pack.py` 打包最终离线数据库 `translations.db`。
