# 烈火之剑（FE7J）适配记录

- 日版 ROM SHA-1 `037702b1febd5c9535262165bf030551d153de81`，与 FireEmblem7J 反编译目标一致。
- `sActiveMsg` EWRAM `0x0202B5B0`
- `sMsgString` EWRAM `0x0202A5B0`（0x1000）
- `sTalkStObj` IWRAM `0x03000040`，str 偏移 0
- `sProcArray` EWRAM `0x02024E20`，步长 `0x6C`，64 个
- `ProcScr_Talk` ROM `0x08BFFB84`
- 页控制符 `0x03`（[A]），页码 = 已消费的 0x03 数减 1。
- 适配器：`core/adapters/fe7.c`，已注册，宿主测试通过。
- 汉化 ROM 文本缓冲为自定义字形码（示例 `92 E9 93 B8 …`），不是 GBK；需字形映射后才能生成中文数据集。

## 已构建伴生包

- 文本源：公开仓库 `arceus-jia/fe7-cn-script`（火花×狼组汉化版剧情/支援/其他文本，带消息 ID）。
- 数据集：`translation-work/work/fe7_text_zh.json`，4,488 个消息、29,088 条分页。
- 包：`gba/Fire_Emblem_Rekka_no_Ken_JA.ja-zh.pack`，2,617 字形，约 1.09 MB，ROM gate 正确。
- 页数由日版 `[A]` 决定；中文行按日版页数分组，不按字数随意增页。
