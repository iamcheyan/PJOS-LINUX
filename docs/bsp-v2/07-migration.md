# 07 — 迁移路线图

> 把当前仓库重构成 `02`–`06` 描述的形态，切成 **9 个可独立合并的步骤**。
>
> 每一步的硬约束：
> 1. **可单独开 PR 合并**，不依赖后续步骤；
> 2. **H700 行为零变化**，且有可执行的证明方式；
> 3. **有回滚方式**，且回滚不需要重新构建已验证的产物；
> 4. 合并后主干随时可发布。
>
> 每一步都给出：影响范围 / 验证方式 / 回滚方式 / "零变化"如何证明。

---

## 0. 为什么是 9 步，以及顺序的约束

顺序不是任意的。三条依赖关系决定了拓扑：

```
M1 (度量基线)
 ├─→ M2 (BSP 目录，纯搬运)
 │     └─→ M3 (profile v2 + 校验器)
 │           └─→ M4 (overlay 合成)
 │                 └─→ M5 (BSP 边界收紧: src/ + harvest)
 │                       └─→ M6 (DAL)
 │                             └─→ M7 (baseosctl)
 │                                   └─→ M8 (应用去设备化)
 └─→ M9 (fake board + CI 矩阵)  ← 可在 M2 后任何时刻并行
```

**M1 必须最先**：没有"内容级"基线，后面每一步都无法证明"零变化"。
这是本设计最容易做错的地方——直觉上会先建目录，但那样就无法区分
"我搬对了"和"我搬的时候顺手改了"。

**M9 可以在 M2 之后并行**：fake board 只需要 BSP 目录存在，不依赖 DAL。

---

## 1. 前置事实：为什么"镜像 SHA 不变"不能作为判据

本次审计实测（可复现）：

```sh
# ext4：同一输入两次 mke2fs，即使固定 -U 与 -E hash_seed，仍有 1 字节差异
$ docker run --rm -v /tmp/x:/w alpine:3.20 sh -c '
    apk add -q e2fsprogs e2fsprogs-extra
    cd /w
    for n in a b; do
      mke2fs -q -F -t ext4 -b 4096 -L rootfs -U 1111... \
        -E hash_seed=1111...,root_owner=0:0 -d r $n.img 8M
    done
    cmp -l a.img b.img'
# → 1 字节差异 @0x22b08（inode 区）

# vfat：每次随机 volume id
$ mkfs.vfat -F 32 -n BASEOS -S 512 a.img   # 两次
# → 4 字节差异 @0x43（BPB volume id）
```

因此本路线图的每一步都用**内容级**判据：

| 判据 | 实测是否稳定 | 用途 |
|---|---|---|
| rootfs 逐文件 manifest（path+mode+uid+gid+sha256，排序后 sha256） | **稳定** | 证明"overlay 合成结果一致" |
| `mksquashfs -mkfs-time 0` 产物 | **字节稳定** | 证明 `/usr/lib` 镜像一致 |
| 单个文件 `cmp` | 稳定 | 证明"原样搬运" |
| `tar` 字节 | **不稳定**（mtime） | **不用** |
| 整盘镜像 SHA | **不稳定** | **不用** |
| `baseosctl` 输出 | 稳定（纯数据） | 证明 DAL 语义一致 |

M1 的产出就是把这些判据固化成工具。

---

## M1 — 建立内容级基线

**目标**：在任何重构之前，能回答"这次改动有没有改变 rootfs 的内容"。

### 影响范围

新增（不改任何现有文件）：

```
tools/content_manifest.py     # 生成/比较 rootfs 逐文件 manifest
tools/overlay_manifest.py     # 生成/比较 overlay 合成结果
docs/bsp-v2/baseline.md       # 记录基线 manifest 的 sha256（生成物，可重生成）
```

### 实现要点

`tools/content_manifest.py`：

```sh
# 输入：一个目录（rootfs 树）或 rootfs.tar
# 输出（stdout，排序）：
#   <mode> <uid> <gid> <type> <path>[ -> <target>] [<sha256>]
# 然后整份输出取 sha256 作为 manifest 摘要
```

规则：
- 排序用 `LC_ALL=C sort`（`tools/tools-stamp.sh:26` 已有此模式）；
- 不含 mtime/atime/ctime；
- 符号链接记录 target，不跟随；
- 设备节点记录 `type=c` + major/minor（`build-rootfs.sh:298-301` 创建 console/null）。

### 验证方式

```sh
# 1. 工具自洽：同一棵树两次生成，摘要相同
python3 tools/content_manifest.py work/rg40xxv/rootfs-tree > /tmp/a
python3 tools/content_manifest.py work/rg40xxv/rootfs-tree > /tmp/b
cmp /tmp/a /tmp/b

# 2. 能发现真实差异：改一个文件
echo x >> work/rg40xxv/rootfs-tree/etc/hostname
! cmp -s /tmp/a <(python3 tools/content_manifest.py work/rg40xxv/rootfs-tree)
git checkout work/rg40xxv/rootfs-tree/etc/hostname 2>/dev/null || true
```

### 回滚

删除三个新文件即可。零风险（不进入镜像、不改构建）。

### 零变化如何证明

本步不改任何现有代码。证明方式：

```sh
git diff --stat main...HEAD -- overlay/ tools/ src/ manifest/ '*.sh'
# 只允许新增 tools/content_manifest.py tools/overlay_manifest.py docs/bsp-v2/
```

### 基线采集

```sh
./fetch-prepared.sh rg40xxv
./build-rootfs.sh rg40xxv
python3 tools/content_manifest.py work/rg40xxv/rootfs.tar > /tmp/baseline-rg40xxv.txt
sha256sum /tmp/baseline-rg40xxv.txt
# 把摘要写进 docs/bsp-v2/baseline.md
```

对 `rg34xx`（另一块代表板）重复一次。两块板足够：一块 `rotation=0`、一块
有 `filename_alias`（`rgsp`）；或按 §1 的判据，任一板都能证明合成逻辑。

**注意**：`build-rootfs.sh` 需要 docker + `work/tools`。若本机不具备，
M1 的基线可以只采集 `overlay/` 的 manifest（不依赖构建），
并在 M4 时补采完整 rootfs。这是**有意的降级**，写进 `baseline.md`。

---

## M2 — 建立 `bsp/` 目录（纯搬运，零逻辑改动）

**目标**：让板级事实有地方住，但不改变任何构建行为。

### 影响范围

新增：

```
bsp/README.md
bsp/schema/board.schema.json
bsp/schema/soc.schema.json
bsp/allwinner/h700/soc.json
bsp/allwinner/h700/harvest.list                 # 从 manifest/harvest.list 复制
bsp/allwinner/h700/kernel/profiles.json         # 从 src/h700-speaker-amp/profiles.json 复制
bsp/allwinner/h700/kernel/modules/              # 从 src/h700-speaker-amp + src/h700-late-usb 复制
bsp/boards/rg34xx/board.json                    # 由 devices.json 的一条生成
... (11 个 board.json)
tools/bsp_validate.py
```

**不修改**：`devices.json`、`manifest/harvest.list`、`src/h700-*`、任何 `build-*.sh`。

### 关键决定：本步是"复制"不是"移动"

`src/h700-*` 与 `manifest/harvest.list` 在本步**保留原位**，
`bsp/` 里是副本。理由：如果本步就移动，`build-audio-module.sh:24-25`
与 `build-rootfs.sh:37-38` 必须同时改，M2 就变成"搬运 + 改构建"，
失去"纯搬运"的可验证性。

代价：本步存在两份副本。**M5 删除旧位置**，中间只有 M3/M4 两个 PR 的窗口。

### 生成 board.json 的规则

从 `devices.json` 的一条机械映射（**不新增任何信息**）：

| v1 字段 | v2 位置 |
|---|---|
| `id` | `id` |
| `model` | `identity.model` |
| `model_string` | `identity.model_string` |
| `stockmod_prefix` | `identity.firmware_prefix` |
| `filename_alias` | `identity.firmware_alias` |
| `baseos_device` | `identity.frontend_family` |
| `bootlogo_width` | `panel.width` + `logo.width` |
| `bootlogo_height` | `panel.height` + `logo.height` |
| `panel_rotation_ccw` | `panel.rotation_ccw` |
| `wifi` | `network.wifi` + `capabilities.wifi`（`true`→`yes`，`false`→`no`） |
| `bluetooth` | `network.bluetooth` + `capabilities.bluetooth` |

**未在 v1 中出现的字段**，本步一律填 `"unknown"`（Capability/Feature）
或从 `soc.json` 继承（其余）。**不得凭空填 `yes`**（`04 §5`、`05 §4.3`）。

具体：`capabilities` 里 `touch`/`vibration` = `unknown`；`hdmi`/`gpu`/`rtc`/
`usb_gadget`/`usb_host`/`brightness`/`audio` 按 `04 §5` 的证据表填。
`features` 全部按 `05 §4.3` 填（5 个 `unknown`）。

### 验证方式

```sh
# 1. 11 条 profile 全部通过 schema
for f in bsp/boards/*/board.json; do python3 tools/bsp_validate.py board "$f"; done

# 2. 与 devices.json 的机械映射一致（逐字段断言）
python3 tools/bsp_validate.py equivalence devices.json bsp/boards/

# 3. 未知字段被拒
echo '{"schema":"pjos.board/1","id":"x","foo":1}' > /tmp/bad.json
! python3 tools/bsp_validate.py board /tmp/bad.json

# 4. 缺 capabilities 键被拒
#    （复制一条 profile，删掉 touch，断言失败）

# 5. harvest 副本与原文逐字节相同
cmp manifest/harvest.list bsp/allwinner/h700/harvest.list

# 6. 内核补丁副本与原文逐字节相同
diff -r src/h700-speaker-amp bsp/allwinner/h700/kernel/modules/speaker-amp
diff -r src/h700-late-usb   bsp/allwinner/h700/kernel/modules/late-usb
```

### 回滚

删除 `bsp/` 与 `tools/bsp_validate.py`。**无构建影响**——本步不改任何
被构建读取的文件。

### 零变化如何证明

```sh
# 本步不改任何构建输入，因此 rootfs 内容必然不变：
git diff --name-only main...HEAD | grep -vE '^(bsp/|tools/bsp_validate\.py|docs/)' | wc -l   # 0
```

这是**最强形式的证明**：不改输入 ⇒ 输出不变，无需重跑构建。

---

## M3 — `device_profile.py` 读 v2，`devices.json` 保留为生成物

**目标**：构建系统改读 `bsp/`，但对外接口（`PROFILE_*` 变量）不变。

### 影响范围

修改：`tools/device_profile.py`（约 40 行）

```
- DEFAULT_PROFILES = ROOT / "devices.json"
+ BSP_BOARDS = ROOT / "bsp" / "boards"
+ BSP_SOC = ROOT / "bsp"

- load_profiles(): 读 devices.json 的 targets
+ load_profiles(): 遍历 bsp/boards/*/board.json，与对应 soc.json 深合并

- REQUIRED_FIELDS = {...10 个 v1 字段...}
+ REQUIRED_FIELDS 从 bsp/schema/board.schema.json 派生
```

**`shell` 子命令的输出变量名与值必须完全不变**：

```
PROFILE_TARGET=rg34xx
PROFILE_MODEL=RG34XX
PROFILE_STOCKMOD_PREFIX=RG34XX-
PROFILE_BASEOS_DEVICE=rg34xx
PROFILE_MODEL_STRING=RG34xx
PROFILE_BOOTLOGO_WIDTH=720
PROFILE_BOOTLOGO_HEIGHT=480
PROFILE_PANEL_ROTATION_CCW=0
PROFILE_WIFI=1
PROFILE_BLUETOOTH=1
```

（这是 `main@dc99d57` 的实际输出，已实测。）

### 关键决定：本步不改任何 `build-*.sh`

12 个脚本都通过 `eval "$(python3 tools/device_profile.py shell "$TARGET")"`
取变量（`build-rootfs.sh:17`、`build-image.sh:32`、`verify-target.sh:29`、
`tools/make-bootlogo.sh:17`、`validate-on-device.sh:12`、`test-boot-qemu.sh:21`、
`flash-card.sh:8`、`build-all.sh:30`、`build-stockmod.sh:23,26,30`、
`cache-pack.sh:40`、`fetch-prepared.sh:40`、`prepare-stock.sh:13`）。
接口不变 ⇒ 零改动。

### 验证方式

```sh
# 1. 每个 target 的 shell 输出与 main 逐字节相同
git stash -q 2>/dev/null || true
for t in $(python3 tools/device_profile.py list); do
  python3 tools/device_profile.py shell "$t" > /tmp/new-$t
done
git checkout main -- tools/device_profile.py
for t in $(python3 tools/device_profile.py list); do
  python3 tools/device_profile.py shell "$t" > /tmp/old-$t
done
for t in $(python3 tools/device_profile.py list); do cmp /tmp/old-$t /tmp/new-$t; done

# 2. list 输出顺序相同（build-all.sh 依赖它做遍历）
diff <(git show main:devices.json | python3 -c 'import json,sys;print(" ".join(t["id"] for t in json.load(sys.stdin)["targets"]))') \
     <(python3 tools/device_profile.py list)

# 3. find 行为不变（固件文件名匹配）
python3 tests/test-prepared-cache.py
./test-prepare-stock.sh

# 4. 未知字段/缺字段仍报错
```

### 回滚

`git revert` 该 commit。`bsp/` 保留（M2 的产物无害）。

### 零变化如何证明

**逐字节相同**的 `PROFILE_*` 输出（上面第 1 条）。因为所有构建脚本
只消费这些变量，变量相同 ⇒ 构建行为相同。

补充：`test-prepare-stock.sh` 与 `test-prepared-cache.py` 覆盖
`find`/`list` 路径。

---

## M4 — overlay 合成（SoC/板级片段）

**目标**：`build-rootfs.sh` 从"拷一份 overlay"变成"合成三层 overlay"，
合成结果与今天逐文件一致。

### 影响范围

修改：

- `build-rootfs.sh:114`（`cp -R /overlay/. "$R/"` → 三次 `cp -R`）
- `build-rootfs.sh:44-57`（docker 挂载：增加 `bsp/<soc>/overlay`、`bsp/boards/<id>/overlay`）
- `tools/device_profile.py shell`（新增 `PROFILE_SOC_OVERLAY`、`PROFILE_BOARD_OVERLAY`）

新增（**空目录**，本步不放内容）：

```
bsp/allwinner/h700/overlay/
bsp/boards/<id>/overlay/      (11 个，空)
```

### 关键决定：本步片段为空

本步只建立**机制**，不搬运内容。所以：

```
合成结果 = overlay/ + (空) + (空) = overlay/
```

这使 M4 成为一个可以"用 manifest 断言完全相等"的步骤。
把 rcS 的 H700 段落搬进片段是 **M5** 的事——那一步才可能改变行为。

### 合成顺序与覆盖语义

```sh
cp -R /overlay/.            "$R/"   # 发行版通用
cp -R /soc-overlay/.        "$R/"   # SoC 片段，覆盖同名
cp -R /board-overlay/.      "$R/"   # 板级片段，最后覆盖
```

`cp -R` 的语义是"逐文件覆盖"，不做目录级替换。这与
`build-rootfs.sh:108-114` 现有注释一致（"Our overlay wins over everything"，
且要先 `rm -f` busybox 的符号链接，`:113`）。

### 验证方式

```sh
# 1. 合成结果与 main 的 overlay 逐文件相同（本步片段为空）
python3 tools/overlay_manifest.py --base overlay/ > /tmp/m4-new.txt
git stash -q; git checkout main -- overlay/ 2>/dev/null
python3 tools/overlay_manifest.py --base overlay/ > /tmp/m4-old.txt
cmp /tmp/m4-old.txt /tmp/m4-new.txt

# 2. rootfs 内容与 M1 基线相同（需要 docker）
./build-rootfs.sh rg40xxv
python3 tools/content_manifest.py work/rg40xxv/rootfs.tar > /tmp/m4-rootfs.txt
cmp /tmp/m4-rootfs.txt /tmp/baseline-rg40xxv.txt

# 3. 覆盖语义有测试：在 SoC 片段里放一个同名文件，断言最终内容来自片段
mkdir -p /tmp/t/soc/etc && echo soc > /tmp/t/soc/etc/hostname
# 用 overlay_manifest.py 的三层模式断言结果

# 4. 空片段不改变 mtime 排序（tar 顺序）——若 manifest 已排序则无关
```

### 回滚

`git revert`。`bsp/*/overlay/` 的空目录留着无害。

### 零变化如何证明

两条独立证据：

1. **静态**：合成结果的文件集合 + 每个文件的 sha256 与 main 相同（上面第 1 条）；
2. **动态**：`build-rootfs.sh` 产出的 rootfs manifest 与 M1 基线相同（第 2 条）。

---

## M5 — BSP 边界收紧（搬走 SoC 内容 + lint）

**目标**：把 `overlay/`、`src/`、`manifest/` 里的 SoC 专有内容搬进 `bsp/`，
并让 lint 从此守住边界。

这是**第一个可能改变行为的步骤**，也是最需要小心的。

### 影响范围

**搬运（内容不变，位置变）**：

| 从 | 到 | 方式 |
|---|---|---|
| `manifest/harvest.list` | `bsp/allwinner/h700/harvest.list` | `git mv` |
| `src/h700-speaker-amp/` | `bsp/allwinner/h700/kernel/modules/speaker-amp/` | `git mv` |
| `src/h700-late-usb/` | `bsp/allwinner/h700/kernel/modules/late-usb/` | `git mv` |
| `src/axp-off.c` | `bsp/allwinner/h700/tools/axp-off.c` | `git mv` |
| `src/baseos-regs.c` | `bsp/allwinner/h700/tools/baseos-regs.c` | `git mv` |
| `src/charger-wait.c` | `bsp/allwinner/h700/tools/charger-wait.c` | `git mv` |
| `overlay/usr/sbin/h700-speaker-amp-load` | `bsp/allwinner/h700/overlay/usr/sbin/speaker-amp-load` | `git mv` + 改名 |
| `rcS:107-115,185-251,377-382` | `bsp/allwinner/h700/overlay/etc/init.d/soc-hw-init` | 抽取为独立脚本 |

**修改**：

- `build-rootfs.sh:37-38`（harvest 路径）
- `build-rootfs.sh:92-94`（模块路径）
- `build-rootfs.sh:149,168`（`h700-speaker-amp-load` → `speaker-amp-load`）
- `build-audio-module.sh:2,14,17,36`（源路径 + 注释里的板名）
- `tools/audio_module.py:24-27`（源路径）
- `tools/tools-stamp.sh:26`（`src/*.c` glob → 加 `bsp/*/tools/*.c`）
- `overlay/etc/init.d/rcS`（调用 `soc-hw-init`，自身变短）
- `tests/test-h700-speaker-amp-load.sh`（改名/改路径，**断言内容不变**）
- `cache-pack.sh:60`、`fetch-prepared.sh:83,147`、`verify-target.sh`、
  `build-rootfs.sh:38`（harvest 清单路径）

**新增**：

```
tools/bsp-lint.sh
```

### 关键决定：`rcS` 的抽取必须"逐行等价"

抽取不是重写。做法：

1. 把 `rcS:107-115`（GPU + late USB）原样移入 `soc-hw-init` 的 `hw_gpu()` / `hw_late_usb()`；
2. 把 `rcS:185-251`（WiFi 块）原样移入 `hw_wifi()`，保留 `( ... ) &` 的后台化；
3. 把 `rcS:377-382`（speaker amp）移入 `hw_speaker_amp()`；
4. `rcS` 在原位置改为 `. /etc/init.d/soc-hw-init` + 三次调用。

**验收是"抽取前后 rcS 的实际执行序列相同"**，而不是"代码看起来一样"。
证明方式见下。

### 验证方式

```sh
# 1. 搬运是逐字节的
git show main:manifest/harvest.list | cmp - bsp/allwinner/h700/harvest.list
git show main:src/h700-speaker-amp/h700_speaker_amp.c | \
  cmp - bsp/allwinner/h700/kernel/modules/speaker-amp/h700_speaker_amp.c
git show main:src/axp-off.c | cmp - bsp/allwinner/h700/tools/axp-off.c

# 2. 内核模块产物相同（这是关键：编译参数没变，只是路径变了）
./build-audio-module.sh rg40xxv
sha256sum work/rg40xxv/audio-module/module/*.ko
# 与 main 上同一 target 的产物 sha256 对比（需先在 main 上构建一次留档）

# 3. rcS 的执行序列等价
./tests/test-wifi-init.sh        # 直接抽取并执行 rcS 的 WiFi 块
./tests/test-input-dir-time.sh
./tests/test-root-mount.sh
./tests/test-usr-lib-image.sh
./tests/test-boot-migration.sh

# 4. 全部 host-only 测试
./tests/test-frontend-session.sh
./tests/test-poweroff-policy.sh
./tests/test-axp-off.sh
./tests/test-power-intent.sh
./tests/test-boot-splash-policy.sh
./tests/test-rtc-utc-policy.sh
./tests/test-timedatectl.sh
./tests/test-systemctl-wifi.sh
./tests/test-usb-storage-mode.sh
./tests/test-usb-gadget-adb.sh
./tests/test-gpt-slot.sh
./tests/test-update-apply.sh
./tests/test-baseos-config.sh
./tests/test-baseos-mdns.sh
./tests/test-boot-menu-held.sh
python3 tests/test-audio-gating.py
python3 tests/test-audio-module.py
python3 tests/test-verify-harvest.py
python3 tests/test-prepared-cache.py
python3 tests/test-strip-gpu-module.py

# 5. rootfs 内容与基线相同
./build-rootfs.sh rg40xxv
python3 tools/content_manifest.py work/rg40xxv/rootfs.tar | cmp - /tmp/baseline-rg40xxv.txt

# 6. lint 通过
./tools/bsp-lint.sh

# 7. QEMU 用户空间冒烟
./test-boot-qemu.sh rg40xxv

# 8. 真机（发布前必做，不是合并门禁）
./validate-on-device.sh rg40xxv DEVICE_IP PASSWORD
```

### 回滚

`git revert` 整个 M5 commit。因为 M2/M3/M4 已经让 `bsp/` 与合成机制存在，
revert M5 只是把内容搬回去，机制仍在，主干仍可用。

**不做**部分回滚：M5 是一个原子步骤（搬 + 改路径 + lint），
拆开会让中间态既不在旧位置也不在新位置。

### 零变化如何证明

三条**互相独立**的证据：

1. **产物哈希**：内核模块 `.ko` 的 sha256 与 main 相同（编译参数未变，只是源路径变）；
2. **rootfs manifest**：与 M1 基线逐文件相同；
3. **行为测试**：`test-wifi-init.sh` 直接执行抽取后的 WiFi 块，
   断言与抽取前相同的时序行为（该测试通过 `rcs.index('# Radio initialization')`
   定位代码块，`tests/wifi-init.py:19-24`——**M5 必须同时更新这个定位**，
   或让 `soc-hw-init` 保持同样的注释锚点）。

**第 3 条的注意点**：`tests/wifi-init.py:19-24` 用字符串锚点从 `rcS` 里
切出 WiFi 块。抽取后锚点消失，测试会失败。**这不是"测试需要放宽"，
而是"测试的定位需要跟着代码搬家"**——把锚点改到 `soc-hw-init`，
断言内容一字不改。

---

## M6 — DAL 落地（7 子系统，先只读）

**目标**：`/usr/lib/baseos/dal.sh` 提供 7 个子系统的查询，
`rcS`/`baseos-charger`/`baseos-diag` 改为调它。

### 影响范围

新增：

```
overlay/usr/lib/baseos/dal.sh
overlay/usr/lib/baseos/dal/{display,audio,input,power,network,storage,led}.sh
```

修改（逐个子系统，**每个子系统一个 commit**，便于独立回滚）：

| commit | 修改文件 |
|---|---|
| M6a display | `overlay/usr/sbin/baseos-charger:44-54`、`overlay/usr/sbin/baseos-diag:532` |
| M6b power | `overlay/etc/init.d/rcS:11-12,80-89`、`overlay/usr/sbin/baseos-charger:11,19,64`、`overlay/usr/sbin/baseos-diag:455,478`、`src/native-health.c:26` |
| M6c storage | `overlay/etc/init.d/rcS:41,120,292-322,353-357`、`expand-storage:14-15`、`baseos-update:30-31`、`usb-storage-mode:12-13`、`baseos-startup-sound:8,13`、`frontend-session:106` |
| M6d input | `overlay/usr/sbin/boot-menu-held:6-8`、`src/charger-wait.c:49-50` |
| M6e audio | `overlay/usr/sbin/baseos-startup-sound:26-31`、`rcS:377-382` |
| M6f network | `overlay/etc/init.d/rcS:185-251`、`overlay/usr/sbin/baseos-mdns:28`、`overlay/mnt/vendor/ctrl/setBluetooth.sh:11-12` |
| M6g led | `overlay/usr/sbin/baseos-charger:64-65` |

### 关键决定：M6 只做只读 + 已存在的写路径

`dal_display_brightness_set`、`dal_power_off`、`dal_storage_expand` 这些
**写**操作，本步只做"把现有实现包一层"，不改变行为。新增的写能力
（`dal_power_rtc_alarm_set`、`dal_audio_volume_set` 的归一化）留到 M7 之后。

理由：M6 的目标是"消除节点字面量"，不是"增加能力"。两者混在一起，
无法区分回归来源。

### 验证方式

每个子系统 commit 都跑：

```sh
# 1. 该子系统的 fake-tree 测试
sh bsp/allwinner/h700/tests/dal-<sub>.sh

# 2. 该子系统的行为测试（现有）
#    display: tests/test-boot-splash-policy.sh
#    power:   tests/test-poweroff-policy.sh tests/test-axp-off.sh tests/test-power-intent.sh
#    storage: tests/test-gpt-slot.sh tests/test-update-apply.sh tests/test-usb-storage-mode.sh
#    input:   tests/test-boot-menu-held.sh tests/test-input-dir-time.sh
#    audio:   tests/test-h700-speaker-amp-load.sh tests/test-startup-sound.sh
#    network: tests/test-wifi-init.sh tests/test-systemctl-wifi.sh tests/test-baseos-mdns.sh
#    led:     （无现有测试，新增 fake-tree 测试）

# 3. 节点字面量减少的量化断言
before=$(git show main:overlay/usr/sbin/baseos-charger | grep -cE '/(sys|proc|dev)/')
after=$(grep -cE '/(sys|proc|dev)/' overlay/usr/sbin/baseos-charger)
[ "$after" -lt "$before" ]

# 4. rootfs manifest 与基线差异仅限预期的文件
python3 tools/content_manifest.py work/rg40xxv/rootfs.tar | diff /tmp/baseline-rg40xxv.txt - | \
  grep '^[<>]' | grep -vE 'usr/lib/baseos/dal|usr/sbin/(baseos-charger|baseos-diag|baseos-update|expand-storage|usb-storage-mode|boot-menu-held|baseos-startup-sound|frontend-session|baseos-mdns)|etc/init.d/rcS|usr/lib/modules'
```

第 4 条是关键：**允许 rootfs 变化，但必须能逐条解释**。

### 回滚

逐 commit `git revert`。7 个子系统独立，可只回滚出问题的那个。

### 零变化如何证明

| 层 | 判据 |
|---|---|
| 语义 | `baseosctl` 尚不存在，用 fake-tree 测试断言 DAL 输出与旧代码行为一致 |
| 行为 | 每个子系统的现有测试全绿 |
| 内容 | rootfs manifest 的差异被逐条解释（第 4 条） |
| 真机 | `validate-on-device.sh` 全 PASS |

**诚实说明**：M6 之后 rootfs **内容会变**（多了 `dal/`，少了字面量）。
所以"零变化"在这里的正确含义是**"行为零变化"**，不是"内容零变化"。
这一点必须在 PR 描述里写清，否则评审会误以为可以要求 manifest 相同。

---

## M7 — `baseosctl`（只读 → 写）

**目标**：提供 `06` 定义的全部子命令。

### 影响范围

新增：

```
overlay/usr/sbin/baseosctl
```

修改：

- `build-rootfs.sh:140-174`（加进 chmod 与可执行性守卫列表）
- `overlay/usr/sbin/systemctl`（三个职责改为调 `baseosctl`）

### 分两步

| 步骤 | 范围 | 验证 |
|---|---|---|
| M7a | `cap` `feature` `version` `display info` `audio info` `power battery` `network info` `input list` `storage info` `led list` | 全部只读，fake-tree 可测 |
| M7b | 全部写操作（`set-brightness`、`set-volume`、`suspend`、`poweroff`、`wifi-up`…） | 真机验证；幂等测试 |

M7a 可以独立合并并发布：应用立刻可以"问而不是猜"。

### 验证方式

```sh
# 1. 全部子命令在 fake 树上可跑
for g in cap feature display audio power network input storage led version; do
  BASEOS_SYS_ROOT=/tmp/fake baseosctl $g --help >/dev/null
done

# 2. 三态退出码
BASEOS_SYS_ROOT=/tmp/fake baseosctl cap has wifi; [ $? = 0 ]
# (在声明 no 的 fake profile 上断言 1；unknown 上断言 2)

# 3. JSON 可解析
for c in "cap list" "feature list" "display info" "power battery" "network info" "storage info" "version"; do
  BASEOS_SYS_ROOT=/tmp/fake baseosctl --json $c | python3 -m json.tool >/dev/null
done

# 4. 无人类散文
BASEOS_SYS_ROOT=/tmp/fake baseosctl display info | grep -qE ' (is|are|the|has|will) ' && exit 1 || true

# 5. systemctl shim 行为不变
./tests/test-systemctl-wifi.sh

# 6. 真机
./validate-on-device.sh rg40xxv DEVICE_IP PASSWORD
```

### 回滚

删除 `overlay/usr/sbin/baseosctl`，`systemctl` shim 回退到直接调
`pidof`/`killall`。因为 M6 的 DAL 仍在，回滚不影响其它部分。

### 零变化如何证明

M7a（只读）**不改变任何系统行为**：它只增加一个新命令。
证明：`git diff` 里没有任何现有文件的语义改动（除 `build-rootfs.sh` 的 chmod 列表）。

M7b（写）改变了 `systemctl` shim 的实现路径。证明：
`tests/test-systemctl-wifi.sh` 全绿 + 真机 `validate-on-device.sh`。

---

## M8 — 应用去设备化（跨仓库，本阶段只定义契约）

**目标**：PocketJS 不再探测硬件，只调 `baseosctl`。

### 影响范围

**本仓库**：无代码改动。只新增：

```
docs/bsp-v2/pocketjs-contract.md     # 给 PocketJS 仓库的契约
```

**PocketJS 仓库**（另一个 PR，不在本 worktree）：

- `dist/sdcard-payload/System/launch_frontend.sh`：删掉 DRM→fbdev 猜测
  （`docs/13-pocketjs-on-baseos.md:19` 的 failure streak 来源），改调
  `baseosctl display node` + `baseosctl input node keyboard`；
- `dist/compat/*`：6 个 shim 改为调 `baseosctl`，**不保留回落**；
- 设置页按 `cap`/`feature` 三态显示（`04 §6.3`、`05 §5.2`）。

### 验证方式

```sh
# 本仓库：契约文档存在且与 06 一致
grep -q 'baseosctl display node' docs/bsp-v2/pocketjs-contract.md
grep -q 'baseosctl cap list' docs/bsp-v2/pocketjs-contract.md

# PocketJS 仓库（独立 PR）：
#   1. 设备上 launch_frontend.sh 的日志里不再出现 "DRM card not found"
#   2. 把 board.json 的 display.backend 从 fbdev 改成 drm（假想设备），
#      应用代码零改动仍能启动（06 的 S 系列断言）
```

### 回滚

PocketJS 侧的 PR 独立 revert。本仓库的契约文档无需回滚。

### 零变化如何证明

本仓库不改代码 ⇒ 无行为变化。PocketJS 侧的证明是"日志里不再有探测失败"。

---

## M9 — fake board + 多设备 CI 矩阵（可与 M2 之后并行）

**目标**：在 x86 CI 上验证 BSP/DAL/profile 逻辑，不需要真机。

### 影响范围

新增：

```
tests/fake-board/
  make-fake-board.sh          # 生成一棵假 /sys + /proc + /dev 树
  boards/fake-fbdev/board.json
  boards/fake-drm/board.json
  boards/fake-minimal/board.json
  expected/<board>.txt        # 每个 fake board 的 baseosctl 期望输出
tests/test-fake-board.sh
```

修改：

- `CONTRIBUTING.md:207-250`（加一条 CI 命令）

### 三个 fake board 的设计

| board | 用来测什么 |
|---|---|
| `fake-fbdev` | 完整 H700 形状（fb0、disp、axp2202、event0-2），`cap` 全 `yes` |
| `fake-drm` | 同形状但 DRM 后端 + 标准 backlight + `/sys/class/leds`，验证"换后端不改代码" |
| `fake-minimal` | 只有 fb0 + 一个 input，`cap` 大部分 `no`/`unknown`，验证降级路径 |

`make-fake-board.sh` 沿用仓库已有的模式（`overlay/usr/sbin/usb-gadget-adb:36-54`
的 `BASEOS_SYS_ROOT` + `TEST_MODE`，以及 `tests/test-boot-menu-held.sh:7-11`
的 `BASEOS_GPIO_DEBUG`）。**不发明新机制。**

### 验证方式

```sh
# 1. fake board 生成
sh tests/fake-board/make-fake-board.sh fake-fbdev /tmp/fake
[ -r /tmp/fake/sys/class/power_supply/axp2202-battery/capacity ]

# 2. 每个 fake board 的输出与期望一致
BASEOS_SYS_ROOT=/tmp/fake baseosctl cap list | diff - tests/fake-board/expected/fake-fbdev.txt

# 3. 降级路径
BASEOS_SYS_ROOT=/tmp/fake-min baseosctl cap has wifi; [ $? = 1 ]   # 声明 no
BASEOS_SYS_ROOT=/tmp/fake-min baseosctl cap has touch; [ $? = 2 ]  # unknown

# 4. 一致性：所有 board.json 通过 schema
for f in bsp/boards/*/board.json tests/fake-board/boards/*/board.json; do
  python3 tools/bsp_validate.py board "$f"
done

# 5. 依赖一致性：cap.no ⇒ feature.no
python3 tools/bsp_validate.py deps bsp/boards/ tests/fake-board/boards/
```

### 回滚

删除 `tests/fake-board/` 与 `tests/test-fake-board.sh`。零影响。

### 零变化如何证明

纯新增，不进入镜像。证明：`git diff --name-only` 全在 `tests/` 与 `CONTRIBUTING.md`。

---

## 2. 汇总表

| 步 | 名称 | 改代码 | 改镜像 | 可独立发布 | 依赖 |
|---|---|---|---|---|---|
| M1 | 内容级基线 | 新增工具 | 否 | 是 | — |
| M2 | `bsp/` 目录（纯复制） | 新增 | 否 | 是 | M1 |
| M3 | `device_profile.py` 读 v2 | 改 1 文件 | 否（输出相同） | 是 | M2 |
| M4 | overlay 合成机制 | 改 1 脚本 + 1 工具 | 否（片段空） | 是 | M3 |
| M5 | BSP 边界收紧 | 移动 + 改路径 | **是** | 是 | M4 |
| M6 | DAL（7 子系统，7 commit） | 新增 + 改 15 文件 | **是** | 是 | M5 |
| M7 | `baseosctl`（a/b 两步） | 新增 + 改 2 文件 | **是** | 是 | M6 |
| M8 | 应用去设备化 | 本仓库仅文档 | 否 | 是 | M7 |
| M9 | fake board + CI | 新增 | 否 | 是 | M2 |

**9 步全部可单独合并、单独发布。** 每步合并后主干都能出镜像。

---

## 3. H700 行为零变化的统一证明模板

每个 PR 描述里填这张表：

| 证据 | 命令 | 本步是否适用 |
|---|---|---|
| E1 不改构建输入 | `git diff --name-only main...HEAD \| grep -vE '^(bsp/\|docs/\|tests/)'` 为空 | M1 M2 M9 |
| E2 `PROFILE_*` 输出逐字节相同 | 见 M3 验证第 1 条 | M3 及之后每步 |
| E3 overlay 合成 manifest 相同 | `tools/overlay_manifest.py` | M4 |
| E4 rootfs manifest 相同 | `tools/content_manifest.py` vs 基线 | M4 M5 |
| E5 rootfs manifest 差异可逐条解释 | 同上 + 解释清单 | M6 M7 |
| E6 内核模块产物 sha256 相同 | `sha256sum work/*/audio-module/module/*.ko` | M5 |
| E7 host-only 测试全绿 | CONTRIBUTING.md:211-247 的清单 | 每步 |
| E8 QEMU 用户空间冒烟 | `./test-boot-qemu.sh rg40xxv` | M5 M6 M7 |
| E9 真机验收 | `./validate-on-device.sh rg40xxv IP PW` | M5 M6 M7（发布前） |
| E10 lint 通过 | `tools/bsp-lint.sh` | M5 及之后 |

**E9 不是合并门禁**（需要真机），但**是发布门禁**。

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| M5 抽取 rcS 时改变执行顺序 | 高（WiFi 时序敏感，`rcS:170-184` 的注释解释了为何顺序重要） | `tests/test-wifi-init.sh` 直接执行抽取后的块；真机对比 boot log |
| M6 逐子系统改动让 rootfs 差异难以审查 | 中 | 每个子系统一个 commit + 差异解释清单 |
| `build-audio-module.sh` 的 docker 挂载路径变化导致缓存失效 | 低 | 只改挂载源路径，编译参数不动；用 `.ko` sha256 断言等价 |
| M7 的 `baseosctl` sh 实现太慢 | 中 | `06 §10`：预渲染变量文件 |
| M8 跨仓库，节奏不受本仓库控制 | 中 | 契约文档先行；应用侧保留旧探测直到 M7 真机验证通过 |
| M9 fake board 与真实 board 漂移 | 中 | `tools/bsp_validate.py` 对 fake 与 real 用同一 schema |
| 真机只有 2 台（`rg34xxsp`、`rg40xxv`，见 `experiments/h700-boot-speed/native/verify-fleet.py:19`） | 高 | 承认：其余 9 台只能靠 fake board + 构建期门禁；写进 `06 §11` 的"验证状态三态" |

**最后一条是必须诚实面对的**：`experiments/h700-boot-speed/native/verify-fleet.py:19` 写 `LIVE_TARGETS = {"rg34xxsp", "rg40xxv"}`。
11 台设备里只有 2 台有真机验证。任何"零变化"的声明，对另外 9 台
只能是"构建期等价 + 内容级等价"，不是"实测等价"。这一点必须在
发布说明里区分。

---

## 5. 时间线建议（不含估算，只给顺序约束）

```
发布 1.6.0 ← M1 M2 M3 M4 可以全部进这个版本（都不改镜像内容）
发布 1.7.0 ← M5（第一个改镜像内容的步骤，需真机）
发布 1.8.0 ← M6a M6b M6c（display/power/storage 是影响面最大的三块）
发布 1.9.0 ← M6d M6e M6f M6g + M7a
发布 1.10.0 ← M7b
            M8 随 PocketJS 仓库节奏
            M9 可在 1.6.0 之后任何时刻插入
```

**每一版都可以回滚到上一版**，因为 `baseos-update` 的 A/B 机制
（`overlay/usr/sbin/baseos-update`）与 `gptslot` 不依赖 BSP 结构。

---

## 6. 本阶段（第一阶段）不做什么

明确列出，避免范围膨胀：

| 不做 | 为什么 |
|---|---|
| 不写任何实现代码 | 任务约束 |
| 不创建 `bsp/` 目录 | M2 的事 |
| 不改 `build-*.sh` | M3/M4 的事 |
| 不写 `baseosctl` | M7 的事 |
| 不写 DAL 库 | M6 的事 |
| 不改 PocketJS | M8 的事，且跨仓库 |
| 不做 A133 的实际支持 | M5 之后才验证架构；`docs/14` 已承认前置条件缺失（"Smart Pro 需要确认是否有官方 StockMod 固件"） |

本阶段只产出 `docs/bsp-v2/` 下的 9 个文件（8 份文档 + 索引）。
