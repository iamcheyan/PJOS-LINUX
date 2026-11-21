#!/usr/bin/env python3
import sys
from pathlib import Path

def patch_fbdev(tree_dir: Path):
    lib_rs = tree_dir / "platforms/linux/fbdev/src/lib.rs"
    native_rs = tree_dir / "platforms/linux/fbdev/src/native.rs"
    
    if not lib_rs.is_file() or not native_rs.is_file():
        print(f"fbdev-pan patch: skipping (files not found in {tree_dir})")
        return

    # 1. Patch lib.rs
    content = lib_rs.read_text(encoding="utf-8")
    if "fn present(&mut self)" not in content:
        content = content.replace(
            "pub trait FrameStore {\n    fn bytes_mut(&mut self) -> &mut [u8];\n}",
            "pub trait FrameStore {\n    fn bytes_mut(&mut self) -> &mut [u8];\n    fn present(&mut self) {}\n}"
        )
        old_flush = """        self.sequence = sequence;
        self.pending = Some(sequence);
        self.acquired = false;
        Ok(sequence)"""
        new_flush = """        self.sequence = sequence;
        self.pending = Some(sequence);
        self.acquired = false;
        self.store.present();
        Ok(sequence)"""
        content = content.replace(old_flush, new_flush)
        lib_rs.write_text(content, encoding="utf-8")
        print(f"Patched {lib_rs} with FrameStore::present() and flush presentation")

    # 2. Patch native.rs
    content = native_rs.read_text(encoding="utf-8")
    if "variable.activate = 128" not in content:
        old_mapping = """pub struct Mapping {
    pointer: *mut libc::c_void,
    length: usize,
    _file: File,
}
impl FrameStore for Mapping {
    fn bytes_mut(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.pointer.cast(), self.length) }
    }
}"""
        new_mapping = """pub struct Mapping {
    pointer: *mut libc::c_void,
    length: usize,
    file: File,
}
impl FrameStore for Mapping {
    fn bytes_mut(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.pointer.cast(), self.length) }
    }
    fn present(&mut self) {
        let mut variable = Variable::default();
        unsafe {
            if libc::ioctl(self.file.as_raw_fd(), 0x4600, &mut variable) >= 0 {
                variable.activate = 128; // FB_ACTIVATE_FORCE
                libc::ioctl(self.file.as_raw_fd(), 0x4606, &mut variable);
            }
        }
    }
}"""
        content = content.replace(old_mapping, new_mapping)
        content = content.replace("_file: file,", "file,")
        native_rs.write_text(content, encoding="utf-8")
        print(f"Patched {native_rs} with FBIOPAN_DISPLAY ioctl")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: apply-pocketjs-fbdev-pan.py <runtime-tree-or-src-dir>")
        sys.exit(1)
    patch_fbdev(Path(sys.argv[1]))
