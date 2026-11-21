# 圣魔之光石翻译包状态：待补

- 日版适配器已完成：`core/adapters/fe8.c`，ROM gate、对话门禁、消息 ID、A 键页码均通过宿主测试。
- 汉化 ROM 的对话缓冲区是自定义字形码（示例 `8B F1 88 F3 …`），不是 GBK/UTF-8。
- 公开渠道未找到带消息 ID 的《圣魔之光石》完整中文脚本；用 FE7 字形映射和 GBK 顺序插值无法可靠解码。
- 因此本目录暂不生成 `.ja-zh.pack`。需要补齐以下任一项后才能继续：
  1. 带日版消息 ID 的中文全文本；或
  2. 汉化字库的“字形码 → Unicode”映射表。

完整输入格式与放置位置见：
`docs/37-retrobilingual-remaining-inputs.md`
