# PJOS-LINUX 离线游戏与翻译资源库 (resouces/)

本目录是掌机游戏资源与双语翻译的**唯一权威离线工作区**。
所有游戏的 ROM、多语言封面、元数据配置以及伴生翻译包均在此维护，修改后只需运行 `./sync-to-device.sh` 即可一键同步至 RG34XX 掌机。

---

## 一、目录结构规范

```text
resouces/
├── sync-to-device.sh           # 一键同步到掌机的自动化脚本
├── series/                     # 所有游戏系列目录（与掌机 /storage/content/games/series/ 严格对应）
│   ├── fe-binding-blade/       # 火焰之纹章：封印之剑
│   ├── fe-blazing-blade/       # 火焰之纹章：烈火之剑
│   ├── fe-sacred-stones/       # 火焰之纹章：圣魔之光石
│   ├── golden-sun/             # 黄金太阳：开启的封印
│   ├── golden-sun-the-lost-age/# 黄金太阳：失落的时代
│   └── zelda-minish-cap/       # 塞尔达传说：缩小帽
│       ├── series.json         # 系列元数据与多语言版本清单
│       ├── cover.png           # 系列 256×256 封面
│       └── gba/                # ROM 与伴生文件
│           ├── <rom_ja>.gba        # 官方权威纯净日版 Clean ROM
│           ├── <rom_ja>.png        # 日版封面
│           ├── <rom_ja>.ja-zh.pack # ★ 专属日译中伴生翻译包（随 ROM 一起携带分享）
│           ├── <rom_cn>.gba        # 官方/最高质量中文版 ROM
│           └── <rom_cn>.png        # 中文版封面
```

---

## 二、伴生翻译包（Companion Pack）机制

- 翻译数据包命名为：`<rom_name_without_ext>.ja-zh.pack`。
- 放置在对应日版 ROM 同一目录下。
- 当玩家在掌机运行该日版 ROM 时，RetroBilingual 翻译核心会自动优先探测并加载同目录下的 `.ja-zh.pack`。
- **便携分享**：用户直接拷贝对应的游戏系列文件夹，即可完整带走游戏本体、封面及双语翻译，无需依赖系统全局配置。

---

## 三、一键同步到掌机

在电脑连接 RG34XX 掌机（本地 USB 或 hx90 桥接均可）后，直接运行：

```bash
./sync-to-device.sh
```

脚本将自动完成：
1. 增量同步所有 ROM、封面和伴生翻译包至掌机 `/storage/content/games/series/`；
2. 在掌机端触发 `pocketshell-games` 重建库索引；
3. 热重载 PocketShell 桌面，呈现最新游戏。
