# 火焰之纹章：封印之剑（FE6J）日译中适配记录

## 目标 ROM

| 项目 | 值 |
| --- | --- |
| 文件 | `gba/Fire_Emblem_Fuuin_no_Tsurugi_JA.gba` |
| 大小 | 8,388,608 (`0x00800000`) |
| 游戏代码 | `AFEJ01` rev0 |
| SHA-1 | `a57095da867de4d585c33d4394712986245fe6ca` |
| SHA-256 | `e62288883544705b18f1a0753896fdd865a628fb4589135813b16a972a4c1557` |

该 SHA-1 与 `StanHash/fe6` 反编译工程的目标 ROM 完全一致，因此可以按符号表确定运行时地址，而不是靠猜测偏移。

## 运行时地址（来自匹配的 FE6 反编译符号）

| 数据 | 地址 | 说明 |
| --- | --- | --- |
| `sActiveMsg` | EWRAM `0x0202A404` | 当前消息 ID（32 位存储，取值 0..0xFFFF） |
| `sMsgString` | EWRAM `0x02029404` | 解码后的消息缓冲区（0x1000 字节） |
| `sTalkStObj.str` | IWRAM `0x03000038` | 对话过程当前读取位置；指向 `sMsgString` 时表示对话仍在显示 |
| `sProcArray` | EWRAM `0x02023CC4` | 64 个过程，步长 `0x6C` |
| `ProcScr_Talk` | ROM `0x085C3D04` | 对话过程脚本；存在该过程时对话框处于打开状态 |

## 分页模型

FE6 的对话文本用 `0x03`（`[A]`）表示“等待 A/B/方向键继续”。`talk.c` 在生成等待过程前已经越过该控制符，因此：

- 已消费的 `0x03` 数量减 1 = 当前显示页的 `page_index`。
- 第一页仍在打字时消费数为 0，统一返回 0。
- 对话过程不存在时返回“无对话”，避免关闭对话框后残留 ID 继续显示翻译。
- 同一 ID 在不同对话框中重复出现时，页数由缓冲区指针重新计算，不依赖跨框缓存。

## 中文文本与页对齐

中文参考 ROM 的 `gMsgTable` 与日版同址（`0x0F635C`），但中文文本是明文 GBK，日文是 Huffman 压缩。提取脚本：

`translation-work/source/fe6_extract.py`

处理规则：

1. 用日版消息表与 Huffman 树解码日文，得到每个消息的 `0x03` 页数。
2. 读取中文 ROM 同 ID 的 GBK 文本；`0x01` 转为换行，`0x10`/`0x80` 控制符连同操作数移除。
3. 若中文页数与日文页数相同，直接使用中文页边界。
4. 中文页数更多时，按日文页宽比例合并相邻中文页，绝不增加 pack 页数。
5. 中文页数更少时，只在换行/标点附近补分页，最终页数与日版 A 键节奏一致。

输出：`translation-work/work/fe6_text_zh.json`（22,439 条，覆盖 3,956 个消息 ID）。

## 已构建伴生包

| 项目 | 值 |
| --- | --- |
| 文件 | `gba/Fire_Emblem_Fuuin_no_Tsurugi_JA.ja-zh.pack` |
| 条目 | 22,440（含 `FFFF` 暂无翻译提示） |
| 字形 | 5,414 |
| 字模 | SarasaUiSC-Regular 12px（本机没有 FusionPixel12.ttf） |
| ROM gate | 目标日版 SHA-256 |
| SHA-256 | 见构建目录的实际文件 |

## 验证

- `make test` 通过，含新增 `tests/host/test_fe6.c`：ROM gate、消息 ID、对话过程门禁、两页 A 键推进。
- 真实日版 ROM 在本机 mGBA 中运行，适配器记录：
  - `0x0A76` page 0 → 1
  - `0x0A7D` page 0 → 1 → 2
  - 对话框关闭后返回无对话
- 尚未完成：AArch64 核心重建、同步到掌机、掌机 X 键截图验收。

## 复现

```sh
python3 resouces/series/fe-binding-blade/translation-work/source/fe6_extract.py
```

随后用 RetroBilingual 的 pack 构建函数生成 `.ja-zh.pack`，gate 使用上面的 SHA-256。
