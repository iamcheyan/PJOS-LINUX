#!/usr/bin/env python3
"""Add the KANADE bridge command to the PocketShell launcher bridge.

The PocketJS guest on this profile has no network capability, so the Kanade app
cannot call videod itself. This adds one narrow command whose verbs map to fixed
videod endpoints; the HTTP call is made by the static ``kanade-ctl`` helper so
the render thread only waits on a short-lived process with a hard timeout.

    KANADE<TAB>status|library|watch_later|favorites|history|downloads
    KANADE<TAB>settings|storage|sync|clear
    KANADE<TAB>watch<TAB><video_id>       marks watched
    KANADE<TAB>favorite<TAB><video_id>    toggles favourite
    KANADE<TAB>play<TAB><video_id>        starts playback
    KANADE<TAB>later<TAB><video_id>       adds to watch later

Every arm returns the raw JSON body (or a short ``error:`` string), which the
app parses. Anchored on the ROMS arm so it applies to any bridge revision that
carries the games library.

    python3 src/apply-pocketjs-kanade.py <pocketshell-launcher.rs>
"""
from pathlib import Path
import sys

ANCHORS = [
    '        ["ROMS"] => games_library(),',
    '        ["APPS", "list"] => apps_list(),',
    '        ["LANGUAGE"] | ["LANGUAGE", _] => language_command(&fields),',
]

ARMS = '''        ["KANADE", verb] => kanade_call(verb, ""),
        ["KANADE", verb, arg] => kanade_call(verb, arg),
'''

HELPER = r'''

// ── Kanade (videod on loopback) ─────────────────────────────────────────────
// One narrow command instead of a generic HTTP proxy: every verb maps to a
// fixed endpoint, so the guest cannot address arbitrary URLs or methods.
// The render thread must never block, hence the hard timeout and the static
// helper process (kanade-ctl) rather than an HTTP client in this binary.
fn kanade_endpoint(verb: &str, arg: &str) -> Option<(&'static str, String, Option<String>)> {
    let safe = |s: &str| s.len() <= 64 && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == ':');
    let got = |what: &str, method: &'static str, path: String| Some((method, path, Some(format!("{{\"video_id\":\"{}\"}}", what))));
    match verb {
        "status"      => Some(("GET",  "/api/health".into(), None)),
        "library"     => Some(("GET",  "/api/library?limit=100".into(), None)),
        "watch_later" => Some(("GET",  "/api/watch_later?limit=100".into(), None)),
        "favorites"   => Some(("GET",  "/api/favorites?limit=100".into(), None)),
        "history"     => Some(("GET",  "/api/history?limit=100".into(), None)),
        "downloads"   => Some(("GET",  "/api/downloads?limit=100".into(), None)),
        "settings"    => Some(("GET",  "/api/settings".into(), None)),
        "storage"     => Some(("GET",  "/api/storage".into(), None)),
        "sync"        => Some(("POST", "/api/sync".into(), Some("{\"what\":\"library\"}".into()))),
        "settings_put" if !arg.is_empty() => Some(("PUT", "/api/settings".into(), Some(arg.to_string()))),
        "nas_status"  => Some(("GET", "/api/share/status".into(), None)),
        "nas_test"    => Some(("POST", "/api/share/test".into(), Some("{}".into()))),
        "nas_pull"    => Some(("POST", "/api/share/pull".into(), Some("{}".into()))),
        "clear"       => Some(("POST", "/api/storage/clear?scope=orphans".into(), None)),
        // Raw RGBA at the row cover size; kanade-ctl base64s octet-stream bodies.
        "thumb" if safe(arg) && !arg.is_empty()    => Some(("GET", format!("/api/thumb/{}?w=32&h=16", arg), None)),
        "play" if safe(arg) && !arg.is_empty()     => got(arg, "POST", "/api/player/play".into()),
        "watched" if safe(arg) && !arg.is_empty()  => got(arg, "POST", format!("/api/library/{}/watched", arg)),
        "later" if safe(arg) && !arg.is_empty()    => got(arg, "POST", format!("/api/watch_later/{}", arg)),
        "favorite" if safe(arg) && !arg.is_empty() => got(arg, "POST", format!("/api/favorites/{}", arg)),
        _ => None,
    }
}


fn kanade_unhex(value: &str) -> Option<String> {
    if value.len() % 2 != 0 || value.len() > 1024 {
        return None;
    }
    let bytes: Option<Vec<u8>> = (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).ok())
        .collect();
    String::from_utf8(bytes?).ok()
}

fn kanade_call<S: AsRef<str>>(verb: S, arg: &str) -> String {
    // Slice patterns over `&[&str]` bind `&&str`, so the verb is normalised here
    // instead of forcing every arm to guess the level of indirection.
    let verb = verb.as_ref();
    // The share password arrives hex-encoded: argv is readable by every process
    // on the panel, so a passphrase must not sit in plain sight in \`ps\`.
    let resolved = if verb == "nas_password" {
        match kanade_unhex(arg) {
            Some(password) => {
                let escaped = password.replace('\\\\', "\\\\\\\\").replace('"', "\\\\\\"");
                Some(("POST", "/api/share/password".to_string(), Some(format!("{{\\"password\\":\\"{}\\"}}", escaped))))
            }
            None => None,
        }
    } else {
        kanade_endpoint(verb, arg)
    };
    let Some((method, path, body)) = resolved else {
        return "error:bad-verb".into();
    };
    let ctl = ["/storage/System/compat/bin/kanade-ctl", "/mnt/sdcard/System/compat/bin/kanade-ctl"]
        .iter()
        .find(|candidate| std::path::Path::new(candidate).exists())
        .copied();
    let Some(ctl) = ctl else { return "error:no-ctl".into() };

    // Explicit &str conversions: a Vec<&str> built from String references only
    // coerces at some call sites, which makes this fragile across rustc versions.
    let mut argv: Vec<&str> = vec!["12", ctl, method, path.as_str()];
    let owned = body.unwrap_or_default();
    if !owned.is_empty() {
        argv.push(owned.as_str());
    }
    match Command::new("/usr/bin/timeout")
        .args(&argv)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
    {
        Ok(out) if !out.stdout.is_empty() => {
            let text = String::from_utf8_lossy(&out.stdout).into_owned();
            text.trim().to_string()
        }
        Ok(_) => "error:empty".into(),
        Err(_) => "error:unreachable".into(),
    }
}
'''


def main(path: str) -> int:
    source = Path(path)
    text = source.read_text()
    if 'fn kanade_call' in text:
        print('already applied')
        return 0
    for anchor in ANCHORS:
        if anchor in text:
            text = text.replace(anchor, ARMS + anchor, 1)
            break
    else:
        print('no anchor for KANADE arms', file=sys.stderr)
        return 1
    source.write_text(text.rstrip() + '\n' + HELPER)
    print('applied KANADE bridge')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
