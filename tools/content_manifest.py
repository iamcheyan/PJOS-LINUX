#!/usr/bin/env python3
"""Emit a path-sorted rootfs manifest without extracting archives or following symlinks."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile


def digest(stream):
    h = hashlib.sha256()
    with stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def quote(value):
    return json.dumps(str(value), ensure_ascii=True)


def tree_rows(root):
    def visit(directory):
        for path in directory.iterdir():
            st = path.lstat()
            kind = stat.filemode(st.st_mode)[0]
            detail = ''
            if kind == '-':
                detail = ' ' + digest(path.open('rb'))
            elif kind == 'l':
                detail = ' -> ' + quote(os.readlink(path))
            elif kind in ('b', 'c'):
                detail = f' {os.major(st.st_rdev)}:{os.minor(st.st_rdev)}'
            yield str(path.relative_to(root)), st.st_mode, st.st_uid, st.st_gid, kind, detail
            if kind == 'd':
                yield from visit(path)
    yield from visit(root)


def archive_rows(path):
    with tarfile.open(path) as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name == PurePosixPath('.') and member.isdir():
                continue
            if name.is_absolute() or '..' in name.parts:
                raise ValueError(f'non-relative archive path: {name}')
            detail = ''
            if member.isfile() or member.islnk():
                kind, detail = '-', ' ' + digest(archive.extractfile(member))
            elif member.issym():
                kind, detail = 'l', ' -> ' + quote(member.linkname)
            elif member.isdir():
                kind = 'd'
            elif member.ischr() or member.isblk():
                kind = 'c' if member.ischr() else 'b'
                detail = f' {member.devmajor}:{member.devminor}'
            elif member.isfifo():
                kind = 'p'
            else:
                raise ValueError(f'unsupported tar member: {name}')
            yield str(name), member.mode, member.uid, member.gid, kind, detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    source = parser.parse_args().source
    rows = tree_rows(source) if source.is_dir() else archive_rows(source)
    manifest = {}
    for path, mode, uid, gid, kind, detail in rows:
        if path in manifest:
            sys.exit(f'duplicate member: {quote(path)}')
        manifest[path] = f'{stat.S_IMODE(mode):04o} {uid} {gid} {kind} {quote(path)}{detail}'
    for path in sorted(manifest, key=os.fsencode):
        print(manifest[path])


if __name__ == '__main__':
    main()
