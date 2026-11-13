#!/usr/bin/env python3
"""Enable isolated framebuffer capture and fixture input in a debug runtime."""
from pathlib import Path
import sys


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit("headless-debug: unsupported source")
    return text.replace(old, new, 1)


def main(root):
    root = Path(root)
    main_source = root / "programs/linux-kms/src/main.rs"
    text = main_source.read_text()
    if "struct PjosCaptureStore" not in text:
        helper = '''struct PjosCaptureStore(Vec<u8>);
impl pocket_linux_fbdev::FrameStore for PjosCaptureStore {
    fn bytes_mut(&mut self) -> &mut [u8] { &mut self.0 }
}
impl Drop for PjosCaptureStore {
    fn drop(&mut self) {
        if let Ok(path) = std::env::var("PJOS_HEADLESS_CAPTURE") {
            let _ = std::fs::write(path, &self.0);
        }
    }
}

'''
        text = replace_once(text, "fn run(options: Options)", helper + "fn run(options: Options)")
        text = replace_once(text, "pocket_linux_fbdev::Framebuffer::new(vec![0; budget / 2], geometry)?", "pocket_linux_fbdev::Framebuffer::new(PjosCaptureStore(vec![0; budget / 2]), geometry)?")
        text = replace_once(text, "struct DiagnosticInput;", "struct DiagnosticInput { tick: u64 }")
        text = replace_once(text, "    fn poll(&mut self, _: &mut InputFrameBuilder) {}", '''    fn poll(&mut self, frame: &mut InputFrameBuilder) {
        self.tick += 1;
        let button = std::env::var("PJOS_TEST_BUTTON");
        if (5..=7).contains(&self.tick) {
            frame.buttons |= match button.as_deref() {
                Ok("right") => pocket_spec::btn::RIGHT,
                Ok("left-confirm") => pocket_spec::btn::LEFT,
                Ok("confirm") => pocket_spec::btn::CIRCLE,
                _ => 0,
            };
        } else if (25..=27).contains(&self.tick) && button.as_deref() == Ok("left-confirm") {
            frame.buttons |= pocket_spec::btn::CIRCLE;
        }
    }''')
        text = replace_once(text, "Box::new(DiagnosticInput)", "Box::new(DiagnosticInput { tick: 0 })")
        main_source.write_text(text)
    bridge = root / "engine/guest-rquickjs/src/pocketshell_launcher.rs"
    text = bridge.read_text()
    if "PJOS_TEST_LIBRARY" not in text:
        text = replace_once(text, "fn games_library() -> String {\n", 'fn games_library() -> String {\n    if let Ok(path) = std::env::var("PJOS_TEST_LIBRARY") { return std::fs::read_to_string(path).unwrap_or_default(); }\n')
        text = replace_once(text, '["ROMLAUNCH", path] => games_launch(path),', '["ROMLAUNCH", path] => { if let Ok(log) = std::env::var("PJOS_TEST_LAUNCH_LOG") { let _ = std::fs::write(log, path); "Starting game".into() } else { games_launch(path) } },')
        bridge.write_text(text)


if __name__ == "__main__":
    main(sys.argv[1])
