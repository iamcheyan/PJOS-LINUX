# ChroMagic 点阵 UI 前期调查

## 1. 调查结论

本次调查针对仓库：<https://github.com/cursedtoast2/ChroMagic>

- 克隆位置：`~/development/ChroMagic`
- 调查版本：`e611a1ef36eb9aa93f706d836f5b0e46129d7137`
- 上游提交标题：`Fix SD card initialization and release ChroMagic 1.0.1`
- 本仓库内的参考归档：`references/chromagic-ui/`
- 归档体积：约 26 MB（其中约 21.8 MB 为后来补充的完整 Fusion Pixel 中英日字体）

ChroMagic 值得借鉴的核心并不是它的 FPGA/Game Boy 播放链路，而是 MCU 菜单使用的一套非常完整的低分辨率 UI 语言：1-bit 点阵字体、固定像素网格、少量高对比颜色、像素图标、细边框、点状分页指示器、静态菜单插图和状态控件。它可以作为 PJOS-LINUX 当前现代化 PocketShell UI 的“复古点阵主题参考实现”。

但有一个必须先纠正的认识：仓库里虽然存在日文命名的 `JF-Dot-K14.ttf` 生成注释，当前提交实际生成的 `jf_dot_k14.c` 范围是 ASCII `32-127`，并不是完整日文字体。仓库中没有原始 TTF 文件，也没有可直接证明的汉字/假名覆盖。后续不能把它直接宣称为“英文和日文完整字体”。

## 2. 参考目录内容

`references/chromagic-ui/` 是隔离的只读式参考资料，不参与当前 PocketShell 构建，也没有把任何文件接入 `app/`、`overlay/` 或运行时。

| 目录 | 内容 | 后续价值 |
| --- | --- | --- |
| `fonts/` | ChroMagic 的三份 LVGL 字体，以及完整 Fusion Pixel 中英日字体包 | 字形比例、像素笔画、CJK 覆盖和字体管线参考 |
| `images/` | 全部 UI PNG、LVGL C 图像数组和 CMake 文件 | 图标、选中态、开关、菜单卡片、品牌装饰参考 |
| `ui-source/osd/` | OSD、palette、display、controls、system 相关源码 | 颜色、状态控件、转场、固定布局和交互结构参考 |
| `ui-source/tab/` | tab list、tab dots、tab table 源码 | 菜单分页、列表选择框和点阵分页参考 |
| `ui-source/menu_mgr/` | 顶层菜单管理与顶部 tab 代码 | 菜单层级、横向 tab 切换、资源挂载方式参考 |
| `ui-source/common/` | 颜色、线条和 OSD 共享定义 | 像素坐标/颜色辅助接口参考 |
| `tools/` | `generate_backups_accent.py` | 从图像生成 1-bit LVGL 资源的处理思路参考 |
| `licenses/` | README、NOTICE、`mcu-LICENSE`、`fpga-LICENSE`、源快照 | 来源、归属和再分发前的法律依据 |

原仓库完整 clone 保留在 `~/development/ChroMagic`，因此参考目录没有复制 FPGA bitstream、Game Boy 核心、硬件驱动和固件构建产物。这些内容与 PocketShell UI 没有直接复用价值，且会让参考目录从几 MB 膨胀到数百 MB 级别。

## 3. UI 系统拆解

### 3.1 视觉基线

ChroMagic 的 MCU UI 使用 LVGL，但设计方法更接近一张手工排版的低分辨率画布：

- 大量尺寸以 `px` 常量直接表达，而不是自适应布局。
- 颜色是黑底、白色主文字、灰色次文字和每个菜单自己的 accent color。
- 选中态通常只有一像素边框、反色/高亮颜色或白灰变化，没有现代 UI 的阴影、圆角卡片和渐变层。
- 图像资源大多是 1-bit、RGB565 或带 alpha 的小位图，尺寸严格贴合布局。
- 文字、图标、边框和分隔线共用同一个整数像素网格，避免亚像素模糊。
- 状态变化主要通过位置、颜色和少量帧/转场表达，而不是复杂动画。

这些特点适合转换成严格的整数像素网格。当前 PocketShell checkout 已经采用 `720×480` 逻辑视口直接对应 `720×480` 物理输出，不再是早期调查时的 `480×320 → 720×480` 1.5× presentation。点阵主题可以保持这个运行时 profile，同时在设计层使用隐含的 `360×240 @2×` 网格；这样既不需要重做 package admission profile，又能保证每个设计像素对应均匀的 `2×2` 面板像素。

### 3.2 顶层菜单和 tab

`mcu/components/menu_mgr/menu_mgr.c` 展示了一套适合掌机的顶层导航：

- 菜单内容图像统一在约 `143×106` 的资源框中。
- 顶层内容从约 `(8, 7)` 的固定原点开始。
- 顶部 tab 用小尺寸边框、glyph 和 accent 色区分当前栏目。
- 当前 tab 通过白色/彩色边框激活，非当前 tab 退为灰色。
- 切换 tab 时显式删除旧 LVGL 对象，再重建当前页面，避免状态对象残留。
- `menu_backups_accent.c` 是单独的 1-bit accent mask，可以把同一图形重着色成当前菜单色。

这不是可以原样移植到 Solid/TSX 的代码，但它提供了明确的组件模型：`MenuTab`、页面资源、accent、当前页绘制回调、切页清理回调。后续可把它转成 PocketShell 的 `category -> page -> item` 数据结构。

### 3.3 列表选择器

`ui-source/tab/tab_list/` 的布局很有参考价值：

- 菜单原点约为 `(7, 7)`。
- 列表原点约为 `(8, 35)`。
- 文本偏移约为 `(3, 2)`。
- 分隔线位于约 `x=65`，从 `y=35` 延伸到 `y=98`。
- 选中框约 `55×11`，边框宽度 1 px。
- 当前项目使用白色文字和 accent 边框，非当前项目使用灰色文字。

它的价值在于给出了一个很克制的掌机列表比例：左侧是窄列表，右侧是内容/预览，选中框不填充背景，只画轮廓。这个比例可用于设计 PocketShell 的“库列表 + 封面/详情”点阵主题，但需要重新适配当前游戏封面和中文标题。

### 3.4 点状分页器

`ui-source/tab/tab_dots/tab_dots.c` 使用白/灰两种 `2×2` 点阵资源，并用 `5 px` 间距排列；当前项为白点，其余为灰点，上下还配有 `5×3` 箭头。

这里有一个很实用的工程细节：LVGL 某版本不能稳定绘制 1 px 图像，所以项目用 `2×2` 图片模拟点。这说明移植到 PocketJS 时应避免依赖单像素 primitive 是否在缩放和 CPU raster path 下保持一致；更稳妥的方法是使用明确的 2×2 逻辑像素资源，或在自己的像素绘制层内定义整数矩形。

### 3.5 开关和状态控件

以下资源可以直接作为点阵控件参考：

- `img_toggle_on/off`：约 `66×31`。
- `img_option_en/dis`：约 `66×20`，用于两项模式切换。
- `img_a_right`、`img_b_left`：约 `7×13` 的操作提示箭头。
- `icon_bat_large_*`：约 `53×19` 的多色电量图。
- `icon_charging`：约 `9×9` 的充电图标。
- `img_arrow_up/down`：约 `5×3` 的列表箭头。
- `img_dot_white/grey`：约 `2×2` 的分页点。

`frameblend.c` 与 `screen_transit_ctl.c` 还展示了“资源 + 文本覆盖”的控件做法：背景是位图，当前状态文字用同一套点阵字体叠加，切换时删除并重建对应对象。这比为每个文案导出整张图片更适合后续支持英文、日文和中文，但前提是 PocketJS 的字体栅格化必须完全采用 nearest-neighbor/整数位置。

### 3.6 点阵字体

仓库包含三份 LVGL 1-bit 静态字体：

| 文件 | 注释中的尺寸 | 当前源码覆盖 | 调查判断 |
| --- | ---: | --- | --- |
| `fingfai.c` | 5 px | `U+0020`–`U+007F` | 极小标签、状态栏、辅助信息；可借鉴比例，不适合作为长标题 |
| `chibit_mr.c` | 8 px | 当前文件为小型 Latin glyph 集 | 主菜单短标签、按钮提示的优先候选；需补全覆盖统计 |
| `jf_dot_k14.c` | 14 px | 生成注释明确为 `32-127` | 大标题/重点数字的像素比例参考；不能当作完整日文字体 |

三份字体都是已经转换成 LVGL C 数组的产物，注释显示至少 `fingfai` 和 `JF-Dot-K14` 使用了 `--bpp 1 --no-compress`。仓库没有 TTF/OTF 原文件，所以不能直接获得字形授权条款、完整 Unicode 覆盖或重新生成参数。后续如果要把字体真正放进 PJOS-LINUX，应先单独确认原字体授权，并以 PocketJS 支持的字体格式重新制作资源。

为解决完整中英日点阵字形来源，本参考目录后来补充了官方 Fusion Pixel `2026.11.10` 的三份完整 12px 等宽 TTF：

| 文件 | 目标排版 | cmap 码点数 | 用途 |
| --- | --- | ---: | --- |
| `fusion-pixel-12px-monospaced-latin.ttf` | Latin/西文 | 37,939 | 英文 UI、英文标题和西文标点 |
| `fusion-pixel-12px-monospaced-zh_hans.ttf` | 简体中文 | 37,939 | 中文 UI、简体中文游戏标题 |
| `fusion-pixel-12px-monospaced-ja.ttf` | 日文 | 37,939 | 日文 UI、假名和日文字形 |

文件位于 `references/chromagic-ui/fonts/fusion-pixel-full/`，并附有版本、哈希、覆盖验证和完整许可证。三个字体包含相同规模的广泛字符集合，但地区字形与标点习惯不同，应按当前 UI 语言选择，而不是把 `ja` 作为中文字体。它们是完整参考源；后续生产构建仍应按固定文案和实际游戏标题裁剪，避免直接把约 21.8 MB 的三份 TTF 全部塞进 launcher 包。

## 4. 可迁移资源分级

### A 级：优先作为设计参考，低风险重绘

- `img_dot_white/grey`、`img_arrow_up/down`、`img_a_right`、`img_b_left` 的几何比例。
- `menu_*.png` 的 143×106 菜单卡片构图、留白和线条密度。
- `tab_list.c` 中的选中框、分隔线和文字层级。
- `tab_dots.c` 的白/灰分页点和窄列布局。
- `style.c` 中的 palette preview 色彩组织方式。
- `menu_mgr.c` 中的顶部 tab、accent 和页面清理模型。

这些内容建议在后续用 PocketShell 原生绘制 API/TSX 重新实现，只把原图作为参考，不直接把 GPL 代码拷入产品。

### B 级：可在许可证确认后转换或适配

- `fonts/*.c` 的点阵位图和字形元数据。
- `images/*.png` 的电量、开关、品牌和菜单图。
- `images/*.c` 中 LVGL 图像数据的像素颜色、alpha 和尺寸。
- `img_magician_hat.c`、`img_magician_wand.c` 的 4-bit indexed pixel-art 图像。
- `generate_backups_accent.py` 中把图像转换为 alpha mask 的做法。

这些是最接近“直接拿来用”的资源，但它们不是自动获得公共领域/宽松许可证。必须保留来源和许可证，确认是否允许复制、改作和随 PJOS-LINUX 发行。

### C 级：不建议直接移植

- `mcu/components/osd/**/*.c` 的 LVGL/ESP-IDF/Zephyr 风格运行时代码。
- `menu_mgr.c`、`tab_*` 的 LVGL 对象生命周期代码。
- 电池、固件状态、串口/卡备份和硬件按钮处理代码。
- `fpga/` 下的 bitstream、Game Boy 核心、HDMI/USB/SD 控制逻辑。

它们可以继续作为行为和布局研究资料，但与 PocketJS Solid/TSX 的运行模型不同，直接移植会带来不必要的 LVGL、ESP-IDF 和 GPL 代码耦合。

## 5. 与 PJOS-LINUX 的适配判断

### 5.1 坐标和缩放

RG34XX 使用 3.4 英寸、`720×480`、3:2 的 IPS 面板。按面板对角线估算，像素密度约 255 PPI，可见区域约为 72×48 mm。设备的 `/dev/fb0` 是 `720×960` 双页缓冲，但一次可见区域仍然只有 `720×480`；不能把 960 当成可布局高度。

当前 PocketShell 的 `app/pocket.json` 和 `config/profile.ts` 均声明 `720×480` logical、`720×480` physical、density 1 和 `integer-fit`，主界面也直接按 `720×480` 布局。这意味着当前运行链路是 1:1 直出，不需要 fractional presentation。后续若 profile 再变化，应以实际 checkout 和打包出的 profile hash 为准，而不是沿用旧调查记录。

#### 推荐方案：720×480 运行时，360×240 设计网格，2×呈现

点阵主题的首选基准是：

```text
运行时/物理画布：720 × 480
设计网格：        360 × 240
设计像素映射：    1 → 2 × 2 个面板像素
基础字体字模：    12 px → 24 px 输出
```

不必把 PocketJS profile 改回 360×240；可以继续以 720×480 编写组件，但所有点阵 chrome 按 2px 网格落位。也就是说，设计稿中的 `(x, y, w, h)` 统一乘 2 后写入当前 TSX。这样可以保留当前 launcher 的 profile、运行时准入和全屏布局，同时得到真正均匀的点阵像素。

具体约束：

- 点阵元素的 `x/y/width/height` 尽量使用偶数。
- 基础边框和分隔线使用 2 个物理像素，即设计网格中的 1 px。
- 最小分页点使用 `4×4` 物理像素，对应设计网格中的 `2×2`。
- 12px 字模以 24px 输出；图标和 alpha mask 使用 nearest-neighbor 2×。
- 点阵图标禁止线性过滤；照片封面和模糊背景可独立使用平滑采样。
- 不要把“720×480 直接布局”理解为所有控件都必须使用 1px 物理线条；1px 在 3.4 英寸面板上过细，也会破坏统一的 2×网格。

这个方案兼顾了信息密度与复古视觉。360 设计像素宽度允许一行容纳约 30 个 12px 全角字格，实际界面加入边距后仍足够显示大部分游戏标题、状态和设置项。

#### 强复古备选：240×160 设计网格，3×呈现

更接近 ChroMagic/GBA 低分辨率观感的备选方案是：

```text
运行时/物理画布：720 × 480
设计网格：        240 × 160
设计像素映射：    1 → 3 × 3 个面板像素
基础字体字模：    12 px → 36 px 输出
```

这个方案的像素颗粒最强，适合启动画面、系统菜单、极简游戏选择器和大图标页面，但每行理论上只有约 20 个全角字格，并且垂直方向只能容纳约 10–12 行有效内容。它不适合作为设置、网络信息、文件列表和长游戏标题页面的唯一布局基准。

#### 不推荐：480×320 设计网格，1.5×呈现

早期 `480×320 → 720×480` 路径虽然可以通过 nearest-neighbor 和 fractional renderer 工作，但不适合作为纯点阵主题的设计基准。1.5×不能把每个源像素映射为同样大小的物理方块，像素列/行会交替占用 1 或 2 个面板像素，导致：

- 1px 边框出现不均匀粗细；
- 字体竖笔和横笔节奏不一致；
- 2×2 点阵图标失去方形比例；
- nearest-neighbor 可以避免模糊，却无法消除非整数缩放造成的尺寸不均匀。

因此完整点阵主题只选 2×或3×整数网格。1.5×路径可继续作为旧 profile/运行时兼容能力保留，但不应成为新视觉方案的设计基础。

#### Fusion Pixel 字号映射

Fusion Pixel 的基础设计尺寸为 12px。在约 255 PPI 的 RG34XX 面板上，不同整数倍率的实际高度与用途如下：

| 输出字号 | 字模倍率 | 面板高度约 | 建议用途 |
| ---: | ---: | ---: | --- |
| 12 px | 1× | 1.2 mm | 次要状态数字或空间极紧的英文；不作为中文主字号 |
| 24 px | 2× | 2.4 mm | 标准中文/日文正文、菜单项、游戏标题 |
| 36 px | 3× | 3.6 mm | 页面标题、当前选中项、重要状态 |
| 48 px | 4× | 4.8 mm | 启动画面、弹窗重点和少量大标题 |

主界面的默认点阵字号应为 24px，标题使用 36px。12px 中文虽然技术上可渲染，但在 3.4 英寸屏幕上的复杂笔画过密，只适合辅助信息。应优先使用 12/24/36/48 这些字模整数倍，避免 18px、30px 等 1.5×或2.5×尺寸。

#### 验证要求

桌面截图只能验证布局，最终验收必须检查 720×480 framebuffer 可见页，并覆盖：

1. 24px 简体中文、24px 日文假名、24px Latin 的混排与 baseline。
2. 36px 页面标题和长中文游戏名的裁切/省略策略。
3. 2px 边框、4×4 分页点和 2×像素图标是否保持均匀。
4. 封面平滑采样与点阵 chrome nearest-neighbor 是否能分开控制。
5. `normal/large/huge` 字体设置是否仍落在整数倍率，或是否需要为点阵主题使用独立字号表。
6. 包体、glyph atlas 内存、首帧时间和页面切换性能。

### 5.2 字体策略

不能直接用 ChroMagic 三份字体解决当前库标题需求。PJOS-LINUX 已经有简体中文和日文假名的 glyph staging 机制，因此更合理的方向是：

- 用 ChroMagic 的英文字形比例作为 Latin UI 字体设计参考。
- 使用本参考目录中授权与覆盖范围明确的 Fusion Pixel `latin`、`zh_hans`、`ja` 完整字体作为源文件，并在构建阶段按文案和游戏库标题裁剪。
- 默认正文/菜单使用 24px（12px 字模 2×），标题使用 36px（3×）；状态栏只有在实机可读性通过时才允许降到 12px。
- 对没有覆盖的字符保留明确 fallback，而不是静默替换成现代抗锯齿字体。
- 以实际 `魔女的冒险`、英文长标题、日文假名混排和数字电量文案作为回归样本。

### 5.3 图像和动态背景

ChroMagic 的资源是静态菜单图，而 PJOS-LINUX 当前还有封面、模糊背景、收藏和类别导航。因此移植时应采用“点阵 chrome + 当前动态内容”的混合方案：

- 顶部状态栏、分页点、方向箭头、选中框和 footer 使用点阵风格。
- 游戏封面保留真实封面，但通过整数裁剪、nearest-neighbor 或低色阶处理使其与点阵 chrome 协调。
- 背景模糊应作为可选主题效果，不能让它破坏文字和 1 px 线条的高对比度。
- 空封面 fallback 可以参考 `img_chromatic*` 的有限色阶和透明像素，而不必复刻 ChroMagic 品牌图形。

## 6. 许可证和来源风险

仓库根 README 指出 `mcu/` 和 `fpga/` 分别受各自 LICENSE 约束，两个 LICENSE 文件都是 GPLv3 文本；NOTICE 还列出 ModRetro、MiSTer Gameboy、mist-devel/gameboy、SameBoy 等上游来源。`fpga` 内的 Game Boy boot ROM 源文件保留了 MIT 许可声明，但这不等于整个仓库或 MCU UI 资源都是 MIT。

尤其需要注意：

- 生成后的字体 C 文件位于 GPLv3 的 `mcu/` 树内，但原始 `FINGFA__.TTF` 和 `JF-Dot-K14.ttf` 不在仓库中。
- PNG 与对应 C 数组看起来是项目资源，但仓库没有为每个图片逐项写出独立授权声明。
- `img_chromatic*`、magician 图形和菜单品牌图不能在没有确认商标/版权边界的情况下作为 PJOS-LINUX 的品牌资产。
- 如果直接复制 GPLv3 覆盖的代码或资源并把它们链接/合并进闭源分发物，可能触发源代码提供和同许可证分发义务。

本次归档因此保留了 `licenses/mcu-LICENSE`、`licenses/fpga-LICENSE`、`licenses/NOTICE` 和上游 README，后续任何“直接采用”决定都应逐项记录来源、许可证、是否改作以及最终分发义务。当前调查不作法律意见；生产合入前应完成一次明确的许可证审查。

## 7. 建议的下一阶段工作（本次不执行）

1. **先做纯参考主题 mockup**：不接入真实 launcher 状态，先制作 `360×240 @2×` 主方案，再制作一张 `240×160 @3×` 强复古对照页，比较菜单列表、顶部 tab、分页点、footer、游戏卡片和信息密度。
2. **建立字体候选矩阵**：对 Latin、数字、日文假名、简体中文分别列出覆盖范围、像素高度、内存大小和许可证；不要直接把 `jf_dot_k14.c` 当作日文解决方案。
3. **做资源格式实验**：把 2×2 点、1 px 边框、1-bit icon、alpha mask 和 indexed pixel-art 分别转换为 PocketJS 可接受的资源，比较包体和 raster 成本。
4. **做三档信息密度**：短英文标题、长英文标题、中文/日文混排各做一张页面，分别确认 360×240 主网格和 240×160 备选网格的溢出行为。
5. **做双输出回归**：桌面窗口看布局，QEMU/捕获 framebuffer 看 720×480 直出、2×/3× nearest-neighbor 和缓存路径；1.5×只作为旧 fractional 路径兼容回归。
6. **最后才接入 launcher**：先以主题开关或独立页面接入，再验证收藏、类别切换、游戏启动、封面背景和输入路径，避免一次性替换现有现代 UI。

## 8. 调查边界和未验证事项

本次完成了仓库克隆、源码/资源盘点、尺寸和实现方式检查、参考文件归档与适配建议；没有修改 PocketShell checkout，没有构建 ChroMagic 固件，也没有把任何资源接入 PJOS-LINUX 的生产构建。

尚未完成的事项包括：ChroMagic 原始字体文件的授权验证、资源在 PocketJS 中的实际转换、360×240 @2×与240×160 @3×视觉 mockup、720×480 硬件显示效果、完整字体裁剪后的包体/atlas/启动性能，以及许可证审查后的可发行资源清单。

## 9. 已落地的字体模式开关（2026-11-14）

PocketShell 现已加入一个持久化的“字体样式”设置，选项为“现代 / 点阵”，默认值仍为“现代”。设置同时补齐 English、简体中文和日本語文案；用户在设置页切换后，`SETTING\tfontMode\t<modern|pixel>` 会保存到现有 launcher 设置桥，重新启动 launcher 后仍保留选择。

实现采用单独的 UI `Text` 包装层：现代模式继续使用当前 Sarasa 字体；点阵模式把所有 launcher 文本切换到 Fusion Pixel 中文完整版的专用字体槽。该字体覆盖英文、数字、简体中文及日文假名，并保留现有 fallback 和图标字体。

### 9.1 RG34XX 720×480 的实际取舍

当前 RG34XX 可见面板为 720×480，launcher package 也是 720×480 逻辑输出。最初尝试为普通文字和标题分别加入 12px、24px 两个完整 CJK atlas，但 QEMU 启动验收出现 `InternalError: out of memory`。因此当前可部署方案只增加一个完整 12px Fusion Pixel atlas（约 1.5MB），并让点阵模式所有文字共用该 atlas；原有 `text-*` 类仍控制布局的 line box 和间距，避免为了第二个完整 atlas 增加约 5.7MB 内存压力。

当前点阵 atlas 已调整为 Fusion Pixel 12px 原字模的 1.5×输出，即 18px。24px 完整 CJK atlas 在 QEMU 中触发运行时 OOM，因此当前先选用 18px 作为 RG34XX 的内存安全上限；后续如果实机内存和启动时间允许，应改为按页面/文案裁剪的 24/36px atlas，或把标题点阵字做成单独的少量 glyph 资源，而不是直接为完整中文字符集无条件增加多套大字号 atlas。

### 9.2 本次验证

- PocketShell TypeScript 构建通过。
- PocketShell 测试 13 项全部通过。
- QEMU 使用新 package 启动 3 帧成功，输出 `completed 3 logical ticks; 720x480; rocknix-h700-kms`。
- 本次尚未完成 RG34XX 实机安装：当前 `adb devices -l` 为空，且环境中没有 `PJOS_DEVICE_IP` / `PJOS_DEV_PW`，因此没有在未确认设备身份的情况下执行 SSH 部署。

