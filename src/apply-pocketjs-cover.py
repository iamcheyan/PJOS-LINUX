#!/usr/bin/env python3
from pathlib import Path
import sys

HELPER = r'''
// BaseOS launcher cover decoding (v1).
fn launcher_cover(path: &str, variant: &str) -> String {
    use base64::Engine;
    use image::GenericImageView;
    use std::io::Cursor;
    let size = match variant { "cover" => (128, 128), "background" => (192, 128), _ => return String::new() };
    if !path.starts_with('/') || path.len() > 4096 { return String::new(); }
    let Ok(meta) = std::fs::metadata(path) else { return String::new(); };
    if !meta.is_file() || meta.len() > 16 * 1024 * 1024 { return String::new(); }
    let Ok(bytes) = std::fs::read(path) else { return String::new(); };
    let Ok(reader) = image::ImageReader::new(Cursor::new(bytes)).with_guessed_format() else { return String::new(); };
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(8192);
    limits.max_image_height = Some(8192);
    limits.max_alloc = Some(64 * 1024 * 1024);
    let mut reader = reader;
    reader.limits(limits);
    let Ok(decoded) = reader.decode() else { return String::new(); };
    let (width, height) = decoded.dimensions();
    if width == 0 || height == 0 { return String::new(); }
    let fitted = decoded.resize_to_fill(size.0, size.1, image::imageops::FilterType::Triangle);
    let result = if variant == "background" { fitted.blur(4.0).resize_exact(128, 128, image::imageops::FilterType::Triangle) } else { fitted };
    let mut pixels = result.to_rgba8();
    if variant == "cover" {
        let radius: i32 = 20;
        for y in 0..128_i32 {
            for x in 0..128_i32 {
                let dx = if x < radius { radius - 1 - x } else if x >= 128 - radius { x - (128 - radius) } else { 0 };
                let dy = if y < radius { radius - 1 - y } else if y >= 128 - radius { y - (128 - radius) } else { 0 };
                if dx * dx + dy * dy >= radius * radius { pixels.get_pixel_mut(x as u32, y as u32).0[3] = 0; }
            }
        }
    }
    base64::engine::general_purpose::STANDARD.encode(pixels.as_raw())
}

'''

def main(path):
    source = Path(path)
    text = source.read_text()
    if '// BaseOS launcher cover decoding (v1).' not in text:
        anchor = '    match fields.as_slice() {\n'
        if text.count(anchor) != 1 or text.count('pub fn command(') != 1:
            raise SystemExit('cover: unsupported bridge anchors')
        text = text.replace(anchor, anchor + '        ["COVER", variant, path] => launcher_cover(path, variant),\n', 1)
        source.write_text(text.replace('pub fn command(', HELPER + 'pub fn command(', 1))
    cargo = source.parent.parent / 'Cargo.toml'
    manifest = cargo.read_text()
    if 'image = { version = "0.25.10", default-features = false, features = ["png", "jpeg"] }' not in manifest:
        manifest = manifest.replace('[dependencies]\n', '[dependencies]\nimage = { version = "0.25.10", default-features = false, features = ["png", "jpeg"] }\nbase64 = "0.23"\n', 1)
        cargo.write_text(manifest)

if __name__ == '__main__':
    main(sys.argv[1])
