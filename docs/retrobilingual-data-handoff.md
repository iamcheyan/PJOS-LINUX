# RetroBilingual 数据交接与补全步骤

运行时、菜单、快捷键、暂停和帧内渲染已实现并通过主机侧测试；当前唯一阻断“显示真实中文”的是**译文数据**。本文给出把数据补齐到可打包状态的最小步骤。

## 现状

- 日版提取：`extract --rom <JP> --language ja` → 3,749 个分页条目。
- 简中 BZMJ 提取：`extract --rom <BZMJ> --language zh` → 3,828 个分页条目（字形字节码，不是 Unicode）。
- 对齐候选：3,747 条 `pending`，2 条未匹配，0 歧义；**0 条 approved**。
- 运行时 pack 只接受 `review_status='approved'` 且带有 UTF-8 译文的数据。

## 需要补齐的两类数据

### 1. 审核状态

用 `review --database … --mapping-id N --status approved --note "…"` 逐条批准。没有审核的候选不会进入 pack。

### 2. UTF-8 译文（当前缺口）

`approved-zh.json`：

```json
{"entries": [
  {"source_id": "0201", "page_index": 0, "text": "早上好，林克！"}
]}
```

`source_id` 与 `page_index` 必须对应数据库中已批准的日文条目。译文来源必须是真实的中文汉化文本（人工录入、汉化组发布的文本、或社区整理的对照表）；禁止用机器翻译或占位文本填充。

如果只有汉化 ROM 的**字形字节码**，需要先取得该汉化版的 code→Unicode 对照（字库表、文本导出或人工核对）。仅凭字节码无法安全生成 `approved-zh.json`，因此运行时会显示「暂无翻译」而不是猜测内容。

## 校验与打包

```sh
python3 tools/retrobilingual/validate_pack_inputs.py \
  --database translations.db \
  --texts approved-zh.json \
  --source-rom-sha256 16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38

python3 tools/retrobilingual/pack.py \
  --database translations.db \
  --texts approved-zh.json \
  --source-rom-sha256 16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38 \
  --output retrobilingual.pack
```

`validate_pack_inputs.py` 会报告：已批准/待审核数量、缺少译文的已批准条目、未批准的译文（会被忽略）、以及字库缺失字符；只有 `pack possible: True` 时才应打包。

## 部署（需用户确认后执行）

`tools/deploy-retrobilingual.sh --pack retrobilingual.pack` 会备份并把 overlay core、`driver.cfg`、pack 安装到 `/storage`。该脚本未在本轮执行，设备验证仍按用户要求暂停。
