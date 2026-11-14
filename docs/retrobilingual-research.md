# RetroBilingual 技术调查（阶段 1）

状态：源码调查与设备盘点已完成；ROM 文本提取、真实对话调试、覆盖层实测仍未完成。

## 结论摘要

- PJOS 这台 RG34XX 通过 `pocket-game-play` 启动 RetroArch，再由 `.gba` 后缀选择 mGBA libretro core。游戏和字幕必须在同一个 RetroArch 视频输出链路中合成；当前设备没有桌面窗口系统，PJOS 的实机证据确认可用图形路径是 SDL2 mali-fbdev → OpenGL ES 2 → `/dev/fb0`。[docs/22-retroarch-gba.md](22-retroarch-gba.md)
- TMC 反编译工程定义了消息资源索引：16 位 `textIndex` 的高字节是文本分类、低字节是该分类内序号。运行时 `gMessage.textIndex` 保存请求的资源索引；`gTextRender.curToken.textIndex` 是当前 token 使用的索引。`gMessage.state & 0x7f` 用于判断活动消息。[2][3][4]
- 上游日版链接布局将 `gMessage` 放在 EWRAM `0x02000050`；`gTextRender` 在 `0x02022780`，其内 `curToken` 从偏移 `0x08` 开始。消息结构中 `state` 为偏移 `0x00`，初始 `textIndex` 为偏移 `0x08`。这是对 TMC 上游匹配 ROM 的候选地址，不是对所有日版、汉化版 ROM 的保证。[2][3][5]
- 分页不能只看资源 ID。`RunTextCommand` 在控制码遇到分页/等待时切换 render 状态；`TextDispWait` 等待按键后滚屏，`MsgChangeLine` 重置行状态。运行时需结合活动标志、资源索引及等待/滚屏状态生成页序号；这套状态机尚未在掌机调试器上观测。[3]
- 设备中的日版 ROM SHA-1 为 `6c5404a1effb17f481f352181d0f1c61a2765c5d`，与 TMC README 列出的 JP 目标完全一致。[1] 另有两份不同的汉化 ROM：简体文件 `塞尔达传说_缩小帽.gba`（SHA-1 `ba04cfbe93d12d2ad684c52234472fa12a5b53d7`，头部代码 `BZMJ`）和 `萨尔达传说-缩小帽.gba`（SHA-1 `74d57112edb6867f58178da6f48bacdbded9ec4d`，代码 `BZMP`）。两者均为 16 MiB，文件名和头部代码不足以证明它们保留了日版的文本编号或事件关系；尚未完成文本表提取和代码差异分析。[设备 ADB 盘点]
- 在日版文件的 ROM 偏移 `0x109214` 读取到的字节不是可直接解释的 ROM 指针表。因此不能仅凭反编译源码注释中的地址，将它直接当作文件偏移。需要继续确认匹配版本的链接映射和文本表存储方式，再实现提取器。
- mGBA libretro 在 `retro_run()` 中采样输入、运行模拟核心并送出视频帧；`RETRO_ENVIRONMENT_SET_MEMORY_MAPS` 公布 EWRAM/IWRAM 映射以供前端作弊/调试设施使用，但这不是一个让外部字幕服务稳定订阅游戏状态的运行时 IPC。[6][7]
- 最小可控路线是在 PJOS 构建的 mGBA libretro core 中加入日版哈希门控的轻量状态读取，并在 core 视频回调前合成字幕。核心状态监控默认关闭、只读两个已知 EWRAM 字段；快捷键激活时暂停核心并使用独立输出缓冲，关闭时恢复原始画面。该钩子和帧缓冲目前尚未实现。
- Batocera 的 AI Game Translation 提供“快捷键暂停、重复按键恢复”的交互先例，但它依赖在线服务；只参考暂停/恢复行为，不复用翻译服务。[8]
- 当前 PJOS RetroArch 构建配置显式禁用 FreeType 和通用 overlay，系统字体检索只找到 `/usr/share/baseos/boot.ttf`。因此不能假定内置 OSD 可显示中文。渲染实现须提供有来源/许可说明的 CJK 字形资源，或从用户已有字体生成仅含数据库所需字形的离线位图包。目标设备实际没有经确认的完整中文字体。

## 研究问题与当前答案

| 问题 | 当前证据与判断 | 未完成验证 |
|---|---|---|
| 稳定识别当前对话？ | 对 TMC 目标日版，消息活动标志和当前资源索引在源码中明确；该 ROM SHA-1 与上游 JP 目标一致。[1][2][3] | 通过 GDB/调试器在真实对话中观察 RAM 值；存档读档、事件内联文本及修改版日版。 |
| 是否有文本编号？ | 有 16 位资源索引，分类/编号编码为 `(category << 8) | index`。[2] | 当前两份汉化 ROM 是否保留相同索引。 |
| 能否识别当前对话页？ | 可从文本 render 状态、等待/滚屏转换追踪；源码没有可直接使用的独立、持久页编号字段。[3] | 在实机实际对话对每次翻页记录 `state`、`textIndex`、render status 与 token 指针。 |
| 汉化 ROM 能否批量提取？ | 两份 ROM 均已在设备上确认；TMC 的资源选择和文本 token 解码实现可供参考。[4] | 汉化版编码/表位置、压缩、字形表尚未解析；目前没有真实导出的汉化文本。 |
| 事件引用是否相同？ | 尚无证据。相同 GBA 标题头或 ROM 偏移不证明事件引用关系相同。 | 对 JP 与两个汉化 ROM 解析消息表和调用引用图，再报告共同/新增/拆分项。 |
| 哪个模拟器适配最容易？ | 本机现成运行链是 RetroArch + mGBA core；在 mGBA core 的运行帧里同时读取 GBA RAM、接收 RetroPad 输入并在视频回调前合成，可避免屏幕外进程竞争 `/dev/fb0`。[6] | 修改 core 构建并在设备运行；比较是否值得将钩子放进 RetroArch frontend。 |
| RG34XX 低开销是否可行？ | 目标设备已有 mGBA + GLES2 帧路径；两个 16 位地址的状态读取不是整 RAM 扫描的设计。 | 需在设备测 FPS、CPU 和内存；不能仅凭架构宣称性能已通过。 |

## ROM 与隐私边界

ROM 只在设备上计算身份信息并通过 ADB 拉到控制机 `/tmp` 做短暂分析；没有写入仓库，也不应提交 ROM、完整提取文本或汉化字库。数据包应记录 SHA-256 与游戏版本。ROM 头部信息、哈希和源码分析可以进研究报告；商业 ROM 的文本资源只在用户本机生成和使用。

设备上三份核心目标 ROM SHA-256：

- 日版：`16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38`
- `塞尔达传说_缩小帽.gba`：`f51c6c2f90e18ee91203dd767307271e06901b5bff35c3a567d52f61a39d166d`
- `萨尔达传说-缩小帽.gba`：`b5c24428cda7db023435ec95e62e4203203ef48ece034cf853ecf3b72b4a72b0`

## 适配方案

1. **ROM 检查与提取**：`retrobilingual inspect` 已实现 GBA 头部与 SHA-1/SHA-256 识别。提取器必须按精确 ROM 哈希选择格式定义；不匹配时明确报错，不猜测偏移。
2. **规范化数据**：JSON 导出保留 ROM SHA-256、`source_id`、文本、上下文、页序号、偏移、脚本引用和控制码。SQLite 保存 ROM 版本、文本、候选映射及审核记录。
3. **对齐**：已实现的第一层只建议唯一的 `source_id + context_id + page_index` 完全键匹配，confidence 为候选分，不自动批准；重复键输出歧义。下一层由脚本引用/场景图匹配补充，顺序或偏移只能提供审核线索，不能单独建立映射。
4. **运行时**：以日版 SHA-256 选择地址配置；低频或帧边界只读活动标志、资源索引和页状态。查询只接受审核通过的数据库记录。
5. **字幕与快捷键**：mGBA core 把 L1+Select 作为默认候选组合；由于两键本身是游戏输入，必须在 core 中先识别/拦截 chord，再验证短按不会误发 GBA L/Select。激活时冻结模拟核心、保留帧缓冲；再次触发关闭。CJK 字符由离线字体打包器生成适配渲染的位图字形。
6. **构建**：给 PJOS H700 的 mGBA core 增加局部补丁与构建脚本，保留现有 RetroArch/Gambatte 路径；不要让 BaseOS 加载中文 ROM，也不改动原始游戏 ROM。

当前仓库已实现：ROM 检查、版本门控的 TMC 表提取、规范化 JSON/SQLite、唯一 ID/页候选、人工审核、运行时 pack 构建，以及 mGBA core 内的菜单/暂停/字幕合成（细节见 [retrobilingual-runtime.md](retrobilingual-runtime.md)）。仍未完成：中文译文到 Unicode 的解码（pack 需要外部已审核 UTF-8 译文），以及全部真机验证（按当前要求暂停）。

## 上游来源

[1] TMC 项目 README：目标版本和 JP ROM SHA-1。  
[2] TMC `message.h`：`Message`、`Token`、`TextRender` 布局与 `TEXT_INDEX`。  
[3] TMC `message.c`：消息活动周期、页/滚屏状态与按键等待。  
[4] TMC `text.c`：文本分类/索引查表和 token 解码入口。  
[5] TMC `linker.ld`：JP 目标的 EWRAM 地址布局。  
[6] mGBA 0.10.5 libretro `libretro.c`：`retro_run`、视频回调和 GBA memory map 设置。  
[7] Libretro header：memory-map 接口契约。  
[8] Batocera AI Game Translation：快捷键、暂停/恢复交互；依赖在线 API，本文仅参考 UI 行为。

## License 与来源边界

TMC 根目录在检查的上游 checkout 中没有项目级 `LICENSE` 文件；仓库下的部分工具各自带有许可证文件。RetroBilingual 只依据其源码记录行为与地址，不复制 TMC 代码、翻译文本或提取资源；后续若需要复用任一子工具，先单独核对那个目录的许可证。[10]

mGBA 使用 MPL 2.0。若在 mGBA libretro core 中加入本项目的 hook 并分发修改后的 core，需要随可执行版本提供相应修改源码和 MPL 通知。[9]

## Sources

[1] https://github.com/zeldaret/tmc/blob/master/README.md
[2] https://github.com/zeldaret/tmc/blob/master/include/message.h
[3] https://github.com/zeldaret/tmc/blob/master/src/message.c
[4] https://github.com/zeldaret/tmc/blob/master/src/text.c
[5] https://github.com/zeldaret/tmc/blob/master/linker.ld
[6] https://github.com/mgba-emu/mgba/blob/0.10.5/src/platform/libretro/libretro.c
[7] https://github.com/mgba-emu/mgba/blob/0.10.5/src/platform/libretro/libretro.h
[8] https://wiki.batocera.org/ai_game_translation
[9] https://github.com/mgba-emu/mgba/blob/0.10.5/LICENSE
[10] https://github.com/zeldaret/tmc
