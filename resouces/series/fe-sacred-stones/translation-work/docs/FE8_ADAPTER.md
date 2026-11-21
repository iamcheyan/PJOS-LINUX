# 圣魔之光石（FE8J）适配记录

- 日版 ROM SHA-1 `7da0456035366aa18414faa79d8fe7649f03c1ed`，与 fireemblem8j 反编译目标一致。
- `sActiveMsg` EWRAM `0x0202B6A8`
- `sMsgString` EWRAM `0x0202A6A8`（0x1000）
- `sTalkStateCore` IWRAM `0x03000040`，str 偏移 0
- `sProcArray` EWRAM `0x02024E68`，步长 `0x6C`，64 个
- `gProcScr_Talk` ROM `0x085B90F0`
- 实机（mGBA）验证 `0x087B` 页 0→6 随 A 键推进。
- 适配器：`core/adapters/fe8.c`，已注册，宿主测试通过。
- 汉化 ROM 文本缓冲同样是自定义字形码（示例 `8B F1 88 F3 …`），不是 GBK；需字形映射。
