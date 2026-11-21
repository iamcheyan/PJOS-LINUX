#!/bin/sh
# One-click sync script: Sync local resouces/series to connected RG34XX
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERIES_DIR="$HERE/series"

echo "=== 正在检测 RG34XX 设备连接 ==="
if adb devices 2>/dev/null | grep -q '5c0010894414c802512.*device'; then
    echo "使用本地 USB ADB 直连..."
    echo "=== 开始同步游戏资源到 /storage/content/games/series/ ==="
    for dir in "$SERIES_DIR"/*; do
        [ -d "$dir" ] || continue
        name=${dir##*/}
        adb -s 5c0010894414c802512 push "$dir/series.json" "/storage/content/games/series/$name/"
        adb -s 5c0010894414c802512 push "$dir/cover.png" "/storage/content/games/series/$name/"
        adb -s 5c0010894414c802512 push "$dir/gba" "/storage/content/games/series/$name/"
    done
    echo "=== 重新构建掌机游戏库索引 ==="
    adb -s 5c0010894414c802512 shell '/storage/System/compat/bin/pocketshell-games'
    echo "=== 重新加载 PocketShell 界面 ==="
    adb -s 5c0010894414c802512 shell 'pids=$(pidof pocket-linux-kms || :); [ -n "$pids" ] && kill -TERM $pids || :'
elif ssh -o ConnectTimeout=3 hx90 "adb -s 5c0010894414c802512 get-state" 2>/dev/null | grep -q 'device'; then
    echo "通过 hx90 ADB 桥接连接 RG34XX..."
    echo "=== 开始同步游戏资源到 /storage/content/games/series/ ==="
    rsync -av --delete --exclude="translation-work" "$SERIES_DIR/" hx90:/tmp/staged_series/
    ssh hx90 "adb -s 5c0010894414c802512 push /tmp/staged_series/. /storage/content/games/series/ && rm -rf /tmp/staged_series"
    echo "=== 重新构建掌机游戏库索引 ==="
    ssh hx90 "adb -s 5c0010894414c802512 shell '/storage/System/compat/bin/pocketshell-games'"
    echo "=== 重新加载 PocketShell 界面 ==="
    ssh hx90 "adb -s 5c0010894414c802512 shell 'pids=\$(pidof pocket-linux-kms || :); [ -n \"\$pids\" ] && kill -TERM \$pids || :'"
else
    echo "错误: 未找到在线的 RG34XX 设备！请确保 USB 线已连接。" >&2
    exit 1
fi

echo "=== 同步完成！所有游戏与伴生翻译包已在掌机就绪 ==="
