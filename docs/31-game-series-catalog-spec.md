# 游戏系列目录规范（数据驱动）

日期：2026-11-15  
状态：调查与实施规范；本文件本身**不改变**现有启动器或卡上的内容。

## 目标

启动器首页只保留内置终端，以及从存储卡扫描得到的游戏。若同一游戏有多个可选版本，首页显示一个“系列”卡片；确认后显示版本列表，选择其中一项再启动。系列、标题、版本顺序和封面均来自卡上的数据文件，应用代码不得依据某个游戏名称、ROM 文件名或路径关键字作特判。

《塞尔达传说：缩小帽》的五个版本保留现有的“一个系列卡片 → 五个版本”的交互和视觉效果，但成为该通用规则的第一个数据样例。

## 迁移前的旧实现与问题（已移除）

当前 `pocketshell/app/launcher-catalog.ts`：

1. 只将 `.gba`、`.gb`、`.gbc` 放入当前启动器游戏流。
2. 用 `zelda|minish|缩小帽` 正则筛选 ROM。
3. 固定创建 `series:zelda-minish-cap`，固定标题、封面和首选封面路径。
4. 用 `formatZeldaTitle()` 从文件名猜测中/日/美/欧版本。
5. 用专用的 `zeldaLastRom` 配置项记忆最后选择的版本。

这能正确展示当前五个缩小帽 ROM，却无法自然扩展到其他系列，且将内容数据混入程序逻辑。

## 卡端目录结构

系列一律放在游戏根目录下的 `series/` 中。普通单 ROM 游戏仍可保留在既有系统目录（例如 `gba/`、`gb/`、`gbc/`）中；扫描器将它们作为普通游戏展示。

```text
/storage/content/games/
├── gba/                                  # 普通、非系列 ROM
│   └── Tetris.gba
└── series/
    └── zelda-minish-cap/                  # 稳定、ASCII 的系列 ID
        ├── series.json                    # 必需：系列描述与版本顺序
        ├── cover.png                      # 可选：系列卡片封面
        └── gba/
            ├── minish-cap.zh-Hans.gba
            ├── minish-cap.zh-Hans.png     # 可选：与 ROM 同名的版本封面
            ├── minish-cap.zh-Hant.gba
            ├── minish-cap.ja.gba
            ├── minish-cap.en-US.gba
            └── minish-cap.en-EU.gba
```

约束：

- `series/` 只包含系列目录；系列 ID 使用 `[a-z0-9][a-z0-9-]{0,63}`。
- `series.json`、`cover.png` 与 ROM 都在该系列目录内；清单不得引用绝对路径或包含 `..` 的路径。
- ROM 平台从扩展名识别。当前可启动扩展名为 `gba`、`gb`、`gbc`；其他扩展名可被底层库扫描，但不能在 PocketShell 中标为可启动，直至播放器支持它们。
- 版本封面优先使用清单指定的相对路径；没有指定时，尝试 ROM 的同名 `.png`、`.jpg`、`.jpeg`；再没有则使用系列封面；最后才使用通用游戏封面。

## `series.json` v1

```json
{
  "schema": "pjos.game-series/v1",
  "id": "zelda-minish-cap",
  "title": "塞尔达传说：缩小帽",
  "cover": "cover.png",
  "variants": [
    {
      "id": "zh-Hans",
      "title": "简体中文",
      "rom": "gba/minish-cap.zh-Hans.gba",
      "cover": "gba/minish-cap.zh-Hans.png",
      "sort": 10,
      "default": true
    },
    {
      "id": "zh-Hant",
      "title": "繁体中文",
      "rom": "gba/minish-cap.zh-Hant.gba",
      "sort": 20
    },
    {
      "id": "ja",
      "title": "日版",
      "rom": "gba/minish-cap.ja.gba",
      "sort": 30
    },
    {
      "id": "en-US",
      "title": "美版",
      "rom": "gba/minish-cap.en-US.gba",
      "sort": 40
    },
    {
      "id": "en-EU",
      "title": "欧版（En/Fr/De/Es/It）",
      "rom": "gba/minish-cap.en-EU.gba",
      "sort": 50
    }
  ]
}
```

字段规则：

| 字段 | 规则 |
| --- | --- |
| `schema` | 必须为 `pjos.game-series/v1`。 |
| `id` | 必须与目录名一致；用于稳定状态键。 |
| `title` | 系列卡片标题；由数据提供，不做文件名猜测。 |
| `cover` | 可选的系列封面相对路径。 |
| `variants` | 至少一个版本；按 `sort` 升序、再按数组顺序显示。 |
| `variants[].id` | 系列内唯一、稳定的 ASCII 标识。 |
| `variants[].title` | 版本列表显示文本；由数据提供。 |
| `variants[].rom` | 相对于系列目录的可启动 ROM 路径。 |
| `variants[].cover` | 可选的相对封面路径。 |
| `variants[].default` | 最多一个；没有时使用排序后的第一个版本。 |

无法解析、ID 冲突、路径越界、ROM 缺失或扩展名不可启动的系列应整体跳过，并在扫描器日志中记录原因；不得降级成带有错误路径的可启动卡片。

## 扫描与输出契约

`pocketshell-games` 扫描器负责读取该结构，并在现有 `library.json` 的 `sections.games` 中发出两种条目：

```json
{
  "kind": "rom",
  "title": "Tetris",
  "path": "/storage/content/games/gba/Tetris.gba",
  "cover": "/storage/content/games/gba/Tetris.png"
}
```

```json
{
  "kind": "series",
  "id": "zelda-minish-cap",
  "title": "塞尔达传说：缩小帽",
  "cover": "/storage/content/games/series/zelda-minish-cap/cover.png",
  "variants": [
    {
      "id": "zh-Hans",
      "title": "简体中文",
      "path": "/storage/content/games/series/zelda-minish-cap/gba/minish-cap.zh-Hans.gba",
      "cover": "/storage/content/games/series/zelda-minish-cap/gba/minish-cap.zh-Hans.png",
      "default": true
    }
  ]
}
```

启动器只消费此通用结构：

1. `kind: "rom"` 直接启动 `path`。
2. `kind: "series"` 显示一个系列卡片；确认后打开其 `variants` 列表。
3. 版本选择后通过既有 `ROMLAUNCH` / `ROM launch` 协议启动其 `path`。
4. 最近选择记录为通用状态键 `series.<series-id>.lastVariant`，或等价的单一 JSON 状态文件；禁止再新增特定游戏键（例如 `zeldaLastRom`）。

UI 不得包含游戏名正则、单一系列 ID、某个 ROM 的固定标题或固定封面路径。封面解析属于扫描器，卡片组件只使用输出的 `cover`。

## 缩小帽迁移

当前卡上有五个版本：简体中文、繁体中文、日本、美国、欧洲多语言。迁移时将它们移动或复制为上文目录，并按清单顺序命名；原始文件名不再承担语言识别职责。

迁移验收：

1. 首页只出现一个“塞尔达传说：缩小帽”系列卡片。
2. 打开后恰好显示五个按 `sort` 排序的版本。
3. 每一版本显示自己的同名封面；缺失时回退到 `cover.png`。
4. 选择版本后启动的绝对路径与 `series.json` 对应。
5. 重启启动器后，该系列将最近选择的版本置顶；其他系列互不影响。
6. 删除或增加一个版本只需改目录及 `series.json`，不修改 TypeScript、Rust 或 shell 代码。

## 已安装应用目录约定

非内置 PocketJS 应用不写入启动器代码或资源包；启动器通过运行时的 `APPS\tlist` 通用协议发现它们。固定目录为：

```text
/storage/apps/
├── kanade.pocket       # 应用包；文件名（不含 .pocket）就是稳定应用 ID
└── kanade.png          # 可选同名封面；缺失时使用通用封面
```

规则：

1. 将任意符合当前 runtime profile 的 `<id>.pocket` 放入 `/storage/apps/`，即可成为首页卡片；`id` 使用 `[A-Za-z0-9_-]{1,64}`。
2. 若存在同目录 `<id>.png`，卡片和背景直接使用它；文件名不匹配或缺失时只回退到通用封面，不影响启动。
3. 显示名称由 ID 自动转换（例如 `kanade` → `Kanade`、`my-player` → `My Player`），不维护应用 ID→名称/图标/封面的前端映射表。
4. 确认卡片时启动器发送 `LAUNCH\t<id>`；运行时再次验证 ID 与 `/storage/apps/<id>.pocket`，然后交给既有 supervisor 启动。因此发现规则与启动规则使用同一个目录和 ID。
5. 删除这两个文件会在下次启动器重启后移除该卡片；不需修改前端、扫描器或 runtime。

2026-11-15 已按此约定安装 Kanade：`kanade.pocket` 与 `kanade.png`。它是离线视频与音频查看器的第一个验证样例，不含 Kanade 专用启动器代码。

## 实施边界

实施时需修改扫描器、`library.json` 类型与启动器的通用 series 渲染，并替换当前塞尔达专用分支。完成前不删除现有 ROM，也不自动移动用户内容。外部应用清理是独立任务，不与系列目录迁移混在同一次部署中。
