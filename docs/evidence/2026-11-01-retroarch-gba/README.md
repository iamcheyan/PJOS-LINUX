# RG34XX 上用 RetroArch 跑起 GBA 游戏（2026-11-01）

设备：Anbernic RG34XX（H700，内核 4.9.170），系统 **PJOS BaseOS 1.5.3**，glibc 2.35。
截帧都是从 `/dev/fb0`（720×480，32bpp）直接读出后转 PNG，不是重建的示意图。

游戏：**Apotris**，GBA homebrew，GPL-3.0，来源见
[`apps/pocket-gamehub/roms/ROM-SOURCES.md`](../../../pocket-gamehub/apps/pocket-gamehub/roms/ROM-SOURCES.md)，
ROM SHA-256 `e5e7b124407d97cb1268b3bde4239bd2f018e133b1cb7990a635fc01937e78f6`。

| 文件 | 证明了什么 |
|---|---|
| `01-apotris-live-framebuffer.png` | 游戏在跑：Apotris 的棋盘、NEXT 方块、`GO` 字样与底部 `Lines 0` 计数都是游戏自己的画面 |
| `02-apotris-title.png` | 重新启动后游戏标题画面：`APOTRIS`、`Press Any Button`、右下角 `akouzoukos` 署名 |

## 运行时事实

- 显示：设备**没有** `/dev/dri`；`/dev/disp` 能打开，但 `DISP_CMD_VERSION`、`DISP_CMD_LAYER_REQUEST`
  都返回 `EPERM`，所以 RetroArch 自带的 `sunxi` 驱动不可用。
- 可用路径：`ghcr.io/loveretro/h700-toolchain` 里的 **SDL2 mali-fbdev**（GCC 8.3，交叉 sysroot），
  `SDL_CreateWindow` + 加速 `opengles2` 渲染器在 `/dev/fb0` 上成立。
- RetroArch v1.21.0 由 `tools/build-retroarch-h700.sh` 构建，最大 GLIBC 需求 **2.28**，
  设备 glibc 2.35 可以加载；旧 ROCKNIX 二进制需要 `GLIBC_2.43` 且缺 `libass.so.9`，无法运行。
- 运行库：`libSDL2-2.0.so.0`、`libsamplerate.so.0`、`libUMP.so.3.0.0`（同 toolchain sysroot）。
- 核心：mGBA（`.gba`）与 Gambatte（`.gb`/`.gbc`），均只依赖 `GLIBC_2.33` 及以下。
- 输入：设备检测到 `ANBERNIC-keys`（15 按钮 / 6 轴 / 1 hat）；可用的设备运行用
  `input_autodetect_enable=false` + 显式 SDL2 键位。手柄事件本身尚未验证。

## 手动复现命令

```sh
# 1) 停掉启动器 runtime，让 /dev/fb0 空出来，然后暂停 supervisor
adb -s 5c0010894414c802512 shell 'kill -STOP $(pgrep -f launch_frontend.sh); kill -9 $(pgrep -f "pocket-linux-kms --package")'
# 2) 前台运行（不要加 &，否则在它画完之前 shell 就退出）
adb -s 5c0010894414c802512 shell 'cd /storage/emu-test && \
  LD_LIBRARY_PATH=lib SDL_VIDEODRIVER=mali SDL_RENDER_DRIVER=opengles2 SDL_JOYSTICK_DISABLED=1 \
  timeout 25 ./ra-v3 --config emu.cfg -L lib/mgba_libretro.so apotris.gba'
# 3) 另开一个 shell 抓帧
adb -s 5c0010894414c802512 shell 'dd if=/dev/fb0 of=/storage/emu-test/fb.raw bs=2880 count=480'
# 4) 恢复 supervisor
adb -s 5c0010894414c802512 shell 'kill -CONT $(pgrep -f launch_frontend.sh)'
```

`dd` 必须在 emulator 还活着的时候执行；进程退出后再抓只会得到启动器的画面。

## 镜像集成

`build-rootfs.sh` 把这些文件装进镜像（都在 rootfs，**需要重刷 SYSTEM 分区**才在设备上生效）：

- `/usr/bin/retroarch`、`/usr/lib/libretro/{mgba,gambatte}_libretro.so`
- `/usr/lib/{libSDL2-2.0.so.0,libsamplerate.so.0,libUMP.so.3.0.0}`（+ `libUMP.so.3` 链接）
- `/usr/share/retroarch/retroarch.cfg`
- `/usr/bin/pocket-game-play`（ROM → 核心选择 → RetroArch）
- `/usr/bin/{pocket-gamehub-play,pocketshell-games}`

ROM 由 `frontend-session` 从 `/usr/share/pocketshell/System/pocketjs/apps/apotris.gba`
装到 `$SD/apps/apotris.gba`，`launch_frontend.sh` 再复制到
`$SD/content/games/homebrew/apotris.gba`（扫描器根目录）。

细节见 [docs/22-retroarch-gba.md](../../22-retroarch-gba.md)。
