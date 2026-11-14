#!/usr/bin/env python3
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.retrobilingual.tmc_rom import extract_tmc_rom

MAPPING_FILE = Path("data/glyph_mapping.json")
mapping = json.loads(MAPPING_FILE.read_text("utf-8"))

B2_SYMBOLS = {
    "G2:01": ">", "G2:02": "「", "G2:03": "」", "G2:04": "◇", "G2:05": "“",
    "G2:06": "·", "G2:07": "↑", "G2:08": "↓", "G2:09": "←", "G2:0A": "→",
    "G2:0B": "?", "G2:0C": "√", "G2:0D": "&", "G2:0E": "\"", "G2:0F": "'",
    "G2:10": "#", "G2:11": "$", "G2:12": "%", "G2:13": "*", "G2:14": "+",
    "G2:15": "/", "G2:16": ":", "G2:17": "<", "G2:18": "=", "G2:19": ">",
    "G2:1A": "@", "G2:1B": "[", "G2:1C": "\\", "G2:1D": "]", "G2:1E": "^",
    "G2:1F": "_", "G2:20": "{", "G2:21": "|", "G2:22": "}", "G2:23": "~",
    "G2:24": "(", "G2:25": ")", "G2:28": ",", "G2:2A": ";",
}

VERIFIED = {
    "G4:FD": "哩", "G6:0D": "憾", "G6:11": "姐", "G6:1E": "《", "G6:22": "》",
    "G6:A4": "藏", "G6:B5": "遥", "G6:E2": "仔", "G6:E3": "鹏", "G6:E4": "介",
    "G6:E5": "班", "G6:E6": "谷", "G6:E7": "绍", "G6:E8": "菇", "G6:EE": "优",
    "G6:CA": "蠕", "G6:F0": "努", "G7:A5": "踏", "G7:F7": "楚", "G7:53": "凝",
    "G9:00": "荐", "G9:01": "刻", "G9:02": "识", "G9:03": "及", "G9:04": "猪",
    "G9:05": "录", "G9:07": "广", "G9:0A": "暗", "G9:0B": "繁", "G9:0C": "抓",
    "G9:0D": "鉴", "G9:0E": "道", "G9:0F": "迹", "G9:10": "穷", "G9:11": "彩",
    "G9:12": "附", "G9:14": "啊", "G9:15": "烈", "G9:17": "注", "G9:18": "板",
    "G9:19": "简", "G9:1B": "订", "G9:1C": "村", "G9:1D": "呼", "G9:20": "昨",
    "G9:22": "鲁", "G9:24": "削", "G9:27": "眠", "G9:28": "贾", "G9:29": "崖",
    "G9:2A": "敬", "G9:2D": "匹", "G9:2E": "愧", "G9:2F": "校", "G9:30": "杂",
    "G9:31": "鱼", "G9:36": "角", "G9:37": "禁", "G9:3C": "灯", "G9:3E": "趟",
    "G9:44": "求", "G9:48": "案", "G9:4B": "未", "G9:4D": "放", "G9:4E": "彰",
    "G9:51": "波", "G9:57": "友", "G9:58": "喊", "G9:59": "稍", "G9:5B": "乘",
    "G9:61": "况", "G9:63": "赏", "G9:66": "香", "G9:67": "习", "G9:68": "歉",
    "G9:6A": "惠", "G9:6B": "背", "G9:70": "珠", "G9:71": "怖", "G9:72": "磊",
    "G9:77": "率", "G9:79": "丁", "G9:7A": "事", "G9:7C": "取", "G9:7F": "拾",
    "G9:82": "爪", "G9:84": "散", "G9:85": "突", "G9:88": "族", "G9:89": "奖",
    "G9:90": "骷", "G9:9B": "髅", "G9:9F": "惜", "G9:A1": "损", "G9:A6": "帮",
    "G9:A9": "鼹", "G9:AB": "庭", "G9:AC": "套", "G9:B5": "熟", "G9:B8": "闭",
    "G9:C7": "柔", "G9:CC": "捡", "G9:CF": "升", "G9:D3": "释", "G9:D6": "验",
    "G9:D9": "琼", "G9:DA": "祥", "G9:DD": "票", "G9:DF": "伯", "G9:E5": "癖",
    "G9:E6": "称", "G9:E7": "帅", "G9:E8": "浇", "G9:E9": "访", "G9:EA": "概",
    "G9:EC": "绳", "G9:EF": "武", "G9:F7": "巫", "G9:FE": "队",
    "G10:10": "院", "G10:12": "盘", "G10:19": "镯", "G10:1D": "派", "G10:28": "简",
    "G10:29": "仿", "G10:2E": "屋", "G10:30": "祝", "G10:34": "筒", "G10:48": "庆",
    "G10:50": "弹", "G10:55": "右", "G10:5E": "橙", "G10:61": "骑", "G10:62": "详",
    "G10:7B": "末", "G10:AA": "假", "G10:B4": "酪", "G10:DD": "碑", "G10:E1": "鼠",
    "G10:F9": "柴", "G11:00": "貌", "G11:23": "娜", "G11:85": "褐", "G11:BC": "美",
    "G11:BF": "乔",
    # Fix worker hallucinations:
    "G4:1E": "滚", "G4:EE": "骨", "G7:07": "碌", "G4:89": "山",
    "G5:B3": "四", "G4:64": "神", "G4:24": "剑",
    "G4:B8": "请", "G4:05": "不", "G4:10": "要", "G6:19": "关", "G6:05": "闭", "G7:47": "电", "G5:E0": "源",
}

cur_map = {**mapping, **B2_SYMBOLS, **VERIFIED}

def inspect_next():
    zh = extract_tmc_rom(Path(".orca/drops/塞尔达传说_缩小帽.gba"), "zh")
    decomp_en = json.loads(Path("/tmp/retrobilingual-tmc-src/translations/English.json").read_text("utf-8"))

    single_entries = {}
    for e in zh["entries"]:
        raw = e["text"]
        if raw == "[EMPTY]": continue
        tokens = [f"G{m.group(1)}:{m.group(2).upper()}" for m in re.finditer(r"\[G(\d+):([0-9A-Fa-f]{2})\]", raw)]
        missing = [t for t in tokens if t not in cur_map or cur_map[t] is None]
        if len(missing) == 1:
            g = missing[0]
            if g not in single_entries: single_entries[g] = []
            single_entries[g].append(e)

    print(f"Total single-missing glyphs: {len(single_entries)}")
    sorted_glyphs = sorted(single_entries.keys(), key=lambda k: len(single_entries[k]), reverse=True)
    for g in sorted_glyphs[:30]:
        exs = single_entries[g]
        ex = exs[0]
        sid = ex["source_id"]
        cat, idx = int(sid[:2], 16), int(sid[2:], 16)
        en = decomp_en[cat][idx] if cat < len(decomp_en) and idx < len(decomp_en[cat]) else ""
        text = ex["text"]
        for k, v in cur_map.items():
            if v: text = text.replace(f"[{k}]", v)
        text = text.replace(f"[{g}]", f"【{g}】")
        print(f"{g} (unlocks {len(exs)}): {repr(text.replace(chr(10), ' '))[:60]} | EN: {repr(en.replace(chr(10), ' '))[:45]}")

if __name__ == "__main__":
    inspect_next()
