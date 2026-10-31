# 系统身份、版本号与 runtime 重编

这份文档记录本轮实际做的事：把系统展示名统一成 **PJOS Linux**、让界面上的版本号变成
真实值、以及 runtime（`pocket-linux-kms`）从源码到掌机的完整重编流程。踩过的坑逐条写下
原因，避免下次重复。

---

## 1. 系统身份：只改看得见的那一层

| 位置 | 之前 | 现在 | 谁读它 |
|---|---|---|---|
| `/etc/os-release` `NAME` | `Base OS` | `PJOS Linux` | 系统信息页、任何 `os-release` 消费者 |
| `/etc/os-release` `PRETTY_NAME` | `Base OS <ver> (h700)` | `PJOS Linux <ver> (h700)` | 同上 |
| 卡片 `README.txt` | `Base OS — add a frontend…` | `PJOS Linux — add a frontend…` | 用户直接看 |
| 开机画面 | `PJOS LINUX` | 不变（本来就是） | `fbsplash` |

**故意不改**的：包名、`BASEOS_*` 变量名、`ID=baseos`、目录结构、镜像文件名。这些是
`baseos-update` 比对身份、脚本判断平台用的内部键；改了只会让升级链路和一堆脚本错位，
而用户一个都看不见。

> 位置：`build-rootfs.sh`（os-release 与 baseos-release 的生成）、`assets/card-readme.txt`。
> `os-release` 在只读根里，改完必须重打镜像才生效；`/storage` 上的东西（README、包、helper）
> 可以直接推，不用刷机。

---

## 2. 版本号：从仓库到屏幕上那一行

```
PJOS-LINUX/VERSION ──build-rootfs.sh──> /etc/baseos-release   (BASEOS_VERSION / BUILD / TARGET …)
                                      /etc/os-release         (NAME / VERSION_ID / PRETTY_NAME)
                                              │
                     runtime 的 Rust 桥 system_snapshot() 读这两个文件
                                              │
                                host.__launcher("STATE"…)  → 启动器 SYSTEM 页
```

本轮加进 `baseos-release` 的两项：

```
PJOS_SDK_VERSION=0.15.0     # 启动器包编译所用的 PocketJS SDK（@pocketjs/framework）
POCKETJS_ABI=12             # runtime 导出的绑定代际，包 admission 也按它比
```

SYSTEM 页现在显示：

```
OS PJOS Linux 1.5.3 · KERNEL 4.9.170
DISPLAY 720x960 · PocketJS 0.15.0 (abi 12)
POCKETJS SDK 0.15.0 · ABI 12 · BUILD <git describe>
```

**坑**：桥原来读 os-release 的 `VERSION` 字段，而这张表只有 `VERSION_ID`，于是版本号一直
是空的（屏幕上显示成 `PJOS runtime` 后面什么都没有）。改成先读 `VERSION`、空则回退
`VERSION_ID`。同理，runtime 标签原来写死 `PJOS {}`，改成 `PocketJS {sdk} (abi {abi})`。

---

## 3. 重编 runtime 的完整流程

掌机上跑的是 **musl aarch64 静态** 的 `pocket-linux-kms`（BaseOS 是 buildroot，没有 glibc）。
重编需要三个输入，缺一个都会失败：

```sh
# 1) 源码：与 ROCKNIX 配方固定的同一个提交
git -C ~/development/.pocketjs-star-drift-sdk rev-parse --short HEAD   # e6770376
git -C ~/development/.pocketjs-star-drift-sdk archive --format=tar.gz \
    --prefix=pocketjs-runtime-e6770376…/ -o <tree>/sources/pocketjs-runtime/pocketjs-runtime-e6770376….tar.gz HEAD

# 2) profile：必须与卡片上的 boot.pocket 完全一致，否则 Admission(ProfileHashMismatch)
cd ~/development/.pocketjs-star-drift-sdk
PATH=$HOME/.bun/bin:$PATH bun tools/pocket.ts profile export \
    --config programs/pocketshell/pocket.runtime-config.ts --out ~/.cache/pjs-rt/profile
# 校验：pocket-profile.json 里的 profileHash 必须是 sha256:85385701f8dde49f…

# 3) 桥与工作区脚本：ROCKNIX 配方目录
BR=~/development/rocknix/projects/ROCKNIX/packages/apps/pocketjs-runtime/scripts
```

然后：

```sh
cd ~/development/PJOS-LINUX
PJOS_ROCKNIX_TREE=$HOME/.cache/pjs-rt/tree \
PJOS_PROFILE_RS=$HOME/.cache/pjs-rt/profile/pocket_profile.rs \
PJOS_BRIDGE_SCRIPTS=$BR \
./build-pocketjs-runtime-musl.sh        # 产物 work/pocketjs-runtime/pocket-linux-kms
```

脚本做的事：起 `debian:bookworm` arm64 容器（qemu）→ 装 build-essential/musl-tools/clang →
装 rust 1.98.1 + `aarch64-unknown-linux-musl` → 解包 → `prepare-workspace.py` →
`apply-pocketjs-input.py` → `patch-runtime.py`（加入桥）→ `apply-pocketjs-bridge.py`（BaseOS 适配）
→ `cargo build --release --target aarch64-unknown-linux-musl`（`+crt-static`）。

验证与部署：

```sh
file work/pocketjs-runtime/pocket-linux-kms          # ELF 64-bit … ARM aarch64 … statically linked
adb push … /storage/System/pocketjs/bin/pocket-linux-kms.new
adb shell '/storage/System/pocketjs/bin/pocket-linux-kms.new --package /storage/System/pocketjs/apps/boot.pocket --check'
# admitted 之后：备份旧二进制 → mv 覆盖 → kill $(pidof pocket-linux-kms) → 看 /tmp/pocketjs-frontend.log 的 admission 行
```

回滚：旧二进制留在 `pocket-linux-kms.bak-<时间戳>`，`cp` 回去再 kill 即可。

---

## 4. 这一轮踩的坑（按发生顺序）

1. **`python3 /in/narrow.py` 报 "can't find '__main__' module"**
   为了跳过 `--offline` 把构建脚本复制到 `~/.cache` 后运行，`HERE` 跟着变成那个目录，
   `-v "$HERE/src/pocketjs-narrow-workspace.py:/in/narrow.py"` 挂了个不存在的路径，docker 便
   建了个空目录。教训：**docker 挂载路径全部相对脚本自身位置，绝不要复制脚本到别处跑**。

2. **`package ID specification rocknix-pocketjs-bindings did not match`**
   配方里的 `prepare-workspace.py` 除了裁剪 workspace，还会生成 `programs/rocknix-bindings`
   这个 shim crate（`rocknix-pocketjs-bindings`），runtime 靠它把 rquickjs 的 bindgen 特性
   钉在锁文件的版本上。自己手写裁剪就漏了这一步。现在直接调配方的脚本。

3. **`default-members` 指向非成员** —— 只改 `members` 不改 `default-members` 时 cargo 直接
   拒绝解析。配方脚本两个键一起改，这也是用它的理由之一。

4. **冷 cache 下 `--offline` 必失败** —— 原脚本假设 ROCKNIX 的 `cargo_home` 已经取过 crates。
   本机构建时改成在线（去掉 `--offline`），crates 缓存落在
   `~/.cache/pjs-rt/tree/build.*/toolchain/cargo_home`，第二次构建就快了。

5. **在 `docker run` 的续行块里插注释** —— 用 python 按 `BASEOS_WIFI=` 锚点插入变量定义时，
   插进了 `-e` 续行中间，`sh -n` 直接报 `"}" unexpected`；另外注释里一个英文撇号
   （`launcher's`）把整段单引号脚本提前闭合。教训：**不要把补丁脚本的锚点指向
   `docker run … \` 这种续行块，也不要在单引号脚本里写撇号**。

6. **os-release 只有 `VERSION_ID`** —— 桥读 `VERSION` 得到空串，版本号显示不出来（见第 2 节）。

---

## 5. 与启动器相关的接口

Wi-Fi 与已安装程序的启动接口在 `docs/19-wifi-and-app-launch.md`，界面侧的契约在
`pocketshell` 仓库的 `docs/WIFI-BRIDGE-CONTRACT.md`。要点：

- `WIFI scan / status / connect / disconnect / forget / saved / ip`，PSK 走 stdin 不走 argv
- `APPS list` 返回 `/storage/apps/*.pocket` 里真实存在的 id
- `LAUNCH <id>` 写 `System/pocketjs/active` 标记，由 `launch_frontend.sh` 接管画面启动子包

---

## 6. 还没做完/没验证的

- **系统镜像**：`build-all.sh rg34xx` 仍在 tools/rootfs 阶段，`.bosupd` 还没产出；os-release
  改名要等它刷进机器才看得见。
- **runtime 重编**：已成功。产物 `work/pocketjs-runtime/pocket-linux-kms`，3,126,048 B，
  sha256 `a3be425f648785e0…`，静态 aarch64；已装到掌机并验证 `boot.pocket` 与
  `apps/files.pocket` 都能 admission，`LAUNCH` 路径端到端跑通（见 `pocketshell`
  仓库 `docs/device/app-files-launch.png` 与 `returned-to-launcher.png`）。
- **长按电源键真关机**：只验证到日志 `power: long press -> poweroff`，真实断电需人手确认。
- **亮度滑条**：`DISP_CMD_LCD_SET_BRIGHT (0x102)` 仍是 EPERM（内核独占），只能写图像增强
  `enhance_bright` 作为近似。
- **WPA3 / 企业级 / 隐藏 SSID**：未实现，先按 WPA2-PSK 与开放网络来。
