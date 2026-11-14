# RetroBilingual tools

The CLI provides GBA ROM identity checks, version-gated TMC text extraction, offline SQLite alignment/review, and a runtime pack builder. Extracted text keeps raw glyph bytecode until a proven Unicode mapping exists; no fabricated text or translation examples are included.

## Commands

```sh
python3 tools/retrobilingual/retrobilingual.py inspect --rom /path/to/game.gba
python3 tools/retrobilingual/retrobilingual.py extract --rom /path/to/tmc-jp.gba --language ja --output japanese.json
python3 tools/retrobilingual/retrobilingual.py extract --rom /path/to/tmc-zh.gba --language zh --output chinese.json
python3 tools/retrobilingual/retrobilingual.py import --input /path/to/japanese.json --language ja --database /path/to/translations.db
python3 tools/retrobilingual/retrobilingual.py import --input /path/to/chinese.json --language zh --database /path/to/translations.db
python3 tools/retrobilingual/retrobilingual.py align --japanese /path/to/japanese.json --chinese /path/to/chinese.json --database /path/to/translations.db --report /path/to/alignment-report.json
python3 tools/retrobilingual/retrobilingual.py review --database /path/to/translations.db --mapping-id 1 --status approved --note 'checked in game'
python3 tools/retrobilingual/pack.py --database /path/to/translations.db --texts /path/to/approved-zh.json \
  --source-rom-sha256 16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38 \
  --output /path/to/retrobilingual.pack
```

`inspect` reports the file SHA-1/SHA-256, GBA title/game code and header-checksum status. It does not identify a ROM as a trusted game version by filename.

Text export JSON uses `game: "zelda_minish_cap"`, `language: "ja"` or `"zh"`, a 64-digit `rom_sha256`, and an `entries` array. Each entry requires `source_id` and UTF-8 `text`; `context_id` defaults to the empty string and `page_index` defaults to zero. Optional fields are `rom_offset`, `script_reference`, and a string array `controls`. Duplicate IDs are accepted and surfaced as ambiguous when they collide on the full ID/context/page key.

Alignment only suggests unique exact ID/context/page matches. Suggestions remain `pending` until reviewed; repeat alignment preserves an unchanged approval and resets it if either text changes. Runtime lookup must filter for `review_status='approved'` and the exact source ROM hash.
`extract` only accepts the exact ROM hashes with a verified table profile (JP `16ac…b38` at `0x9B1A30`; the installed BZMJ Chinese ROM `f51c…66d` at `0xDCA000`). Other ROMs fail with an explicit error instead of guessing offsets.

`pack.py` joins approved database mappings with a UTF-8 `approved-zh.json` (`{"entries":[{"source_id","page_index","text"}]}`), rasterizes only those characters with the OFL Sarasa UI SC font (default; FusionPixel's zh_hans file is a launcher subset and misses common characters), and embeds a no-translation notice. The runtime overlay at `docs/retrobilingual-runtime.md` consumes the pack; unapproved mappings are never included.

All commands use Python's standard library. Keep ROMs and extracted commercial-game text outside version control; store only local hashes and generated databases on the user's device.
