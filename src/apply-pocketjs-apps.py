#!/usr/bin/env python3
"""Add installed-app listing, launch and close arms to the pinned bridge.

The launcher no longer bundles non-terminal programs. It lists every
`/storage/apps/<id>.pocket` with `APPS<TAB>list`, starts one with
`LAUNCH<TAB><id>`, and a child app returns to the supervisor with
`APP<TAB>close`. The native hand-off script owns the marker and the runtime
exit, so these arms only validate the id and delegate.

    python3 src/apply-pocketjs-apps.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import sys

ARM_ANCHOR = '        ["LAUNCH", app] if ["disk", "xmplayer"].contains(app) => {'

ARMS = '''        ["APPS", "list"] => apps_list(),
        ["APP", "close"] => app_close(),
        ["LAUNCH", app] if apps_launch_ready(app) => apps_launch(app),
'''

HELPER = '''
// ── Installed PocketJS programs ─────────────────────────────────────────────────
fn apps_list() -> String {
    let mut rows: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir("/storage/apps") {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if let Some(id) = name.strip_suffix(".pocket") {
                if !id.is_empty()
                    && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
                {
                    rows.push(id.to_string());
                }
            }
        }
    }
    rows.sort();
    rows.join("\\n")
}

fn apps_launch_ready(app: &str) -> bool {
    !app.is_empty()
        && app.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
        && std::path::Path::new(&format!("/storage/apps/{}.pocket", app)).exists()
}

fn native_launch(app: &str) -> Option<String> {
    let helper = [
        "/storage/System/compat/bin/pocketjs-native-launch",
        "/mnt/sdcard/System/compat/bin/pocketjs-native-launch",
        "/usr/bin/pocketjs-native-launch",
    ]
    .iter()
    .find(|path| std::path::Path::new(path).is_file())?;
    match Command::new(helper)
        .arg(app)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(_) => Some(app.to_string()),
        Err(_) => None,
    }
}

fn apps_launch(app: &str) -> String {
    if !apps_launch_ready(app) {
        return format!("error:missing:{}", app);
    }
    match native_launch(app) {
        Some(id) => format!("launching:{}", id),
        None => "error:launcher".into(),
    }
}

fn app_close() -> String {
    match native_launch("exit") {
        Some(_) => "ok".into(),
        None => "error:launcher".into(),
    }
}
'''


def main(source_path: str) -> int:
    source = Path(source_path)
    text = source.read_text()

    if "fn apps_list(" in text and '"APPS", "list"' in text:
        print("already applied: installed app arms")
        return 0
    if text.count(ARM_ANCHOR) != 1:
        raise SystemExit(
            f"anchor for the LAUNCH arm appears {text.count(ARM_ANCHOR)} times"
        )

    text = text.replace(ARM_ANCHOR, ARMS + ARM_ANCHOR, 1)
    text = text.rstrip() + "\n" + HELPER
    source.write_text(text)
    print("applied installed app arms")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
