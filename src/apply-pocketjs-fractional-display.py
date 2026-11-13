#!/usr/bin/env python3
"""Enable the RG34XX 480x320 -> 720x480 software presentation path."""
from pathlib import Path
import sys


def replace_once(text, old, new, name):
    if text.count(old) != 1:
        raise SystemExit(f"fractional-display: unsupported {name}")
    return text.replace(old, new, 1)


def main(root):
    root = Path(root)
    runtime = root / "engine/runtime/src/lib.rs"
    text = runtime.read_text()
    if "pjos_fractional_cpu" not in text:
        text = replace_once(text, "                let scale = physical[0] / logical[0];", "                let pjos_fractional_cpu = physical == [720, 480] && logical == [480, 320] && display.role == DisplayRole::Primary;\n                let scale = physical[0] / logical[0];", "runtime scale")
        text = replace_once(text, "                        || physical != [logical[0] * scale, logical[1] * scale]", "                        || (!pjos_fractional_cpu && physical != [logical[0] * scale, logical[1] * scale])", "runtime validation")
        runtime.write_text(text)

    coordinator = root / "engine/present/src/coordinator.rs"
    text = coordinator.read_text()
    if "pjos_fractional_cpu" not in text:
        anchor = "            let list = match descriptor.role {"
        insert = "            let pjos_fractional_cpu = descriptor.role == DisplayRole::Primary && descriptor.target_ownership == TargetOwnership::CpuVisible && descriptor.width == 720 && descriptor.height == 480 && viewport == (480.0, 320.0) && self.scale == 1;\n"
        text = replace_once(text, anchor, insert + anchor, "coordinator role")
        text = replace_once(text, "                        && (descriptor.width != primary_width", "                        && !pjos_fractional_cpu\n                        && (descriptor.width != primary_width", "coordinator dimensions")
        text = replace_once(text, "            let viewport = if native_primary {", "            let viewport = if native_primary || pjos_fractional_cpu {", "coordinator viewport")
        text = replace_once(text, "            let identity = identity.filter(|_| {\n                !native_primary", "            let identity = identity.filter(|_| {\n                !pjos_fractional_cpu && (!native_primary", "coordinator damage start")
        text = replace_once(text, "                        && descriptor.height == primary_height\n            });", "                        && descriptor.height == primary_height)\n            });", "coordinator damage end")
        coordinator.write_text(text)

    lib = root / "engine/raster/src/lib.rs"
    text = lib.read_text()
    if "extern crate alloc;" not in text:
        text = replace_once(text, "#![no_std]\n", "#![no_std]\n\nextern crate alloc;\n", "raster allocator")
        lib.write_text(text)
    surface = root / "engine/raster/src/surface.rs"
    text = surface.read_text()
    if "pjos_fractional_render" in text and "pjos_cache" not in text:
        raise SystemExit("fractional-display: outdated patch; rebuild from an unpatched source tree")
    if "pjos_fractional_render" not in text:
        text = replace_once(text, "    scale: u32,\n}\n\nimpl RasterRenderer", "    scale: u32,\n    pjos_cache: PjosFrameCache,\n}\n\nimpl RasterRenderer", "raster storage")
        text = replace_once(text, "        Ok(Self { scale })", "        Ok(Self { scale, pjos_cache: PjosFrameCache::default() })", "raster construction")
        text = replace_once(text, "        match &mut frame.target {\n", "        if self.scale == 1 && frame.resources.viewport() == (480.0, 320.0) {\n            if let Target::CpuVisible(surface) = &mut frame.target {\n                if surface.region().width == 720 {\n                    return pjos_fractional_render(frame.resources, &frame.list.words, surface, &mut self.pjos_cache);\n                }\n            }\n        }\n        match &mut frame.target {\n", "raster dispatch")
        anchor = "/// Clear the acquired region to opaque black, then render the DrawList."
        helper = '''#[derive(Default)]
struct PjosFrameCache {
    pixels: alloc::vec::Vec<u8>,
    words: alloc::vec::Vec<u32>,
    revision: Option<u64>,
    format: Option<PixelFormat>,
}

fn pjos_fractional_render(resources: &dyn RenderResources, words: &[u32], surface: &mut Surface<'_>, cache: &mut PjosFrameCache) -> Result<(), RenderError> {
    let bytes_per_pixel = match surface.format() {
        PixelFormat::Argb8888 | PixelFormat::Rgba8888 => 4,
        PixelFormat::Rgb565 => 2,
        _ => return Err(RenderError::Unsupported),
    };
    let stride = 480 * bytes_per_pixel;
    let revision = resources.raster_revision();
    let format = surface.format();
    if cache.revision != Some(revision) || cache.format != Some(format) || cache.words != words {
        cache.revision = None;
        cache.pixels.resize(stride * 320, 0);
        let mut intermediate = Surface::new(cache.pixels.as_mut_slice(), Rect::new(0, 0, 480, 320), stride, format).map_err(|_| RenderError::InvalidFrame)?;
        render_surface(resources, words, &mut intermediate, 1)?;
        cache.words.clear();
        cache.words.extend_from_slice(words);
        cache.revision = Some(revision);
        cache.format = Some(format);
    }
    let region = surface.region();
    let target_stride = surface.stride_bytes();
    let target = surface.pixels_mut();
    let input = cache.pixels.as_slice();
    for y in 0..region.height as usize {
        let source_y = (y + region.y as usize) * 2 / 3;
        for x in 0..region.width as usize {
            let source_x = (x + region.x as usize) * 2 / 3;
            let source_offset = source_y * stride + source_x * bytes_per_pixel;
            let target_offset = y * target_stride + x * bytes_per_pixel;
            target[target_offset..target_offset + bytes_per_pixel].copy_from_slice(&input[source_offset..source_offset + bytes_per_pixel]);
        }
    }
    Ok(())
}

'''
        text = replace_once(text, anchor, helper + anchor, "raster helper")
        surface.write_text(text)


if __name__ == "__main__":
    main(sys.argv[1])
