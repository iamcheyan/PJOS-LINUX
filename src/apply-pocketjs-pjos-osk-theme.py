#!/usr/bin/env python3
"""Add PJOS's square pixel skin to the shared PocketJS OSK component.

The keyboard controller, layouts, focus and input handling stay in
@pocketjs/framework/osk. Applications opt into this skin with theme="pjos".
"""
from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"pjos osk: expected one anchor: {old[:72]!r}")
    return source.replace(old, new, 1)


def replace_default(source: str, old: str, new: str) -> str:
    """Replace a legacy default once, while allowing an idempotent rerun."""
    if old not in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"pjos osk: expected one default anchor: {old[:72]!r}")
    return source.replace(old, new, 1)


def main(path: Path) -> None:
    source = path.read_text()
    if 'export type OskThemeName = "dark" | "light" | "classic" | "pjos";' in source:
        if 'pjos: "relative bg-[#19172b]' not in source:
            raise SystemExit("pjos osk: incomplete existing theme")
    else:
        source = replace_once(
            source,
            'export type OskThemeName = "dark" | "light" | "classic";',
            'export type OskThemeName = "dark" | "light" | "classic" | "pjos";',
        )
        source = replace_once(
            source,
            'const PANEL: Readonly<Record<OskThemeName, string>> = {\n',
            'const PANEL: Readonly<Record<OskThemeName, string>> = {\n'
            '  pjos: "relative bg-[#19172b] border-[#38334f]",\n',
        )
        source = replace_once(
            source,
            'const KEY: Readonly<Record<OskThemeName, { readonly key: string; readonly special: string }>> = {\n',
            'const KEY: Readonly<Record<OskThemeName, { readonly key: string; readonly special: string }>> = {\n'
            '  pjos: {\n'
            '    key: "absolute items-center justify-center bg-[#242039] border border-[#4b4163] focus:bg-[#39304e] focus:border-[#f2ce76] active:bg-[#5b4b72]",\n'
            '    special: "absolute items-center justify-center bg-[#211d33] border border-[#4b4163] focus:bg-[#39304e] focus:border-[#f2ce76] active:bg-[#5b4b72]",\n'
            '  },\n',
        )
        source = replace_once(
            source,
            'const INK: Readonly<Record<OskThemeName, string>> = { dark: "#dbe7ee", light: "#1c2430", classic: "#263950" };',
            'const INK: Readonly<Record<OskThemeName, string>> = { dark: "#dbe7ee", light: "#1c2430", classic: "#263950", pjos: "#f5eddb" };',
        )
        source = replace_once(
            source,
            'const INK_DIM: Readonly<Record<OskThemeName, string>> = { dark: "#8fa3ad", light: "#5f6b78", classic: "#4f5d70" };',
            'const INK_DIM: Readonly<Record<OskThemeName, string>> = { dark: "#8fa3ad", light: "#5f6b78", classic: "#4f5d70", pjos: "#f2ce76" };',
        )
    if '  pjos: "text-xs text-[#f5eddb]",' not in source:
        source = replace_once(
            source,
            'const FIELD_TEXT: Readonly<Record<OskThemeName, string>> = {\n',
            'const FIELD_TEXT: Readonly<Record<OskThemeName, string>> = {\n'
            '  pjos: "text-xs text-[#f5eddb]",\n',
        )
    if 'props.theme === "pjos"' not in source:
        source = replace_once(
            source,
            '          (props.theme === "classic"\n',
            '          (props.theme === "pjos"\n'
            '            ? "bg-[#242039] border border-[#4b4163] px-2 py-1 focus:border-[#f2ce76] active:bg-[#39304e]"\n'
            '            : props.theme === "classic"\n',
        )

    # PJOS is the system look, not an opt-in ornament. These defaults cover
    # both public keyboard seams: <Osk>, TextField and oskHeight().
    replacements = (
        ('  /** Default "dark". */\n', '  /** Default "pjos". */\n'),
        ('theme={props.theme ?? "dark"}', 'theme={props.theme ?? "pjos"}'),
        (
            'theme: OskThemeName = "dark", layout?: OskLayoutKind',
            'theme: OskThemeName = "pjos", layout?: OskLayoutKind',
        ),
        (
            'get theme() { return props.theme; }',
            'get theme() { return props.theme ?? "pjos"; }',
        ),
    )
    for old, new in replacements:
        source = replace_default(source, old, new)

    # TextField's default class, ink and placeholder must agree with the
    # theme it sends to <Osk>; otherwise an un-themed field gets a PJOS panel
    # above a dark legacy input box.
    if '          (props.theme === "pjos"' in source and 'props.theme === undefined' not in source:
        source = replace_once(
            source,
            '          (props.theme === "pjos"\n',
            '          (props.theme === undefined || props.theme === "pjos"\n',
        )
    source = replace_default(
        source,
        '              ? FIELD_TEXT[props.theme ?? "dark"]',
        '              ? FIELD_TEXT[props.theme ?? "pjos"]',
    )
    if (
        ': props.theme === "classic" ? "text-sm text-[#667485]" : "text-sm text-slate-500";'
        in source
    ):
        source = replace_once(
            source,
            ': props.theme === "classic" ? "text-sm text-[#667485]" : "text-sm text-slate-500";',
            (
                ': props.theme === "classic"\n'
                '                ? "text-sm text-[#667485]"\n'
                '                : props.theme === undefined || props.theme === "pjos"\n'
                '                ? "text-sm text-[#f2ce76]"\n'
                '                : "text-sm text-slate-500";'
            ),
        )
    path.write_text(source)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-pocketjs-pjos-osk-theme.py <sdk/framework/src/osk.tsx>")
    main(Path(sys.argv[1]))
