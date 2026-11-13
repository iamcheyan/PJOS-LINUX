#!/usr/bin/env python3
"""Configure Linux KMS program for BaseOS integer scaling and package budget.

The upstream Linux KMS program adds a duplicate RasterRenderer as renderer 1
instead of using RendererId::SOFTWARE (renderer 0), which causes coordinator
set_scale() at boot to update renderer 0 while the display remains bound to
the unscaled renderer 1.

It also raises the default heap limit to 64 MiB for baked glyph packages.
"""

import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1])
    text = path.read_text()
    
    old_heap = "heap_limit: 32 * 1024 * 1024,"
    new_heap = "heap_limit: 64 * 1024 * 1024,"
    if old_heap in text:
        text = text.replace(old_heap, new_heap, 1)

    old_renderer = """    let renderer = runtime
        .add_renderer(pocket_raster::RasterRenderer::new(profile.density).map_err(error)?)
        .map_err(error)?;"""
    new_renderer = "    let renderer = pocket_runtime::RendererId::SOFTWARE;"
    if old_renderer in text:
        text = text.replace(old_renderer, new_renderer, 1)

    path.write_text(text)

    guest_lib = path.parent.parent.parent.parent / "engine/guest-rquickjs/src/lib.rs"
    if guest_lib.is_file():
        guest_text = guest_lib.read_text()
        old_remember = "            self.last_error = Some(error.to_string());"
        new_remember = '            eprintln!("Guest error: {error}");\n            self.last_error = Some(error.to_string());'
        if old_remember in guest_text and 'eprintln!("Guest error: {error}");' not in guest_text:
            guest_lib.write_text(guest_text.replace(old_remember, new_remember, 1))


if __name__ == "__main__":
    main()
