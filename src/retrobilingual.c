/* RetroBilingual mGBA integration: in-frame menu, pause and subtitle overlay.
 * SPDX-License-Identifier: MPL-2.0
 *
 * Frame path: this module is called from the libretro core before
 * video_cb, so everything is composited into the GBA 240x160 framebuffer.
 * No external window, no framebuffer race with the launcher.
 *
 * ROM gate: exact JP SHA-256 is carried by the translation pack; the core
 * computes the ROM SHA-256 once and refuses the pack on mismatch.
 *
 * Keys (RetroPad ids):
 *   X (9) short press       -> quick menu (never part of GBA keymap)
 *   L (10) + Select (2)     -> toggle subtitle (default, configurable)
 *   options: quick save/load and subtitle chord are configurable.
 * Select+Start long press and L2/R2 are left to baseos-hotkeys.
 */
#ifdef RB_HOST_TEST
#include "host_stubs.h"
#define COLOR_16_BIT 1
#else
#include "retrobilingual.h"
#include "libretro.h"

#include <mgba/core/core.h>
#include <mgba/gba/core.h>
#include <mgba/internal/gba/gba.h>
#include <mgba-util/vfs.h>
#endif

#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define RB_JP_ROM_CRC32 0x6CE771A5u
#define RB_JP_ROM_SIZE  0x01000000u
#define RB_JP_ROM_SHA256 \
    "16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38"

#define RB_EWRAM_MESSAGE      0x50u
#define RB_EWRAM_TEXT_RENDER  0x22780u
#define RB_MSG_STATE_ACTIVE   0x7Fu

#define RB_KEY_A      (1u << 0)
#define RB_KEY_B      (1u << 1)
#define RB_KEY_SELECT (1u << 2)
#define RB_KEY_START  (1u << 3)
#define RB_KEY_RIGHT  (1u << 4)
#define RB_KEY_LEFT   (1u << 5)
#define RB_KEY_UP     (1u << 6)
#define RB_KEY_DOWN   (1u << 7)
#define RB_KEY_R      (1u << 8)
#define RB_KEY_L      (1u << 9)

#define RB_FB_W 240
#define RB_FB_H 160
#define RB_MAX_GLYPHS 8192
#define RB_MAX_ENTRIES 4096
#define RB_MAX_TEXT 512

typedef enum { RB_GAME, RB_MENU, RB_SUBTITLE, RB_BINDINGS } RBState;
typedef enum { ACT_SAVE, ACT_LOAD, ACT_SUBTITLE, ACT_COUNT } RBAction;

typedef struct {
    uint32_t codepoint;
    uint16_t glyph_index;
} RBGlyph;

typedef struct {
    uint16_t text_id;
    uint8_t page;
    uint16_t first_glyph;
    uint16_t glyph_count;
} RBEntry;

static struct {
    int loaded;
    int glyph_w, glyph_h;
    uint32_t glyph_count, entry_count;
    RBGlyph glyphs[RB_MAX_GLYPHS];
    uint8_t* bits;             /* glyph_count * glyph_bytes */
    size_t glyph_bytes;
    RBEntry entries[RB_MAX_ENTRIES];
    uint16_t* indices;         /* sequences for all entries */
    size_t index_count;
    int16_t codepoint_map[0x10000];
} sPack;

static RBState sState;
static int sRomMatched;
static int sMenuCursor;
static int sBindingCursor;
static int sBindingCapture;
static int sBindingPending[2];
static int sBindingCount;

typedef struct {
    int enabled;
    int chord[ACT_COUNT][2];   /* RetroPad ids, -1 = unset */
} RBConfig;
static RBConfig sCfg = {
    .enabled = 1,
    .chord = {
        { -1, -1 },            /* save */
        { -1, -1 },            /* load */
        { RETRO_DEVICE_ID_JOYPAD_L, RETRO_DEVICE_ID_JOYPAD_SELECT },
    },
};

static uint32_t sPrevKeys;
static int sPrevX;
static int sPrevAction[ACT_COUNT];

static struct mCore* sCore;
static void* sStateBuf;
static size_t sStateSize;
static char sConfigPath[512];
static char sPackPath[512];
static char sStatePath[512];

static uint16_t sDlgTextId;
static uint8_t sDlgPage;
static uint8_t sDlgRender;
static int sDlgActive;
static int sDlgChanged;
static uint16_t sDlgGlyphStart;
static uint16_t sDlgGlyphCount;

/* ---------- SHA-256 ---------------------------------------------------- */
typedef struct { uint32_t h[8]; uint64_t len; uint8_t buf[64]; size_t fill; } Sha256;
static const uint32_t SHA_K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};
#define RB_ROR(x,n) (((x)>>(n))|((x)<<(32-(n))))
static void sha_block(Sha256* s, const uint8_t* p) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = (uint32_t)p[i*4]<<24 | (uint32_t)p[i*4+1]<<16 | (uint32_t)p[i*4+2]<<8 | p[i*4+3];
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = RB_ROR(w[i-15],7) ^ RB_ROR(w[i-15],18) ^ (w[i-15]>>3);
        uint32_t s1 = RB_ROR(w[i-2],17) ^ RB_ROR(w[i-2],19) ^ (w[i-2]>>10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=s->h[0],b=s->h[1],c=s->h[2],d=s->h[3],e=s->h[4],f=s->h[5],g=s->h[6],h=s->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = RB_ROR(e,6) ^ RB_ROR(e,11) ^ RB_ROR(e,25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + SHA_K[i] + w[i];
        uint32_t S0 = RB_ROR(a,2) ^ RB_ROR(a,13) ^ RB_ROR(a,22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    s->h[0]+=a; s->h[1]+=b; s->h[2]+=c; s->h[3]+=d;
    s->h[4]+=e; s->h[5]+=f; s->h[6]+=g; s->h[7]+=h;
}
static void sha_init(Sha256* s) {
    static const uint32_t iv[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                                   0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    memcpy(s->h, iv, sizeof(iv)); s->len = 0; s->fill = 0;
}
static void sha_update(Sha256* s, const void* data, size_t n) {
    const uint8_t* p = data;
    s->len += n;
    while (n--) {
        s->buf[s->fill++] = *p++;
        if (s->fill == 64) { sha_block(s, s->buf); s->fill = 0; }
    }
}
static void sha_final(Sha256* s, uint8_t out[32]) {
    uint64_t bits = s->len * 8;
    uint8_t pad = 0x80;
    sha_update(s, &pad, 1);
    uint8_t zero = 0;
    while (s->fill != 56) sha_update(s, &zero, 1);
    uint8_t lenbe[8];
    for (int i = 0; i < 8; i++) lenbe[i] = (uint8_t)(bits >> (56 - i*8));
    sha_update(s, lenbe, 8);
    for (int i = 0; i < 8; i++) {
        out[i*4] = (uint8_t)(s->h[i]>>24); out[i*4+1] = (uint8_t)(s->h[i]>>16);
        out[i*4+2] = (uint8_t)(s->h[i]>>8); out[i*4+3] = (uint8_t)s->h[i];
    }
}

/* ---------- config and pack paths -------------------------------------- */
static void rb_paths(void) {
    const char* dir = getenv("RETROBILINGUAL_DIR");
    if (!dir) dir = "/storage/.config/pocketjs";
    snprintf(sConfigPath, sizeof(sConfigPath), "%s/retrobilingual.conf", dir);
    snprintf(sPackPath, sizeof(sPackPath), "%s/retrobilingual.pack", dir);
    snprintf(sStatePath, sizeof(sStatePath), "%s/retrobilingual-quick.state", dir);
}

static void rb_config_load(void) {
    rb_paths();
    FILE* f = fopen(sConfigPath, "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        int a = -1, b = -1, v = -1;
        if (sscanf(line, "subtitle_enabled=%d", &v) == 1) sCfg.enabled = v != 0;
        else if (sscanf(line, "bind_save=%d,%d", &a, &b) == 2) { sCfg.chord[ACT_SAVE][0]=a; sCfg.chord[ACT_SAVE][1]=b; }
        else if (sscanf(line, "bind_load=%d,%d", &a, &b) == 2) { sCfg.chord[ACT_LOAD][0]=a; sCfg.chord[ACT_LOAD][1]=b; }
        else if (sscanf(line, "bind_subtitle=%d,%d", &a, &b) == 2) { sCfg.chord[ACT_SUBTITLE][0]=a; sCfg.chord[ACT_SUBTITLE][1]=b; }
    }
    fclose(f);
}

static void rb_config_save(void) {
    rb_paths();
    FILE* f = fopen(sConfigPath, "w");
    if (!f) return;
    fprintf(f, "subtitle_enabled=%d\n", sCfg.enabled ? 1 : 0);
    for (int i = 0; i < ACT_COUNT; i++) {
        const char* key = i == ACT_SAVE ? "bind_save" : i == ACT_LOAD ? "bind_load" : "bind_subtitle";
        fprintf(f, "%s=%d,%d\n", key, sCfg.chord[i][0], sCfg.chord[i][1]);
    }
    fclose(f);
}

/* ---------- translation pack ------------------------------------------ */
static uint32_t rd32(const uint8_t* p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static uint16_t rd16(const uint8_t* p) { return (uint16_t)(p[0]|(p[1]<<8)); }

static int rb_pack_load(void) {
    if (sPack.loaded) return 1;
    rb_paths();
    FILE* f = fopen(sPackPath, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < 64 || size > 8 * 1024 * 1024) { fclose(f); return 0; }
    uint8_t* data = malloc((size_t)size);
    if (!data || fread(data, 1, (size_t)size, f) != (size_t)size) { free(data); fclose(f); return 0; }
    fclose(f);

    if (memcmp(data, "RBPK", 4) != 0) { free(data); return 0; }
    int ok = 0;
    do {
        if (rd16(data + 4) != 1) break;
        sPack.glyph_w = rd16(data + 6);
        sPack.glyph_h = rd16(data + 8);
        sPack.glyph_count = rd32(data + 10);
        sPack.entry_count = rd32(data + 14);
        if (sPack.glyph_w < 6 || sPack.glyph_w > 32 || sPack.glyph_h < 6 || sPack.glyph_h > 32) break;
        if (sPack.glyph_count > RB_MAX_GLYPHS || sPack.entry_count > RB_MAX_ENTRIES) break;
        size_t off = 18;
        if (off + 32 > (size_t)size) break;
        /* ROM hash gate */
        Sha256 sha; sha_init(&sha);
        const struct GBA* gba = sCore ? sCore->board : NULL;
        if (!gba || gba->memory.romSize != RB_JP_ROM_SIZE) break;
        sha_update(&sha, gba->memory.rom, gba->memory.romSize);
        uint8_t digest[32]; sha_final(&sha, digest);
        if (memcmp(digest, data + off, 32) != 0) break;
        off += 32;

        sPack.glyph_bytes = ((size_t)sPack.glyph_w * sPack.glyph_h + 7) / 8;
        size_t glyph_table = (size_t)sPack.glyph_count * (4 + sPack.glyph_bytes);
        size_t entry_table = (size_t)sPack.entry_count * 8;
        if (off + glyph_table + entry_table > (size_t)size) break;

        memset(sPack.codepoint_map, 0xFF, sizeof(sPack.codepoint_map));
        sPack.bits = malloc((size_t)sPack.glyph_count * sPack.glyph_bytes);
        if (!sPack.bits) break;
        for (uint32_t i = 0; i < sPack.glyph_count; i++) {
            uint32_t cp = rd32(data + off);
            off += 4;
            if (cp < 0x10000) sPack.codepoint_map[cp] = (int16_t)i;
            memcpy(sPack.bits + (size_t)i * sPack.glyph_bytes, data + off, sPack.glyph_bytes);
            off += sPack.glyph_bytes;
        }
        for (uint32_t i = 0; i < sPack.entry_count; i++) {
            sPack.entries[i].text_id = rd16(data + off);
            sPack.entries[i].page = data[off + 2];
            sPack.entries[i].first_glyph = rd16(data + off + 4);
            sPack.entries[i].glyph_count = rd16(data + off + 6);
            off += 8;
        }
        /* Remaining bytes: glyph index sequences. */
        size_t index_bytes = (size_t)size - off;
        sPack.index_count = index_bytes / 2;
        sPack.indices = malloc(index_bytes);
        if (!sPack.indices) break;
        memcpy(sPack.indices, data + off, index_bytes);
        for (uint32_t i = 0; i < sPack.entry_count; i++) {
            RBEntry* e = &sPack.entries[i];
            if ((size_t)e->first_glyph + e->glyph_count > sPack.index_count) { ok = -1; break; }
        }
        if (ok < 0) break;
        ok = 1;
        sPack.loaded = 1;
    } while (0);
    free(data);
    return ok == 1;
}

static int rb_find_entry(uint16_t text_id, uint8_t page, RBEntry** out) {
    for (uint32_t i = 0; i < sPack.entry_count; i++) {
        RBEntry* e = &sPack.entries[i];
        if (e->text_id == text_id && e->page == page) { *out = e; return 1; }
    }
    return 0;
}

/* ---------- dialogue state --------------------------------------------- */
static void rb_dialogue_read(const struct GBA* gba) {
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    uint8_t  state   = ewram[RB_EWRAM_MESSAGE];
    uint16_t textId  = rd16(ewram + RB_EWRAM_MESSAGE + 8);
    uint8_t  render  = ewram[RB_EWRAM_TEXT_RENDER + 0x89];
    int active = (state & RB_MSG_STATE_ACTIVE) != 0;

    if (!active) {
        if (sDlgActive) sDlgChanged = 1;
        sDlgActive = 0;
        return;
    }
    if (!sDlgActive || textId != sDlgTextId) {
        sDlgTextId = textId;
        sDlgPage = 0;
        sDlgChanged = 1;
    } else if (sDlgRender == 3 && render == 4) {
        if (sDlgPage < 0xFF) sDlgPage++;
        sDlgChanged = 1;
    }
    sDlgRender = render;
    sDlgActive = 1;

    RBEntry* e = NULL;
    if (sPack.loaded && rb_find_entry(sDlgTextId, sDlgPage, &e)) {
        sDlgGlyphStart = e->first_glyph;
        sDlgGlyphCount = e->glyph_count;
    } else {
        sDlgGlyphStart = 0;
        sDlgGlyphCount = 0;
    }
}

/* ---------- drawing ---------------------------------------------------- */
#ifdef COLOR_16_BIT
typedef uint16_t pixel_t;
#define PITCH_PIXELS(p) ((p) / 2u)
static inline uint16_t shade(uint16_t c) { return (uint16_t)((c >> 1) & 0x3DEF); }
#else
typedef uint32_t pixel_t;
#define PITCH_PIXELS(p) ((p) / 4u)
static inline uint32_t shade(uint32_t c) { return (c >> 1) & 0xFEFEFEFEu; }
#endif

static void rect(pixel_t* fb, unsigned p, int x, int y, int w, int h, pixel_t c) {
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x + w > RB_FB_W) w = RB_FB_W - x;
    if (y + h > RB_FB_H) h = RB_FB_H - y;
    for (int r = 0; r < h; r++)
        for (int c2 = 0; c2 < w; c2++)
            fb[(y + r) * p + x + c2] = c;
}

static void glyph(pixel_t* fb, unsigned p, int x, int y, uint16_t index) {
    if (!sPack.loaded || index >= sPack.glyph_count) return;
    int gw = sPack.glyph_w, gh = sPack.glyph_h;
    const uint8_t* bmp = sPack.bits + (size_t)index * sPack.glyph_bytes;
    for (int gy = 0; gy < gh; gy++) {
        int dx = x, dy = y + gy;
        if (dy < 0 || dy >= RB_FB_H) continue;
        for (int gx = 0; gx < gw; gx++) {
            int bit = gy * gw + gx;
            if (!(bmp[bit >> 3] & (0x80 >> (bit & 7)))) continue;
            if (dx >= 0 && dx < RB_FB_W) fb[dy * p + dx] = 0xFFFF;
            dx++;
        }
    }
}

static void draw_sequence(pixel_t* fb, unsigned p, int x, int y, int max_w,
                          uint16_t start, uint16_t count) {
    int cx = x, cy = y;
    for (uint16_t i = 0; i < count; i++) {
        uint16_t idx = sPack.indices[start + i];
        if (idx == 0xFFFF) { cx = x; cy += sPack.glyph_h; continue; }
        if (cx + sPack.glyph_w > x + max_w) { cx = x; cy += sPack.glyph_h; }
        if (cy + sPack.glyph_h > RB_FB_H) break;
        glyph(fb, p, cx, cy, idx);
        cx += sPack.glyph_w;
    }
}

static const char* action_name(int a) {
    return a == ACT_SAVE ? "SAVE" : a == ACT_LOAD ? "LOAD" : "SUBTITLE";
}

/* Minimal UI font: draw a 5x7 ASCII glyph from a compact table. */
static const uint8_t UI_FONT[96][5] = {
    {0,0,0,0,0},{0,0,0x5F,0,0},{0,7,0,7,0},{0x14,0x7F,0x14,0x7F,0x14},
    {0x24,0x2A,0x7F,0x2A,0x12},{0x23,0x13,0x08,0x64,0x62},{0x36,0x49,0x55,0x22,0x50},
    {0,5,3,0,0},{0,0x1C,0x22,0x41,0},{0,0x41,0x22,0x1C,0},{0x14,0x08,0x3E,0x08,0x14},
    {0x08,0x08,0x3E,0x08,0x08},{0,0x50,0x30,0,0},{0x08,0x08,0x08,0x08,0x08},
    {0,0x60,0x60,0,0},{0x20,0x10,0x08,0x04,0x02},{0x3E,0x51,0x49,0x45,0x3E},
    {0,0x42,0x7F,0x40,0},{0x42,0x61,0x51,0x49,0x46},{0x21,0x41,0x45,0x4B,0x31},
    {0x18,0x14,0x12,0x7F,0x10},{0x27,0x45,0x45,0x45,0x39},{0x3C,0x4A,0x49,0x49,0x30},
    {0x01,0x71,0x09,0x05,0x03},{0x36,0x49,0x49,0x49,0x36},{0x06,0x49,0x49,0x29,0x1E},
    {0,0x36,0x36,0,0},{0,0x56,0x36,0,0},{0x08,0x14,0x22,0x41,0},
    {0x14,0x14,0x14,0x14,0x14},{0,0x41,0x22,0x14,0x08},{0x02,0x01,0x51,0x09,0x06},
    {0x32,0x49,0x79,0x41,0x3E},{0x7E,0x11,0x11,0x11,0x7E},{0x7F,0x49,0x49,0x49,0x36},
    {0x3E,0x41,0x41,0x41,0x22},{0x7F,0x41,0x41,0x22,0x1C},{0x7F,0x49,0x49,0x49,0x41},
    {0x7F,0x09,0x09,0x01,0x01},{0x3E,0x41,0x49,0x49,0x7A},{0x7F,0x08,0x08,0x08,0x7F},
    {0,0x41,0x7F,0x41,0},{0x20,0x40,0x41,0x3F,0x01},{0x7F,0x08,0x14,0x22,0x41},
    {0x7F,0x40,0x40,0x40,0x40},{0x7F,0x02,0x04,0x02,0x7F},{0x7F,0x04,0x08,0x10,0x7F},
    {0x3E,0x41,0x41,0x41,0x3E},{0x7F,0x09,0x09,0x09,0x06},{0x3E,0x41,0x51,0x21,0x5E},
    {0x7F,0x09,0x19,0x29,0x46},{0x46,0x49,0x49,0x49,0x31},{0x01,0x01,0x7F,0x01,0x01},
    {0x3F,0x40,0x40,0x40,0x3F},{0x1F,0x20,0x40,0x20,0x1F},{0x3F,0x40,0x38,0x40,0x3F},
    {0x63,0x14,0x08,0x14,0x63},{0x07,0x08,0x70,0x08,0x07},{0x61,0x51,0x49,0x45,0x43},
};
static void ui_text(pixel_t* fb, unsigned p, int x, int y, const char* s, pixel_t c) {
    int cx = x;
    for (; *s; s++) {
        unsigned ch = (unsigned char)*s;
        if (ch < 32 || ch > 127) { cx += 6; continue; }
        const uint8_t* g = UI_FONT[ch - 32];
        for (int col = 0; col < 5; col++)
            for (int row = 0; row < 7; row++)
                if (g[col] & (1u << row)) {
                    int dx = cx + col, dy = y + row;
                    if (dx >= 0 && dx < RB_FB_W && dy >= 0 && dy < RB_FB_H) fb[dy * p + dx] = c;
                }
        cx += 6;
    }
}

/* ---------- persistence actions ---------------------------------------- */
static void rb_quick_save(struct mCore* core) {
    struct VFile* vf = VFileOpen(sStatePath, O_WRONLY | O_CREAT | O_TRUNC);
    if (!vf) return;
    mCoreSaveStateNamed(core, vf, 0);
    vf->close(vf);
}
static int rb_quick_load(struct mCore* core) {
    struct VFile* vf = VFileOpen(sStatePath, O_RDONLY);
    if (!vf) return 0;
    int ok = mCoreLoadStateNamed(core, vf, 0);
    vf->close(vf);
    return ok;
}

static void rb_pause(struct mCore* core) {
    size_t need = core->stateSize(core);
    if (need != sStateSize) {
        free(sStateBuf);
        sStateBuf = malloc(need);
        sStateSize = need;
    }
    if (sStateBuf) core->saveState(core, sStateBuf);
}
static void rb_resume(struct mCore* core) {
    if (sStateBuf) core->loadState(core, sStateBuf);
}

/* ---------- input ------------------------------------------------------ */
static int edge(uint32_t now, uint32_t prev, uint32_t bit) {
    return (now & bit) && !(prev & bit);
}

static int chord_down(uint16_t keys, const int* chord) {
    int a = chord[0], b = chord[1];
    uint32_t mask = 0;
    if (a >= 0 && a < 10) mask |= 1u << a;
    if (b >= 0 && b < 10) mask |= 1u << b;
    if (!mask) return 0;
    return (keys & mask) == mask;
}

void retrobilingual_process_input(struct mCore* core, uint16_t* keys,
                                  retro_input_state_t input)
{
    if (!core) return;
    const struct GBA* gba = core->board;
    if (!gba || gba->memory.romSize != RB_JP_ROM_SIZE ||
        gba->romCrc32 != RB_JP_ROM_CRC32) {
        sRomMatched = 0;
        return;
    }
    int first = !sRomMatched;
    sRomMatched = 1;
    if (first) {
        sCore = core;
        rb_paths();
        rb_config_load();
        rb_pack_load();
    }

    int x_pressed = input && input(0, RETRO_DEVICE_JOYPAD, 0, RETRO_DEVICE_ID_JOYPAD_X);
    int x_just = x_pressed && !sPrevX;
    uint16_t prev = (uint16_t)sPrevKeys;
    uint32_t now = *keys;

    if (sState == RB_BINDINGS) {
        static const int ids[] = {
            RETRO_DEVICE_ID_JOYPAD_A, RETRO_DEVICE_ID_JOYPAD_B,
            RETRO_DEVICE_ID_JOYPAD_L, RETRO_DEVICE_ID_JOYPAD_R,
            RETRO_DEVICE_ID_JOYPAD_SELECT, RETRO_DEVICE_ID_JOYPAD_START,
            RETRO_DEVICE_ID_JOYPAD_UP, RETRO_DEVICE_ID_JOYPAD_DOWN,
            RETRO_DEVICE_ID_JOYPAD_LEFT, RETRO_DEVICE_ID_JOYPAD_RIGHT,
        };
        if (x_just) { sState = RB_MENU; *keys = 0; goto done; }
        if (!sBindingCapture) {
            if (edge(now, prev, RB_KEY_DOWN)) sBindingCursor = (sBindingCursor + 1) % ACT_COUNT;
            if (edge(now, prev, RB_KEY_UP)) sBindingCursor = (sBindingCursor + ACT_COUNT - 1) % ACT_COUNT;
            if (edge(now, prev, RB_KEY_A)) { sBindingCapture = 1; sBindingCount = 0; }
        } else {
            int any = 0;
            for (size_t i = 0; i < sizeof(ids)/sizeof(ids[0]); i++) {
                int down = input && input(0, RETRO_DEVICE_JOYPAD, 0, ids[i]);
                if (down) {
                    any = 1;
                    if (sBindingCount < 2 &&
                        (sBindingCount == 0 || sBindingPending[sBindingCount - 1] != ids[i])) {
                        sBindingPending[sBindingCount++] = ids[i];
                    }
                }
            }
            if (!any && sBindingCount > 0) {
                sCfg.chord[sBindingCursor][0] = sBindingPending[0];
                sCfg.chord[sBindingCursor][1] = sBindingCount > 1 ? sBindingPending[1] : -1;
                rb_config_save();
                sBindingCapture = 0;
            }
        }
        *keys = 0;
        goto done;
    }

    if (sState == RB_MENU) {
        if (edge(now, prev, RB_KEY_DOWN)) sMenuCursor = (sMenuCursor + 1) % 5;
        if (edge(now, prev, RB_KEY_UP)) sMenuCursor = (sMenuCursor + 4) % 5;
        if (x_just || edge(now, prev, RB_KEY_B)) {
            rb_resume(core);
            sState = RB_GAME;
        } else if (edge(now, prev, RB_KEY_A)) {
            switch (sMenuCursor) {
            case 0: rb_resume(core); sState = RB_GAME; break;
            case 1: rb_quick_save(core); rb_resume(core); sState = RB_GAME; break;
            case 2: rb_quick_load(core); sState = RB_GAME; break;
            case 3: sCfg.enabled = !sCfg.enabled; rb_config_save(); break;
            case 4: sState = RB_BINDINGS; sBindingCursor = 0; sBindingCapture = 0; break;
            default: break;
            }
        }
        *keys = 0;
        goto done;
    }

    if (sState == RB_SUBTITLE) {
        if (x_just || edge(now, prev, RB_KEY_B) || chord_down((uint16_t)now, sCfg.chord[ACT_SUBTITLE])) {
            rb_resume(core);
            sState = RB_GAME;
        }
        *keys = 0;
        goto done;
    }

    /* RB_GAME */
    if (x_just) {
        rb_pause(core);
        sState = RB_MENU;
        sMenuCursor = 0;
    } else {
        for (int a = 0; a < ACT_COUNT; a++) {
            int c = chord_down((uint16_t)now, sCfg.chord[a]);
            if (c && !sPrevAction[a]) {
                if (a == ACT_SAVE) rb_quick_save(core);
                else if (a == ACT_LOAD) rb_quick_load(core);
                else if (a == ACT_SUBTITLE && sCfg.enabled) {
                    rb_dialogue_read(gba);
                    if (sDlgActive) {
                        rb_pause(core);
                        sState = RB_SUBTITLE;
                    }
                }
            }
            sPrevAction[a] = c;
        }
    }

    if (sState != RB_GAME) *keys = 0;
    else rb_dialogue_read(gba);

done:
    sPrevKeys = now;
    sPrevX = x_pressed;
}

int retrobilingual_should_run_frame(struct mCore* core) {
    (void)core;
    return sState == RB_GAME;
}

void retrobilingual_draw(struct mCore* core, void* pixels, unsigned width,
                         unsigned height, unsigned pitch)
{
    if (!sRomMatched || width != RB_FB_W || height != RB_FB_H) return;
    pixel_t* fb = (pixel_t*)pixels;
    unsigned p = PITCH_PIXELS(pitch);

    if (sState == RB_SUBTITLE) {
        int by = RB_FB_H - 34, bh = 34;
        for (int r = by; r < by + bh; r++)
            for (int c = 0; c < RB_FB_W; c++)
                fb[r * p + c] = shade(fb[r * p + c]);
        for (int c = 0; c < RB_FB_W; c++) fb[by * p + c] = 0x7BEF;
        if (sDlgGlyphCount) {
            draw_sequence(fb, p, 4, by + 4, RB_FB_W - 8, sDlgGlyphStart, sDlgGlyphCount);
        } else {
            RBEntry* notice = NULL;
            if (rb_find_entry(0xFFFF, 0, &notice)) {
                draw_sequence(fb, p, 4, by + 4, RB_FB_W - 8,
                              notice->first_glyph, notice->glyph_count);
            } else {
                ui_text(fb, p, 8, by + 12, "NO TRANSLATION", 0xFFFF);
            }
        }
        ui_text(fb, p, RB_FB_W - 50, by + 12, "X:CLOSE", 0xAD55);
    } else if (sState == RB_MENU || sState == RB_BINDINGS) {
        int mw = 180, mh = 5 * 16 + 16;
        int mx = (RB_FB_W - mw) / 2, my = 14;
        rect(fb, p, mx - 2, my - 2, mw + 4, mh + 4, 0x7BEF);
        rect(fb, p, mx, my, mw, mh, 0x0000);
        if (sState == RB_MENU) {
            static const char* labels[5] = {
                "RESUME", "QUICK SAVE", "QUICK LOAD", "SUBTITLES", "HOTKEYS"
            };
            for (int i = 0; i < 5; i++) {
                int iy = my + 8 + i * 16;
                if (i == sMenuCursor) rect(fb, p, mx + 2, iy - 2, mw - 4, 12, 0x2965);
                ui_text(fb, p, mx + 8, iy, labels[i], 0xFFFF);
                if (i == 3) ui_text(fb, p, mx + mw - 28, iy, sCfg.enabled ? "ON" : "OFF", 0xFFE0);
            }
        } else {
            ui_text(fb, p, mx + 8, my + 8, "BIND ACTION (A=CAPTURE)", 0xFFFF);
            for (int a = 0; a < ACT_COUNT; a++) {
                int iy = my + 26 + a * 20;
                if (a == sBindingCursor) rect(fb, p, mx + 2, iy - 2, mw - 4, 12, 0x2965);
                ui_text(fb, p, mx + 8, iy, action_name(a), 0xFFFF);
                char buf[24];
                if (sBindingCapture && a == sBindingCursor) snprintf(buf, sizeof(buf), "PRESS...");
                else snprintf(buf, sizeof(buf), "%d,%d", sCfg.chord[a][0], sCfg.chord[a][1]);
                ui_text(fb, p, mx + 100, iy, buf, 0xAD55);
            }
        }
        ui_text(fb, p, 4, RB_FB_H - 10, "X:CLOSE  A:SELECT  B:BACK", 0xAD55);
    }
    (void)core;
}

#ifdef RB_HOST_TEST
int rb_test_pack_loaded(void) { return sPack.loaded; }
int rb_test_state(void) { return (int)sState; }
int rb_test_dialogue_page(void) { return (int)sDlgPage; }
int rb_test_glyphs(void) { return (int)sDlgGlyphCount; }
#endif
