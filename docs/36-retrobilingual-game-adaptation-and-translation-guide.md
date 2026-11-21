# RetroBilingual 游戏双语翻译框架：实现原理与新游戏适配全流程指南

本文档全面阐述 BaseOS / PJOS 掌机内置的 **RetroBilingual**（实时游戏翻译与浮动 HUD 系统）的底层实现架构、翻译源文件存储规范，以及如何为任意 GBA 日文游戏添加中文双语对照翻译。

本指南编写严密、步骤清晰，可作为后续智能体或开发者独立适配新游戏的执行手册（Playbook）。

---

## 目录
1. [系统架构与翻译实现原理](#一系统架构与翻译实现原理)
   - [1.1 核心理念：零侵入式外挂翻译](#11-核心理念零侵入式外挂翻译)
   - [1.2 Libretro 核心钩子与帧生命周期](#12-libretro-核心钩子与帧生命周期)
   - [1.3 EWRAM 内存嗅探机制](#13-ewram-内存嗅探机制)
   - [1.4 浮动 HUD 渲染与文字排版](#14-浮动-hud-渲染与文字排版)
   - [1.5 物理按键与 RG34XX 硬件映射](#15-物理按键与-rg34xx-硬件映射)
   - [1.6 ROM SHA-256 门禁机制](#16-rom-sha-256-门禁机制)
2. [源码结构与数据文件存储位置](#二源码结构与数据文件存储位置)
   - [2.1 多仓库协同规范](#21-多仓库协同规范)
   - [2.2 翻译源数据存储分布](#22-翻译源数据存储分布)
   - [2.3 掌机运行时持久化文件](#23-掌机运行时持久化文件)
3. [为新游戏添加翻译的完整适配流程 (SOP)](#三为新游戏添加翻译的完整适配流程-sop)
   - [步骤 1：逆向定位日版 ROM 对话内存 ID](#步骤-1逆向定位日版-rom-对话内存-id)
   - [步骤 2：编写 C 语言 Game Adapter](#步骤-2编写-c-语言-game-adapter)
   - [步骤 3：准备对齐的翻译数据集 (JSON)](#步骤-3准备对齐的翻译数据集-json)
   - [步骤 4：使用 pack.py 打包二进制数据包](#步骤-4使用-packpy-打包二进制数据包)
   - [步骤 5：编译与集成部署](#步骤-5编译与集成部署)
4. [验证与测试体系](#四验证与测试体系)
   - [4.1 宿主自动化测试](#41-宿主自动化测试)
   - [4.2 掌机 ADB 真实按键注入与截屏验证](#42-掌机-adb-真实按键注入与截屏验证)

---

## 一、系统架构与翻译实现原理

### 1.1 核心理念：零侵入式外挂翻译
传统的汉化方式往往依赖于对 ROM 文件的二进制“打补丁”（Romhack），修改程序指针、破解字体排版程序或扩充 ROM 容量。这种方式存在严重弊端：
1. 汉化 ROM 往往引入未知 Bug 或死机；
2. 破坏了原版日文的纯粹体验与存档通用性；
3. 无法让玩家在原汁原味的日版 ROM 下随时对照中文。

**RetroBilingual** 采用的是**外挂式实时 HUD 架构**：
- 玩家运行的是**未经修改的原版日文 ROM**。
- 模拟器（libretro-mgba）在逐帧运行期间，通过轻量级 C 钩子实时监测 GBA 内存（EWRAM）。
- 当检测到屏幕出现剧情对话时，获取当前对话的索引 ID 与分页。
- 玩家按下实体快捷键（RG34XX 上为实体的 **X 键**）时，屏幕浮现一层极低功耗的点阵像素 HUD 窗口，瞬时呈现对齐的中文翻译；再次按下或翻页时自动同步。

```
┌────────────────────────────────────────────────────────────────┐
│                      mGBA Libretro Core                        │
│                                                                │
│  [Clean JP ROM] ──> [Emulation CPU] ──> [EWRAM 0x02000000]     │
│                             │                  │               │
│                             ▼                  ▼ (Poll RAM)    │
│                     [Video Framebuffer]   [RetroBilingual]     │
│                             │                  │ (Lookup pack) │
│                             │                  ▼               │
│                             └─────────> [Overlay Floating HUD] │
│                                                │               │
│                                                ▼               │
│                                      [RG34XX Screen 720×480]   │
└────────────────────────────────────────────────────────────────┘
```

---

### 1.2 Libretro 核心钩子与帧生命周期
RetroBilingual 编译进 `mgba_libretro.so`，其生命周期钩接在核心的几个核心回调：
- `retro_load_game()`：
  - 计算当前装载 ROM 的无填充文件大小与 SHA-256 哈希。
  - 在适配器注册表（`rb_adapter_match`）中寻找完全匹配的适配器。
  - 打开并载入 `/storage/.config/pocketjs/retrobilingual.pack`。
- `retro_run()`（每秒 60 次）：
  - 核心执行一帧模拟后，调用 `rb_frame()`。
  - 读取当前手柄按键掩码。
  - 调用匹配适配器的 `read_dialogue(core, keys, &text_id, &page)`。
  - 若处于显示状态，直接在模拟器输出的 RGB565 / XRGB8888 视频缓冲上混合绘制 1bpp 字体图层。
- `retro_reset()` / `retro_unserialize()`：
  - 调用适配器的 `reset()`，重置对话追踪游标。

---

### 1.3 EWRAM 内存嗅探机制
GBA 拥有 256KB 的片外工作内存（EWRAM，地址 `0x02000000` 到 `0x0203FFFF`）。所有商业 RPG 游戏都会在 EWRAM 的固定数据结构中记录当前对话框的状态。
例如：
- **塞尔达传说：缩小帽（TMC）**：
  - 消息索引：`0x02000000 + 0x1270`（16 位整数，低位字节优先）。
  - 分页游标：`0x02000000 + 0x1274`。
- **黄金太阳：开启的封印（Golden Sun）**：
  - 文本索引：通过游戏全局事件句柄与消息栈读取。
  - 按 A 键推进时状态码从 `WAIT_A` 转为下一段。

适配器只需每帧读取这几个字节，即可实现零开销（微秒级）的精准对话捕获。

---

### 1.4 浮动 HUD 渲染与文字排版
1. **尺寸与宽度**：
   - RG34XX 的有效显示逻辑分辨率为 360×240（在 720×480 面板上 2× 整数缩放）。
   - HUD 的单行宽度固定为 **15 个全角汉字**（30 字符宽）。
   - 使用紧凑的 12px 点阵字体（Fusion Pixel），既节省显存，又具备极高的复古像素质感。
2. **位置自适应（Avoidance）**：
   - 适配器报告游戏原生对话框是在屏幕**上方**还是**下方**。
   - RetroBilingual HUD 会自动移动到画面的另一侧（`AUTO` 模式：原生框在下，HUD 浮于上方；原生框在上，HUD 浮于下方），确保绝不遮挡原版立绘或对话。
3. **滚动与分页**：
   - 若一段翻译在 15 字宽下需要多页，支持左右键横向滚动，无需修改核心状态。

---

### 1.5 物理按键与 RG34XX 硬件映射
RG34XX 的按键在 Linux 内核 DTS 与驱动层有特殊的键位反转特性：
- **物理 X 键（顶侧印刷 X）**：
  - Linux evdev 编码：`307` (`BTN_NORTH` $\to$ RetroArch `input_player1_x_btn = "3"`）。
  - **功能：瞬时翻译键**。游戏中按下立即弹出/关闭当前对话的中文翻译 HUD。
- **物理 Y 键（左侧印刷 Y）**：
  - Linux evdev 编码：`306` (`BTN_WEST` $\to$ RetroArch `input_player1_y_btn = "2"`）。
  - **功能：快捷功能菜单**。弹出 RetroBilingual 5 槽位即时存档卡片与 HUD 设置（位置切换/按键行为切换）。
- **物理 A 键 / B 键**：
  - 物理 A（右侧）= `304` (`BTN_SOUTH`，对应确认)。
  - 物理 B（下侧）= `305` (`BTN_EAST`，对应取消/返回)。

---

### 1.6 ROM SHA-256 门禁机制
RetroBilingual 的适配器和打包文件具有**极严格的 ROM 校验**：
- 适配器定义了 `rom_size` 与 `sha256_hex`。
- 数据包文件头也记录了目标 ROM 的 SHA-256。
- 为什么必须这样设计？
  因为不同版本（日版 rev0、日版 rev1、修改版、汉化版）的 EWRAM 内存偏移完全不同！如果将适配于日版 clean dump 的偏移读取应用到汉化版或错误版本的 ROM 上，会导致指针错位甚至读取到垃圾数据。
  因此，**日文 ROM 必须使用干净、权威的 No-Intro / 官方 Dump**。

---

## 二、源码结构与数据文件存储位置

### 2.1 多仓库协同规范
项目代码在主机上分为两个核心目录：
1. **`~/development/retrobilingual`**（上游独立代码库）：
   - `core/retrobilingual.c` & `core/retrobilingual.h`：核心引擎。
   - `core/adapters/`：所有游戏适配器源文件（`adapter.h`, `tmc.c`, `golden_sun.c`, `registry.c`）。
   - `tools/pack.py`：打包工具。
   - `tests/`：主机与算法测试。
2. **`~/development/PJOS-LINUX`**（系统集成仓库）：
   - `src/retrobilingual.c` 与 `src/adapters/`：核心在系统层镜像。
   - `tools/build-retrobilingual-mgba-h700.sh`：交叉编译 Docker 构建脚本。
   - `resouces/game/series/`：游戏 ROM 与多语言封面资源库。

> [!IMPORTANT]
> 修改核心代码或适配器时，应优先在 `~/development/retrobilingual` 中编辑并测试，然后运行 `make sync` 或 `make build` 自动同步至 `PJOS-LINUX`。

---

### 2.2 翻译源数据存储分布
翻译源文本存放于以下位置：

| 游戏系列 | 翻译工程目录 / 源数据文件 | 说明 |
| :--- | :--- | :--- |
| **塞尔达传说：缩小帽 (TMC)** | `data/tmc_bilingual_aligned.json`<br>`data/tmc_chinese_export.json`<br>`resouces/game/series/zelda-minish-cap/translation-work/` | 完整的双语对齐 JSON，包含每一个 Message ID、分页索引及对应译文。 |
| **黄金太阳：开启的封印 (GS1)** | `resouces/game/series/golden-sun/translation-work/work/golden-sun-text-zh.json`<br>`~/development/retrobilingual/tools/golden_sun_build.py` | 提取自汉化版本的对话文本集，通过 `golden_sun_build.py` 按 `0x01` 控制符完成精确分页与人名宏替换。 |

---

### 2.3 掌机运行时持久化文件
掌机（RG34XX）上的运行环境文件分布如下：
- **二进制翻译数据包**：
  `/storage/.config/pocketjs/retrobilingual.pack`
  （这是运行时唯一加载的紧凑格式二进制文件，内嵌点阵字模与按 ID 排序的检索表）。
- **用户配置文件**：
  `/storage/.config/pocketjs/retrobilingual.conf`
  （记录 `x_action`、`slot`、`hud_pos` 等设置）。
- **即时存档状态槽位**：
  `/storage/.config/pocketjs/retrobilingual-slot[1-5].state`
  （5 槽位即时存档，带有解析出游戏内心之容器、卢比数、所在区域的元数据卡片）。
- **Libretro 核心**：
  `/storage/System/compat/lib/libretro/mgba_libretro.so`。

---

## 三、为新游戏添加翻译的完整适配流程 (SOP)

如果后续要为其他日文游戏（如《火焰之纹章：封印之剑》、《烈火之剑》、《圣魔之光石》、《黄金太阳：失落的时代》等）增加 X 键中文翻译功能，请严格遵循以下标准化四步工作流：

### 步骤 1：逆向定位日版 ROM 对话内存 ID
在 PC 上使用 **mGBA**（或 No$gba）启动目标游戏的日版 clean ROM：
1. **寻找消息 ID（Message ID / Text ID）**：
   - 推进到任意对话场景（如主角与 NPC 对话）。
   - 打开 mGBA 菜单：`Tools -> Memory Search`（内存搜索）。
   - 搜索范围选择 `EWRAM`（`0x02000000` - `0x0203FFFF`），数据类型选 `16-bit unsigned`。
   - 对话进行时搜索变化值；当进入下一句话时，再次点击 `Changed` 筛选；对话结束退出时，搜索变成 `0` 的地址。
   - 重复 2-3 次对话，即可锁定唯一的 16 位全局 Message ID 内存地址（例如 `0x02001270`）。
2. **寻找分页游标与按 A 翻页状态**：
   - 观察 Message ID 附近的字节。通常距离该地址偏移 +2、+4 或 +8 字节处，会有一个 8 位的当前页码计数器（从 `0` 开始，按一次 A 键递增 `1`），或者一个标识状态的标志位（如 `0x02 = 等待按A`，`0x01 = 正在打字`）。
   - 记录下这两个内存偏移量。

---

### 步骤 2：编写 C 语言 Game Adapter
在 `~/development/retrobilingual/core/adapters/` 目录下创建新文件，例如 `fe6.c`：

```c
#include "adapter.h"
#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/* 1. 定义日版 Clean ROM 的准确字节数与 SHA-256 */
#define FE6_JA_ROM_SIZE  8388608
#define FE6_JA_SHA256    "..." // 通过 sha256sum 计算的真实 64 位小写十六进制

static uint16_t sCurrentTextId = 0;
static uint8_t  sCurrentPage = 0;

static void fe6_reset(void) {
    sCurrentTextId = 0;
    sCurrentPage = 0;
}

static int fe6_read(struct mCore* core, uint16_t keys,
                    uint16_t* out_text_id, uint8_t* out_page) {
    if (!core) return 0;
    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba || !gba->memory.wram) return 0;

    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;

    /* 2. 从发现的 EWRAM 偏移读取 16 位 Text ID (例如 0x1A2B0) */
    uint16_t text_id = (uint16_t)(ewram[0x1A2B0] | (ewram[0x1A2B1] << 8));
    
    // 如果不在对话状态则返回 0
    if (text_id == 0 || text_id == 0xFFFF) {
        sCurrentTextId = 0;
        sCurrentPage = 0;
        return 0;
    }

    /* 3. 分页追踪：如果 text_id 发生变化，重置页码 */
    if (text_id != sCurrentTextId) {
        sCurrentTextId = text_id;
        sCurrentPage = 0;
    }

    /* 读取游戏自身的分页游标，或者依据按键/等待标志更新 sCurrentPage */
    uint8_t page = ewram[0x1A2B4];

    *out_text_id = text_id;
    *out_page = page;
    return 1;
}

const RBAdapter g_rb_adapter_fe6 = {
    .game_id = "fe6",
    .title = "Fire Emblem: Fuuin no Tsurugi",
    .rom_size = FE6_JA_ROM_SIZE,
    .sha256_hex = FE6_JA_SHA256,
    .reset = fe6_reset,
    .read_dialogue = fe6_read,
    .page_slack = 0,
};
```

#### 在注册表中注册
打开 `~/development/retrobilingual/core/adapters/adapter.h`：
```c
extern const RBAdapter g_rb_adapter_fe6;
```
打开 `~/development/retrobilingual/core/adapters/registry.c`：
```c
const RBAdapter* rb_adapter_match(uint32_t rom_size, const uint8_t sha256[32]) {
    ...
    if (rom_matches(rom_size, sha256, &g_rb_adapter_fe6)) return &g_rb_adapter_fe6;
    return 0;
}
```

---

### 步骤 3：准备对齐的翻译数据集 (JSON)
准备一个 UTF-8 编码的 JSON 数据集，格式遵循 `RBTextEntry` 规范：

```json
[
  {
    "source_id": "01A4",
    "page_index": 0,
    "text": "罗伊，你必须要活下去。\n继承艾利乌德公爵的意志。"
  },
  {
    "source_id": "01A4",
    "page_index": 1,
    "text": "我们一定会坚守到底的！"
  }
]
```

#### 关键排版规范：
> [!WARNING] 严禁按宽度随意拆分 page_index！
> - `page_index` 的推进必须与游戏内玩家按 **A 键翻页**的事件 1:1 严格一致。
> - 一页内部如果有多行，使用换行符 `\n` 分隔（建议一页最多两行）。
> - 绝对不要因为译文比较长就自动人为增加 `page_index`，否则玩家在游戏中按一次 A 键，游戏跳到了下一句话，但翻译却卡在上一句话的半截。
> - 若单页汉字超过 15 个字，RetroBilingual 会自动允许玩家在 HUD 内使用手柄左右键滚动查阅全部文本。

---

### 步骤 4：使用 pack.py 打包二进制数据包
运行打包脚本 `tools/pack.py`：

```bash
python3 ~/development/retrobilingual/tools/pack.py \
  --texts /path/to/translated_entries.json \
  --source-rom-sha256 <日版Clean_ROM的SHA256> \
  --font $HOME/development/pocketshell/app/fonts/FusionPixel12.ttf \
  --font-size 12 \
  --output /tmp/retrobilingual.pack
```

打包工具会自动：
1. 提取所有在译文中出现的汉字与标点；
2. 光栅化生成只包含有效字符的 1bpp 字体图集（Font Atlas）；
3. 将所有条目按 `(source_id << 8) | page_index` 升序排列，生成 $O(\log N)$ 二分检索表；
4. 校验目标 ROM 哈希并嵌入文件头；
5. 输出尺寸极小（通常仅几百 KB）、可直接快速 mmap 载入的 `.pack` 文件。

---

### 步骤 5：编译与集成部署
1. **同步与编译 Libretro 核心**：
   ```bash
   cd ~/development/retrobilingual
   make sync
   make build
   ```
   （或在 `PJOS-LINUX` 下直接执行 `tools/build-retrobilingual-mgba-h700.sh`，构建出适配 Allwinner H700 的 `mgba_libretro.so`）。
2. **部署数据包与核心到 RG34XX**：
   ```bash
   # 推送新编译的动态库
   ssh hx90 "adb -s 5c0010894414c802512 push /path/to/mgba_libretro.so /storage/System/compat/lib/libretro/"

   # 推送生成的数据包
   ssh hx90 "adb -s 5c0010894414c802512 push /tmp/retrobilingual.pack /storage/.config/pocketjs/retrobilingual.pack"
   ```

---

## 四、验证与测试体系

### 4.1 宿主自动化测试
在将核心部署到硬件前，首先必须在主机运行测试用例：
```bash
cd ~/development/retrobilingual
make test
```
- `tests/test_host.py`：模拟 libretro 环境加载 pack，测试快速二分查词、越界容错、回滚逻辑。
- `tests/test_pack.py`：验证 pack 文件头的魔数、版本号、字模边界及校验和。

---

### 4.2 掌机 ADB 真实按键注入与截屏验证
由于 RG34XX 连接在编译测试机上，智能体可通过 ADB 编写非侵入式自动测试脚本对实机进行端到端验证：

#### 1. 注入按键流程
向 `/dev/input/event1` 写入标准的 Linux `struct input_event`（24 字节）：
- **确认启动游戏**：注入 `BTN_SOUTH`（code `304`）。
- **呼出翻译 HUD**：注入 `BTN_NORTH`（code `307`，即实体 **X 键**）。
- **呼出存档菜单**：注入 `BTN_WEST`（code `306`，即实体 **Y 键**）。

#### 2. 读取当前活动显存截屏
```bash
# 1. 查询当前活动的显存偏移（双缓冲 720×960）
PAN=$(ssh hx90 "adb -s 5c0010894414c802512 shell 'cat /sys/class/graphics/fb0/pan'")

# 2. 导出显存 RAW 数据
ssh hx90 "adb -s 5c0010894414c802512 shell 'dd if=/dev/fb0 of=/tmp/frame.raw bs=4096 count=675'"
ssh hx90 "adb -s 5c0010894414c802512 pull /tmp/frame.raw /tmp/frame.raw"
scp hx90:/tmp/frame.raw /tmp/frame.raw

# 3. 根据活动偏移裁剪出 720×480 的实际显示内容（以 0,480 为例）
convert -size 720x960 -depth 8 bgra:/tmp/frame.raw -crop 720x480+0+480 +repage /tmp/fb_active.png
```

通过查看 `/tmp/fb_active.png`，可以直接客观确认：
1. 日文游戏是否处于正常运行画面；
2. 按下 X 键后浮动 HUD 是否准确出现；
3. HUD 内部的汉字点阵是否清晰完整、有无错位或未映射字符。

---
*文档编制完成于 2026-11-21，已同步至 PJOS-LINUX 与 RetroBilingual 文档库。*
