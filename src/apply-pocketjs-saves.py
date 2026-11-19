#!/usr/bin/env python3
from pathlib import Path
import sys

HELPER = r'''
// BaseOS Save & Savestate Manager bridge
const TMC_LOCATIONS: &[&str] = &[
    "未知区域", "滚滚山", "滚滚山麓", "塔玛兰切荒地",
    "风之遗迹", "王家谷", "特里尔比高地", "西林",
    "城堡庭园", "北海拉鲁平原", "海拉鲁镇", "南海拉鲁平原",
    "贝勒泉", "贝勒瀑布", "隆隆牧场", "东丘",
    "云顶", "海利亚湖", "密林", "圣域",
    "塞拉之村", "梅拉里矿山", "海拉鲁城堡", "森林神殿",
    "森林神殿", "火焰洞窟", "风之要塞", "水之神殿",
    "风之宫殿", "暗之城堡", "王家墓地", "大戈隆迷宫"
];

fn extract_tmc_stats(path: &std::path::Path) -> Option<String> {
    use std::io::{Read, Seek, SeekFrom};
    let mut f = std::fs::File::open(path).ok()?;
    let meta = f.metadata().ok()?;
    if meta.len() < 0x61000 {
        return None;
    }
    let mut hearts = 0;
    let mut rupees = 0;
    let mut loc_name = "未知区域";

    if f.seek(SeekFrom::Start(0x23AEB)).is_ok() {
        let mut b = [0u8; 1];
        if f.read_exact(&mut b).is_ok() {
            hearts = b[0] / 8;
        }
    }
    if f.seek(SeekFrom::Start(0x23B00)).is_ok() {
        let mut b = [0u8; 2];
        if f.read_exact(&mut b).is_ok() {
            rupees = u16::from_le_bytes(b);
        }
    }
    if f.seek(SeekFrom::Start(0x54A91)).is_ok() {
        let mut b = [0u8; 1];
        if f.read_exact(&mut b).is_ok() {
            let idx = b[0] as usize;
            if idx < TMC_LOCATIONS.len() {
                loc_name = TMC_LOCATIONS[idx];
            }
        }
    }
    Some(format!("hearts={};rupees={};loc={}", hearts, rupees, loc_name))
}

fn scan_saves_in_dir(dir: &std::path::Path, results: &mut Vec<(String, String, String, String, u64, u64, String)>) {
    if let Ok(entries) = std::fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                scan_saves_in_dir(&path, results);
                continue;
            }
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("").to_string();
            let is_save = name.contains(".state") || name.ends_with(".srm") || name.ends_with(".sav") || name.starts_with("retrobilingual-slot");
            if !is_save || name.ends_with(".bak") {
                continue;
            }

            let meta = match entry.metadata() {
                Ok(m) => m,
                Err(_) => continue,
            };
            let size = meta.len();
            let mtime = meta.modified().ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);

            let (game_title, kind, label) = if name.starts_with("retrobilingual-slot") {
                let slot_num = name.trim_start_matches("retrobilingual-slot").trim_end_matches(".state");
                ("塞尔达传说：缩小帽".to_string(), "slot".to_string(), format!("快捷存档 槽位{}", slot_num))
            } else if name.to_lowercase().contains("zelda") || name.contains("缩小帽") || name.to_lowercase().contains("boushi") {
                if name.ends_with(".state.auto") {
                    ("塞尔达传说：缩小帽".to_string(), "auto_state".to_string(), "自动即时存档".into())
                } else if name.ends_with(".srm") || name.ends_with(".sav") {
                    ("塞尔达传说：缩小帽".to_string(), "battery".to_string(), "电池记忆 (SRAM)".into())
                } else {
                    ("塞尔达传说：缩小帽".to_string(), "state".to_string(), "即时存档".into())
                }
            } else if name.contains("黄金太阳") || name.to_lowercase().contains("golden") || name.to_lowercase().contains("ougon") {
                if name.ends_with(".state.auto") {
                    ("黄金太阳：开启的封印".to_string(), "auto_state".to_string(), "自动即时存档".into())
                } else if name.ends_with(".srm") || name.ends_with(".sav") {
                    ("黄金太阳：开启的封印".to_string(), "battery".to_string(), "电池记忆 (SRAM)".into())
                } else {
                    ("黄金太阳：开启的封印".to_string(), "state".to_string(), "即时存档".into())
                }
            } else if name.to_lowercase().contains("apotris") {
                ("Apotris".to_string(), "auto_state".to_string(), "自动即时存档".into())
            } else if name.to_lowercase().contains("celeste") {
                ("蔚蓝 (Celeste)".to_string(), "auto_state".to_string(), "自动即时存档".into())
            } else if name.to_lowercase().contains("snek") {
                ("贪吃蛇 (Snek)".to_string(), "auto_state".to_string(), "自动即时存档".into())
            } else if name.to_lowercase().contains("googledino") {
                ("小恐龙 (Dino)".to_string(), "auto_state".to_string(), "自动即时存档".into())
            } else {
                let clean = name.replace(".state.auto", "").replace(".state", "").replace(".srm", "").replace(".sav", "");
                let g = if clean.is_empty() { "其他游戏".to_string() } else { clean };
                if name.ends_with(".srm") || name.ends_with(".sav") {
                    (g, "battery".to_string(), "电池记忆 (SRAM)".into())
                } else {
                    (g, "state".to_string(), "即时存档".into())
                }
            };

            let extra = if game_title == "塞尔达传说：缩小帽" {
                extract_tmc_stats(&path).unwrap_or_default()
            } else {
                String::new()
            };

            results.push((
                game_title,
                kind,
                label,
                path.to_string_lossy().to_string(),
                size,
                mtime,
                extra,
            ));
        }
    }
}

fn saves_list() -> String {
    let mut results = Vec::new();
    let dirs = [
        std::path::Path::new("/storage/.config/pocketjs"),
        std::path::Path::new("/storage/pocketshell/states"),
        std::path::Path::new("/storage/pocketshell/saves"),
        std::path::Path::new("/storage/content/games"),
    ];
    for d in dirs {
        if d.is_dir() {
            scan_saves_in_dir(d, &mut results);
        }
    }

    results.sort_by(|a, b| b.5.cmp(&a.5)); // Sort newest mtime first
    let mut lines = Vec::new();
    for (title, kind, label, path, size, mtime, extra) in results {
        lines.push(format!("{}\t{}\t{}\t{}\t{}\t{}\t{}", title, kind, label, path, size, mtime, extra));
    }
    lines.join("\n")
}

fn saves_export(path_str: &str) -> String {
    let src = std::path::Path::new(path_str.trim());
    if !src.is_file() {
        return "error:file_not_found".into();
    }
    let file_name = match src.file_name() {
        Some(f) => f,
        None => return "error:invalid_filename".into(),
    };
    let backup_dir = std::path::Path::new("/storage/backups/saves");
    if let Err(e) = std::fs::create_dir_all(backup_dir) {
        return format!("error:create_dir_failed:{}", e);
    }
    let dest = backup_dir.join(file_name);
    match std::fs::copy(src, &dest) {
        Ok(_) => format!("ok\t{}", dest.to_string_lossy()),
        Err(e) => format!("error:copy_failed:{}", e),
    }
}

fn saves_export_all() -> String {
    let list_str = saves_list();
    if list_str.is_empty() {
        return "error:no_saves_found".into();
    }
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let backup_dir = std::path::PathBuf::from(format!("/storage/backups/saves/backup-{}", now));
    if let Err(e) = std::fs::create_dir_all(&backup_dir) {
        return format!("error:create_dir_failed:{}", e);
    }

    let mut copied = 0;
    for line in list_str.lines() {
        let parts: Vec<&str> = line.split('\t').collect();
        if parts.len() >= 4 {
            let src = std::path::Path::new(parts[3]);
            if src.is_file() {
                if let Some(name) = src.file_name() {
                    let dest = backup_dir.join(name);
                    if std::fs::copy(src, dest).is_ok() {
                        copied += 1;
                    }
                }
            }
        }
    }
    format!("ok\t{}\t{}", copied, backup_dir.to_string_lossy())
}

'''

def main(path):
    source = Path(path)
    text = source.read_text()
    if '// BaseOS Save & Savestate Manager bridge' in text:
        return
    anchor = '    match fields.as_slice() {\n'
    if text.count(anchor) != 1 or text.count('pub fn command(') != 1:
        raise SystemExit('saves: unsupported bridge anchors')
    arms = '        ["SAVES", "list"] => saves_list(),\n        ["SAVES", "export", path] => saves_export(path),\n        ["SAVES", "export_all"] => saves_export_all(),\n'
    text = text.replace(anchor, anchor + arms, 1)
    source.write_text(text.replace('pub fn command(', HELPER + 'pub fn command(', 1))

if __name__ == '__main__':
    main(sys.argv[1])
