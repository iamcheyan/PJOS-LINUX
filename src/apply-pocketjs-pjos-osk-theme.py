#!/usr/bin/env python3
"""Add PJOS's modern Material 3 skin and mature handheld layout to the PocketJS OSK component.

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


def patch_osk_layout(layout_path: Path) -> None:
    if not layout_path.exists():
        return
    source = layout_path.read_text()
    if 'label: "?123"' in source:
        return  # already patched

    old_grid = """const GRID_BOTTOM: OskKeyDef[] = [
  { action: "hide", label: "▼", w: 1.5 },
  { action: "left", label: "‹", w: 1.5 },
  { ch: " ", label: "", w: 7 },
  { action: "right", label: "›", w: 1.5 },
  { action: "enter", label: "✓", w: 1.5 },
];

const GRID_LAYERS: Partial<Record<OskLayerName, OskKeyDef[][]>> = {
  lower: [
    [{ action: "layer", to: "symbols", label: "1#", w: 1.5 }, ...chars("qwertyuiop"), { action: "backspace", label: "⌫", w: 1.5 }],
    [{ action: "shift", label: "ABC", w: 2 }, ...chars("asdfghjkl"), { action: "enter", label: "↵", w: 2 }],
    chars("_-zxcvbnm.,:"),
    GRID_BOTTOM,
  ],
  upper: [
    [{ action: "layer", to: "symbols", label: "1#", w: 1.5 }, ...chars("QWERTYUIOP"), { action: "backspace", label: "⌫", w: 1.5 }],
    [{ action: "shift", label: "abc", w: 2 }, ...chars("ASDFGHJKL"), { action: "enter", label: "↵", w: 2 }],
    chars("_-ZXCVBNM.,:"),
    GRID_BOTTOM,
  ],
  symbols: [
    [{ action: "layer", to: "lower", label: "abc", w: 1.5 }, ...chars("1234567890"), { action: "backspace", label: "⌫", w: 1.5 }],
    [...chars("+-*/=%!?@"), { action: "enter", label: "↵", w: 2 }],
    chars("#()[]'\";&$,."),
    GRID_BOTTOM,
  ],
};"""

    new_grid = """const GRID_BOTTOM: OskKeyDef[] = [
  { action: "layer", to: "symbols", label: "?123", w: 1.5 },
  { action: "left", label: "‹", w: 1.2 },
  { ch: " ", label: "Space", w: 6.1 },
  { action: "right", label: "›", w: 1.2 },
  { action: "hide", label: "▼", w: 1.5 },
];

const GRID_BOTTOM_SYMBOLS: OskKeyDef[] = [
  { action: "layer", to: "lower", label: "ABC", w: 1.5 },
  { action: "left", label: "‹", w: 1.2 },
  { ch: " ", label: "Space", w: 6.1 },
  { action: "right", label: "›", w: 1.2 },
  { action: "hide", label: "▼", w: 1.5 },
];

const GRID_LAYERS: Partial<Record<OskLayerName, OskKeyDef[][]>> = {
  lower: [
    [...chars("qwertyuiop"), { action: "backspace", label: "⌫", w: 1.5 }],
    [...chars("asdfghjkl"), { action: "enter", label: "↵", w: 2.5 }],
    [{ action: "shift", label: "⇧", w: 1.5 }, ...chars("zxcvbnm"), { ch: ",", w: 1 }, { ch: ".", w: 1 }, { ch: "/", w: 1 }],
    GRID_BOTTOM,
  ],
  upper: [
    [...chars("QWERTYUIOP"), { action: "backspace", label: "⌫", w: 1.5 }],
    [...chars("ASDFGHJKL"), { action: "enter", label: "↵", w: 2.5 }],
    [{ action: "shift", label: "abc", w: 1.5 }, ...chars("ZXCVBNM"), { ch: ",", w: 1 }, { ch: ".", w: 1 }, { ch: "/", w: 1 }],
    GRID_BOTTOM,
  ],
  symbols: [
    [...chars("1234567890"), { action: "backspace", label: "⌫", w: 1.5 }],
    [...chars("-+=*/%@#&"), { action: "enter", label: "↵", w: 2.5 }],
    [...chars("()[]{}:;!?"), { ch: "~", w: 1.5 }],
    GRID_BOTTOM_SYMBOLS,
  ],
};"""

    if old_grid in source:
        source = source.replace(old_grid, new_grid)
        layout_path.write_text(source)


def main(path: Path) -> None:
    patch_osk_layout(path.parent / "osk-layout.ts")
    source = path.read_text()
    if 'export type OskThemeName = "dark" | "light" | "classic" | "pjos";' in source:
        pass
    else:
        source = replace_once(
            source,
            'export type OskThemeName = "dark" | "light" | "classic";',
            'export type OskThemeName = "dark" | "light" | "classic" | "pjos";',
        )

    # Panel styling: modern Material 3 dark surface container
    if 'pjos: "relative bg-[#141218] border-t border-[#2b2930] p-[6px]",' not in source:
        if 'pjos: "relative bg-[#19172b] border-[#38334f]",' in source:
            source = source.replace(
                'pjos: "relative bg-[#19172b] border-[#38334f]",',
                'pjos: "relative bg-[#141218] border-t border-[#2b2930] p-[6px]",',
            )
        else:
            source = replace_once(
                source,
                'const PANEL: Readonly<Record<OskThemeName, string>> = {\n',
                'const PANEL: Readonly<Record<OskThemeName, string>> = {\n'
                '  pjos: "relative bg-[#141218] border-t border-[#2b2930] p-[6px]",\n',
            )

    # Key styling: Material 3 elevated rounded-[10px] keycaps with high-contrast active/focus rings
    target_key = (
        '  pjos: {\n'
        '    key: "absolute rounded-[10px] items-center justify-center bg-[#2b2930] border border-[#3b3842] focus:bg-[#4a4458] focus:border-2 focus:border-[#d0bcff] active:bg-[#635b70]",\n'
        '    special: "absolute rounded-[10px] items-center justify-center bg-[#211f26] border border-[#36343b] focus:bg-[#4a4458] focus:border-2 focus:border-[#d0bcff] active:bg-[#635b70]",\n'
        '  },\n'
    )
    if 'key: "absolute rounded-[10px] items-center justify-center bg-[#2b2930]' not in source:
        if 'pjos: {' in source:
            # replace existing pjos block
            start = source.index('pjos: {')
            end = source.index('},\n', start) + 3
            source = source[:start] + target_key.strip() + source[end:]
        else:
            source = replace_once(
                source,
                'const KEY: Readonly<Record<OskThemeName, { readonly key: string; readonly special: string }>> = {\n',
                'const KEY: Readonly<Record<OskThemeName, { readonly key: string; readonly special: string }>> = {\n'
                + target_key,
            )

    # Inks
    if 'pjos: "#e6e0e9"' not in source:
        if 'pjos: "#f5eddb"' in source:
            source = source.replace('pjos: "#f5eddb"', 'pjos: "#e6e0e9"')
        else:
            source = replace_once(
                source,
                'const INK: Readonly<Record<OskThemeName, string>> = { dark: "#dbe7ee", light: "#1c2430", classic: "#263950" };',
                'const INK: Readonly<Record<OskThemeName, string>> = { dark: "#dbe7ee", light: "#1c2430", classic: "#263950", pjos: "#e6e0e9" };',
            )
    if 'pjos: "#cac4d0"' not in source:
        if 'pjos: "#f2ce76"' in source:
            source = source.replace('pjos: "#f2ce76"', 'pjos: "#cac4d0"')
        else:
            source = replace_once(
                source,
                'const INK_DIM: Readonly<Record<OskThemeName, string>> = { dark: "#8fa3ad", light: "#5f6b78", classic: "#4f5d70" };',
                'const INK_DIM: Readonly<Record<OskThemeName, string>> = { dark: "#8fa3ad", light: "#5f6b78", classic: "#4f5d70", pjos: "#cac4d0" };',
            )

    # Distinct Enter primary keycap
    if 'key.action === "enter" && props.theme === "pjos"' not in source:
        old_keycls = 'const keyCls = (key: OskKeyDef): string => (key.ch === undefined ? KEY[props.theme].special : KEY[props.theme].key);'
        new_keycls = (
            'const keyCls = (key: OskKeyDef): string =>\n'
            '    (key.action === "enter" && props.theme === "pjos"\n'
            '      ? "absolute rounded-[10px] items-center justify-center bg-[#4f378b] border border-[#d0bcff] focus:bg-[#654b9e] focus:border-2 focus:border-[#ffffff] active:bg-[#7e62ba]"\n'
            '      : key.ch === undefined\n'
            '      ? KEY[props.theme].special\n'
            '      : KEY[props.theme].key);'
        )
        if old_keycls in source:
            source = source.replace(old_keycls, new_keycls)

    # Scale key fonts when rowHeight >= 28
    if 'const letterCls = kind === "staggered" ? "text-sm" : "text-xs font-bold";' in source:
        source = source.replace(
            'const letterCls = kind === "staggered" ? "text-sm" : "text-xs font-bold";',
            'const letterCls = rowHeight >= 28 ? "text-lg font-bold" : (kind === "staggered" ? "text-sm" : "text-xs font-bold");',
        )
    if 'rect().key.ch !== undefined && rect().key.ch !== " " ? letterCls : "text-xs font-bold"' in source:
        source = source.replace(
            'rect().key.ch !== undefined && rect().key.ch !== " " ? letterCls : "text-xs font-bold"',
            'rect().key.ch !== undefined && rect().key.ch !== " " ? letterCls : (rowHeight >= 28 ? "text-sm font-bold" : "text-xs font-bold")',
        )
    if 'lineHeight: kind === "staggered" ? 14 : 12,' in source:
        source = source.replace(
            'lineHeight: kind === "staggered" ? 14 : 12,',
            'lineHeight: rowHeight >= 28 ? 24 : (kind === "staggered" ? 14 : 12),',
        )
    if 'rect().key.action === "enter" && props.theme === "pjos"' not in source:
        source = source.replace(
            'textColor: isPressed(rect()) ? "#ffffff" : rect().key.ch !== undefined ? INK[props.theme] : INK_DIM[props.theme],',
            'textColor: isPressed(rect())\n'
            '                          ? "#ffffff"\n'
            '                          : rect().key.action === "enter" && props.theme === "pjos"\n'
            '                          ? "#ffffff"\n'
            '                          : rect().key.ch !== undefined\n'
            '                          ? INK[props.theme]\n'
            '                          : INK_DIM[props.theme],',
        )

    # Defaults
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

    path.write_text(source)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-pocketjs-pjos-osk-theme.py <sdk/framework/src/osk.tsx>")
    main(Path(sys.argv[1]))
