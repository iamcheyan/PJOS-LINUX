#!/usr/bin/env python3
"""Create a read-only glyph review report for RetroBilingual stage 1.

This script never changes mapping or decoded data.  It ranks mapped glyphs by
their occurrences in chinese_raw, adds short decoded contexts, and aggregates
unmapped [G..] markers already present in chinese.
"""

from __future__ import annotations

import json
import re
import argparse
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "data/glyph_mapping.json"
ALIGNED = ROOT / "data/tmc_bilingual_aligned.json"
GLYPH_INDEX = ROOT / "data/glyphs/index.json"
TAG_RE = re.compile(r"\[G(\d+):([0-9A-Fa-f]{2})\]")
RESIDUAL_RE = re.compile(r"\[G\d+:[0-9A-Fa-f]{2}\]")
CONTROL_RE = re.compile(r"\[C[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2})+(?::[0-9A-Fa-f]{2})*\]")


def tag_for(bank: str, code: str) -> str:
    return f"G{bank}:{code.upper()}"


def decode_for_context(text: str, mapping: dict[str, str]) -> str:
    def glyph(match: re.Match[str]) -> str:
        tag = tag_for(match.group(1), match.group(2))
        return mapping.get(tag) or f"[{tag}]"

    text = TAG_RE.sub(glyph, text)
    text = text.replace("[C06:00]", "{player}").replace("[Player]", "{player}")
    text = text.replace("[C06:01]", "{1}")
    return re.sub(r"\s+", " ", text).strip()


def one_line(text: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def context_for(entry: dict, tag: str, mapping: dict[str, str]) -> str:
    decoded = decode_for_context(str(entry.get("chinese_raw", "")), mapping)
    value = mapping.get(tag) or f"[{tag}]"
    pos = decoded.find(value)
    if pos < 0:
        return decoded[:80]
    return decoded[max(0, pos - 6):pos + len(value) + 6]


def image_info(tag: str, index: dict[str, dict]) -> str:
    info = index.get(f"[{tag}]") or {}
    path = info.get("image_path", f"data/glyphs/{tag.replace(':', '_')}.png")
    size = f"{info.get('width', '?')}×{info.get('height', '?')}"
    return f"`{path}` ({size})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/glyph_audit.md")
    parser.add_argument("--baseline-residual", type=int)
    args = parser.parse_args()
    mapping: dict[str, str] = json.loads(MAPPING.read_text(encoding="utf-8"))
    aligned: list[dict] = json.loads(ALIGNED.read_text(encoding="utf-8"))
    glyph_index = {
        item["tag"]: item
        for item in json.loads(GLYPH_INDEX.read_text(encoding="utf-8"))
        if "tag" in item
    }

    raw_counts = Counter()
    residual_counts = Counter()
    unknown_controls = Counter()
    for entry in aligned:
        raw_counts.update(
            tag_for(bank, code) for bank, code in TAG_RE.findall(str(entry.get("chinese_raw", "")))
        )
        residual_counts.update(RESIDUAL_RE.findall(str(entry.get("chinese", ""))))
        for control in CONTROL_RE.findall(str(entry.get("chinese", ""))):
            if not re.fullmatch(r"\[C0[23](?::[0-9A-Fa-f]+)+\]|\[C06:0[01]\]", control):
                unknown_controls[control] += 1

    nonempty = sum(entry.get("chinese_raw") not in ("", "[EMPTY]") for entry in aligned)
    output = [
        "# RetroBilingual 阶段 1 字模审计",
        "",
        "本报告由 `audit_glyphs.py` 生成；只读审计，不自动修改映射。",
        "",
        "## 基线",
        "",
        f"- 对齐行：{len(aligned)}；不同 `source_id`：{len({e.get('source_id') for e in aligned})}",
        f"- 非空文本：{nonempty}；空文本：{len(aligned) - nonempty}",
        f"- `chinese` 中残留 `[G..]`：{sum(residual_counts.values())} 处，{len(residual_counts)} 个码位",
        f"- 已映射码位：{len(mapping)}",
        "",
        "## 已映射码位（按 `chinese_raw` 出现次数降序）",
        "",
        "| 次数 | 标记 | 当前映射 | 字模 | 例句上下文 | source_id | 英文 |",
        "|---:|---|---|---|---|---|---|",
    ]
    ordered = sorted(mapping, key=lambda tag: (-raw_counts[tag], tag))
    for tag in ordered:
        examples = []
        for entry in aligned:
            if f"[{tag}]" not in str(entry.get("chinese_raw", "")):
                continue
            examples.append(
                (
                    context_for(entry, tag, mapping),
                    str(entry.get("source_id", "")),
                    one_line(str(entry.get("english", ""))),
                )
            )
            if len(examples) == 3:
                break
        if examples:
            context, source_id, english = examples[0]
        else:
            context = source_id = english = ""
        output.append(
            f"| {raw_counts[tag]} | `{tag}` | `{mapping[tag]}` | {image_info(tag, glyph_index)} "
            f"| {context} | `{source_id}` | {english} |"
        )

    output += ["", "## `chinese` 中残留的未映射标记", "", "| 次数 | 标记 | 例句上下文 | source_id | 英文 |", "|---:|---|---|---|---|"]
    for token, count in residual_counts.most_common():
        example = next((e for e in aligned if token in str(e.get("chinese", ""))), None)
        if example is None:
            continue
        output.append(
            f"| {count} | `{token}` | {one_line(str(example.get('chinese', '')))} | "
            f"`{example.get('source_id', '')}` | {one_line(str(example.get('english', '')))} |"
        )

    output += ["", "## 阶段 1 验收快照", "", "### 五个优先候选", "", "| 标记 | 阶段 1 最终映射 |", "|---|---|"]
    for tag in ("G7:19", "G5:E4", "G4:82", "G4:AD", "G4:60"):
        output.append(f"| `{tag}` | `{mapping.get(tag, '<missing>')}` |")
    output += ["", "### 人工查看的前 20 个高频码位", "", "`" + "`, `".join(ordered[:20]) + "`", ""]
    output += [
        "### 本轮前 200 人工复核后纠正",
        "",
        "| 标记 | 原映射 | 字模确认 |",
        "|---|---|---|",
    ]
    for tag, before, after in (
        ("G4:15", "哪", "那"),
        ("G4:16", "之", "么"),
        ("G4:1A", "门", "们"),
        ("G4:41", "安", "芒"),
        ("G4:48", "十", "什"),
        ("G4:50", "重", "事"),
        ("G4:56", "口", "只"),
        ("G4:67", "威", "存"),
        ("G4:71", "进", "复"),
        ("G4:77", "户", "卢"),
        ("G4:86", "闹", "走"),
    ):
        output.append(f"| `{tag}` | `{before}` | `{after}` |")
    output += ["", "人工复核同时确认 `G4:09` 的字模为“在”、`G4:76` 的字模为“经”，两者不改。"]
    for sid in ("0003", "1002", "4901"):
        example = next((e for e in aligned if str(e.get("source_id", "")).upper() == sid), None)
        if example:
            output.append(f"- `0x{sid}`：{one_line(str(example.get('chinese', '')), 300)}")
    output += [
        "",
        f"- 未映射 `[G..]`：{sum(residual_counts.values())} 处。",
        f"- 阶段开始时实际基线：{args.baseline_residual} 处。" if args.baseline_residual is not None else "- 阶段开始基线：未传入。",
        "- 按出现次数排序的前 200 个已映射码位已查看 PNG；除已列出的修正外，未发现可据图确认的替换。",
        f"- 未确认控制码：{sum(unknown_controls.values())} 处，{len(unknown_controls)} 种；保留原标记，未猜测其含义。",
        "- 本阶段未重新生成 `data/translations.rbpk`；现有文件保持原样（阶段 1 不把现有 5,071 条目当作新验收结果）。",
        "- 文档记录的阶段前错误切分页数为 6,082；阶段 1 不改变页号，阶段 2 才验收新 pack 页数。",
        "- 本阶段未打包、未编译运行时、未部署到掌机。",
    ]
    if unknown_controls:
        output += ["", "未确认控制码样例："]
        output.extend(f"- `{token}`：{count} 处" for token, count in unknown_controls.most_common())

    output_path = Path(args.output)
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(output_path)
    print(f"mapped={len(mapping)} raw_glyph_occurrences={sum(raw_counts.values())}")
    print(f"residual_instances={sum(residual_counts.values())} residual_codepoints={len(residual_counts)}")


if __name__ == "__main__":
    main()
