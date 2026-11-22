#define _POSIX_C_SOURCE 200809L

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
#include "retrobilingual.h"

#ifdef RB_HOST_TEST
#include "host_stubs.h"
#define COLOR_16_BIT 1
#else
#include "libretro.h"

#include <mgba/core/core.h>
#include <mgba/gba/core.h>
#include <mgba/internal/gba/gba.h>
#include <mgba-util/vfs.h>
#endif

#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "adapters/adapter.h"

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
#define RB_MAX_ENTRIES 16384
#define RB_MAX_TEXT 512

typedef enum { RB_GAME, RB_MENU, RB_SUBTITLE, RB_BINDINGS, RB_CONFIRM_OVERWRITE } RBState;
typedef enum { ACT_SAVE, ACT_LOAD, ACT_SUBTITLE, ACT_COUNT } RBAction;
typedef enum { X_ACT_SUBTITLE = 0, X_ACT_SAVE = 1, X_ACT_LOAD = 2, X_ACT_COUNT } XAction;

typedef struct {
    uint32_t codepoint;
    uint16_t glyph_index;
} RBGlyph;

typedef struct {
    uint16_t text_id;
    uint8_t page;
    uint32_t first_glyph;
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
static int sInitialized;
static int sMenuCursor;
static int sBindingCursor;
static int64_t sAutoSaveLastTimeMs;
static int sAutoSaveClockStarted;
static int sBindingCapture;
static int sBindingPending[2];
static int sBindingCount;

#define RB_SLOT_COUNT 5

typedef enum {
    RB_POS_AUTO = 0,
    RB_POS_TOP = 1,
    RB_POS_CENTER = 2,
    RB_POS_BOTTOM = 3,
    RB_POS_COUNT = 4
} RBHudPos;

typedef struct {
    int enabled;
    int x_action;              /* 0: SUBTITLE, 1: SAVE, 2: LOAD */
    int slot;                  /* 0..4 (Slot 1..5) */
    int hud_pos;               /* 0: AUTO, 1: TOP, 2: CENTER, 3: BOTTOM */
    int visual_filter;         /* RBVisualFilter (0..7) */
    int autosave_interval;     /* index into sAutoSaveMinutes; 0 disables */
    int chord[ACT_COUNT][2];   /* RetroPad ids, -1 = unset */
} RBConfig;
static RBConfig sCfg = {
    .enabled = 1,
    .x_action = X_ACT_SUBTITLE,
    .slot = 0,
    .hud_pos = RB_POS_AUTO,
    .visual_filter = RB_FILTER_LCD_COLOR,
    .autosave_interval = 0,
    .chord = {
        { -1, -1 },            /* save */
        { -1, -1 },            /* load */
        { RETRO_DEVICE_ID_JOYPAD_L, RETRO_DEVICE_ID_JOYPAD_SELECT },
    },
};

static const int sAutoSaveMinutes[] = { 0, 1, 3, 5, 10, 15, 30 };
static const char* sAutoSaveNames[] = { "OFF", "1 MIN", "3 MIN", "5 MIN", "10 MIN", "15 MIN", "30 MIN" };

static const char* sFilterNames[RB_FILTER_COUNT] = {
    "OFF (RAW 3X)", "LCD GRID", "GBA COLOR", "LCD+COLOR", "CRT SCAN", "RGB STRIPE", "GB DMG", "GB POCKET"
};

#define RB_OUT_W 720
#define RB_OUT_H 480
static uint16_t sScaleFrame[RB_OUT_W * RB_OUT_H];
static uint16_t sGbaColorLut[65536];
static uint16_t sGbDmgLut[65536];
static uint16_t sGbPocketLut[65536];
static int sFilterLutsInitialized = 0;

static const float sGamma32[32] = {
    0.000000f, 0.000524f, 0.002406f, 0.005870f, 0.011054f, 0.018061f, 0.026973f, 0.037863f, 0.050793f, 0.065817f, 0.082986f, 0.102345f, 0.123938f, 0.147802f, 0.173975f, 0.202491f,
    0.233382f, 0.266681f, 0.302415f, 0.340614f, 0.381303f, 0.424509f, 0.470256f, 0.518568f, 0.569468f, 0.622977f, 0.679119f, 0.737912f, 0.799378f, 0.863535f, 0.930403f, 1.000000f
};
static const float sGamma64[64] = {
    0.000000f, 0.000110f, 0.000505f, 0.001233f, 0.002323f, 0.003795f, 0.005667f, 0.007955f, 0.010672f, 0.013829f, 0.017436f, 0.021504f, 0.026041f, 0.031055f, 0.036554f, 0.042545f,
    0.049036f, 0.056032f, 0.063540f, 0.071566f, 0.080116f, 0.089194f, 0.098805f, 0.108956f, 0.119651f, 0.130894f, 0.142690f, 0.155043f, 0.167957f, 0.181437f, 0.195487f, 0.210110f,
    0.225310f, 0.241091f, 0.257457f, 0.274410f, 0.291955f, 0.310095f, 0.328832f, 0.348171f, 0.368114f, 0.388665f, 0.409826f, 0.431600f, 0.453990f, 0.477000f, 0.500631f, 0.524887f,
    0.549771f, 0.575284f, 0.601430f, 0.628210f, 0.655629f, 0.683688f, 0.712389f, 0.741735f, 0.771728f, 0.802371f, 0.833667f, 0.865616f, 0.898222f, 0.931486f, 0.965412f, 1.000000f,
};
static const float sInvGamma256[256] = {
    0.000000f, 0.080560f, 0.110395f, 0.132737f, 0.151280f, 0.167429f, 0.181896f, 0.195098f, 0.207307f, 0.218708f, 0.229437f, 0.239595f, 0.249261f, 0.258497f, 0.267353f, 0.275870f,
    0.284083f, 0.292020f, 0.299707f, 0.307164f, 0.314409f, 0.321460f, 0.328330f, 0.335031f, 0.341576f, 0.347973f, 0.354232f, 0.360361f, 0.366368f, 0.372258f, 0.378039f, 0.383716f,
    0.389294f, 0.394777f, 0.400170f, 0.405478f, 0.410703f, 0.415850f, 0.420922f, 0.425921f, 0.430851f, 0.435714f, 0.440513f, 0.445250f, 0.449927f, 0.454547f, 0.459110f, 0.463620f,
    0.468078f, 0.472486f, 0.476845f, 0.481157f, 0.485422f, 0.489643f, 0.493821f, 0.497957f, 0.502052f, 0.506108f, 0.510125f, 0.514104f, 0.518046f, 0.521953f, 0.525825f, 0.529664f,
    0.533469f, 0.537242f, 0.540983f, 0.544693f, 0.548374f, 0.552025f, 0.555647f, 0.559241f, 0.562808f, 0.566348f, 0.569861f, 0.573348f, 0.576811f, 0.580248f, 0.583662f, 0.587051f,
    0.590417f, 0.593760f, 0.597081f, 0.600380f, 0.603657f, 0.606913f, 0.610149f, 0.613363f, 0.616558f, 0.619733f, 0.622888f, 0.626025f, 0.629142f, 0.632242f, 0.635323f, 0.638386f,
    0.641432f, 0.644460f, 0.647472f, 0.650467f, 0.653445f, 0.656407f, 0.659353f, 0.662284f, 0.665199f, 0.668099f, 0.670983f, 0.673853f, 0.676708f, 0.679549f, 0.682376f, 0.685189f,
    0.687988f, 0.690773f, 0.693545f, 0.696304f, 0.699050f, 0.701783f, 0.704503f, 0.707210f, 0.709905f, 0.712588f, 0.715259f, 0.717918f, 0.720565f, 0.723201f, 0.725825f, 0.728438f,
    0.731039f, 0.733630f, 0.736210f, 0.738778f, 0.741336f, 0.743884f, 0.746421f, 0.748948f, 0.751465f, 0.753971f, 0.756468f, 0.758954f, 0.761432f, 0.763899f, 0.766357f, 0.768805f,
    0.771244f, 0.773674f, 0.776095f, 0.778507f, 0.780909f, 0.783303f, 0.785689f, 0.788065f, 0.790433f, 0.792793f, 0.795144f, 0.797487f, 0.799821f, 0.802148f, 0.804466f, 0.806776f,
    0.809079f, 0.811373f, 0.813660f, 0.815939f, 0.818211f, 0.820475f, 0.822732f, 0.824981f, 0.827222f, 0.829457f, 0.831684f, 0.833905f, 0.836118f, 0.838324f, 0.840523f, 0.842715f,
    0.844901f, 0.847079f, 0.849251f, 0.851417f, 0.853576f, 0.855728f, 0.857874f, 0.860013f, 0.862146f, 0.864273f, 0.866393f, 0.868507f, 0.870615f, 0.872717f, 0.874813f, 0.876903f,
    0.878987f, 0.881065f, 0.883137f, 0.885203f, 0.887264f, 0.889318f, 0.891368f, 0.893411f, 0.895449f, 0.897481f, 0.899508f, 0.901529f, 0.903545f, 0.905556f, 0.907561f, 0.909561f,
    0.911556f, 0.913545f, 0.915529f, 0.917509f, 0.919483f, 0.921451f, 0.923415f, 0.925374f, 0.927328f, 0.929277f, 0.931221f, 0.933160f, 0.935095f, 0.937025f, 0.938949f, 0.940870f,
    0.942785f, 0.944696f, 0.946602f, 0.948504f, 0.950401f, 0.952293f, 0.954181f, 0.956064f, 0.957944f, 0.959818f, 0.961688f, 0.963554f, 0.965416f, 0.967273f, 0.969126f, 0.970975f,
    0.972820f, 0.974660f, 0.976496f, 0.978328f, 0.980156f, 0.981980f, 0.983800f, 0.985616f, 0.987428f, 0.989235f, 0.991039f, 0.992839f, 0.994635f, 0.996427f, 0.998216f, 1.000000f,
};

static void rb_init_filter_luts(void) {
    if (sFilterLutsInitialized) return;
    for (int c = 0; c < 65536; c++) {
        uint8_t r5 = (c >> 11) & 0x1F;
        uint8_t g6 = (c >> 5) & 0x3F;
        uint8_t b5 = c & 0x1F;

        /* GBA Color Correction (Hunterk / Pokefan531 matrix with gamma 2.2) */
        float r_lin = sGamma32[r5];
        float g_lin = sGamma64[g6];
        float b_lin = sGamma32[b5];

        float r_out = (0.82f * r_lin + 0.125f * g_lin + 0.195f * b_lin) * 0.94f;
        float g_out = (0.24f * r_lin + 0.665f * g_lin + 0.075f * b_lin) * 0.94f;
        float b_out = (-0.06f * r_lin + 0.21f * g_lin + 0.73f * b_lin) * 0.94f;

        if (r_out < 0.0f) r_out = 0.0f; else if (r_out > 1.0f) r_out = 1.0f;
        if (g_out < 0.0f) g_out = 0.0f; else if (g_out > 1.0f) g_out = 1.0f;
        if (b_out < 0.0f) b_out = 0.0f; else if (b_out > 1.0f) b_out = 1.0f;

        int ri = (int)(r_out * 255.0f); if (ri > 255) ri = 255;
        int gi = (int)(g_out * 255.0f); if (gi > 255) gi = 255;
        int bi = (int)(b_out * 255.0f); if (bi > 255) bi = 255;

        uint16_t ro = (uint16_t)(sInvGamma256[ri] * 31.0f + 0.5f);
        uint16_t go = (uint16_t)(sInvGamma256[gi] * 63.0f + 0.5f);
        uint16_t bo = (uint16_t)(sInvGamma256[bi] * 31.0f + 0.5f);
        sGbaColorLut[c] = (ro << 11) | (go << 5) | bo;

        /* Luminance for Game Boy palettes */
        float lum = 0.299f * (r5 / 31.0f) + 0.587f * (g6 / 63.0f) + 0.114f * (b5 / 31.0f);

        /* Game Boy DMG classic olive green */
        if (lum < 0.25f) sGbDmgLut[c] = 0x09C2;       /* dark olive */
        else if (lum < 0.50f) sGbDmgLut[c] = 0x3326;  /* olive */
        else if (lum < 0.75f) sGbDmgLut[c] = 0x8D62;  /* pea soup green */
        else sGbDmgLut[c] = 0x9DE2;                   /* light green */

        /* Game Boy Pocket grayscale */
        if (lum < 0.25f) sGbPocketLut[c] = 0x0000;
        else if (lum < 0.50f) sGbPocketLut[c] = 0x52AA;
        else if (lum < 0.75f) sGbPocketLut[c] = 0xA555;
        else sGbPocketLut[c] = 0xFFFF;
    }
    sFilterLutsInitialized = 1;
}

static uint32_t sPrevKeys;
static int sPrevX;
static int sPrevY;
static int sPrevAction[ACT_COUNT];

static struct mCore* sCore;
static void* sStateBuf;
static size_t sStateSize;
static char sConfigPath[512];
static char sPackPath[512];
static char sStatePath[512];
static const RBAdapter* sAdapter;
static uint8_t sRomSha256[32];
static int sRomIdentityReady;

static uint16_t sDlgTextId;
static uint8_t sDlgPage;
static int sDlgActive;
static int sDlgChanged;
static uint32_t sDlgGlyphStart;
static uint16_t sDlgGlyphCount;
static int sHudScroll;
#ifdef RB_HOST_TEST
static int sHudFirstVisibleLine;
#endif

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

static int rb_rom_identity(const struct GBA* gba) {
    if (!gba || !gba->memory.rom || !gba->memory.romSize) return 0;
    if (sRomIdentityReady) return sAdapter != NULL;
    /* mGBA pads memory.romSize up to the cartridge address-space mask; the
     * real file length is pristineRomSize. Hash and gate on the file length,
     * otherwise non-power-of-two ROMs (Golden Sun is 0x8D4000/0xB0E9B0)
     * can never match a pack. */
    size_t rom_size = gba->pristineRomSize ? gba->pristineRomSize : gba->memory.romSize;
    Sha256 sha;
    sha_init(&sha);
    sha_update(&sha, gba->memory.rom, rom_size);
    sha_final(&sha, sRomSha256);
    sAdapter = rb_adapter_match((uint32_t)rom_size, sRomSha256);
    sRomIdentityReady = 1;
    if (sAdapter && sAdapter->reset) sAdapter->reset();
    return sAdapter != NULL;
}

/* ---------- config and pack paths -------------------------------------- */
static char sRomPath[1024] = {0};

void retrobilingual_set_rom_path(const char* path) {
    if (path && path[0]) {
        strncpy(sRomPath, path, sizeof(sRomPath) - 1);
        sRomPath[sizeof(sRomPath) - 1] = '\0';
    } else {
        sRomPath[0] = '\0';
    }
}

static int file_exists(const char* path) {
    if (!path || !path[0]) return 0;
    FILE* f = fopen(path, "rb");
    if (f) {
        fclose(f);
        return 1;
    }
    return 0;
}

static void rb_paths(void) {
    const char* dir = getenv("RETROBILINGUAL_DIR");
    if (!dir) dir = "/storage/.config/pocketjs";
    snprintf(sConfigPath, sizeof(sConfigPath), "%s/retrobilingual.conf", dir);
    snprintf(sStatePath, sizeof(sStatePath), "%s/retrobilingual-quick.state", dir);

    sPackPath[0] = '\0';

    /* 1. First priority: Check for companion pack next to the loaded ROM */
    if (sRomPath[0]) {
        char stem[1024];
        strncpy(stem, sRomPath, sizeof(stem) - 1);
        stem[sizeof(stem) - 1] = '\0';
        char* dot = strrchr(stem, '.');
        if (dot && dot > strrchr(stem, '/')) *dot = '\0';

        char cand[1280];
        /* Candidate 1a: <rom_stem>.ja-zh.pack */
        snprintf(cand, sizeof(cand), "%s.ja-zh.pack", stem);
        if (file_exists(cand)) {
            strncpy(sPackPath, cand, sizeof(sPackPath) - 1);
        }
        /* Candidate 1b: <rom_stem>.pack */
        if (!sPackPath[0]) {
            snprintf(cand, sizeof(cand), "%s.pack", stem);
            if (file_exists(cand)) {
                strncpy(sPackPath, cand, sizeof(sPackPath) - 1);
            }
        }
        /* Candidate 1c: <rom_dir>/retrobilingual.pack */
        if (!sPackPath[0]) {
            char dir_buf[1024];
            strncpy(dir_buf, sRomPath, sizeof(dir_buf) - 1);
            dir_buf[sizeof(dir_buf) - 1] = '\0';
            char* slash = strrchr(dir_buf, '/');
            if (slash) {
                *slash = '\0';
                snprintf(cand, sizeof(cand), "%s/retrobilingual.pack", dir_buf);
                if (file_exists(cand)) {
                    strncpy(sPackPath, cand, sizeof(sPackPath) - 1);
                }
            }
        }
    }

    /* 2. Global fallback to RETROBILINGUAL_DIR or /storage/.config/pocketjs/retrobilingual.pack */
    if (!sPackPath[0]) {
        snprintf(sPackPath, sizeof(sPackPath), "%s/retrobilingual.pack", dir);
    }
}

static void rb_config_load(void) {
    rb_paths();
    FILE* f = fopen(sConfigPath, "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof(line), f)) {
        int a = -1, b = -1, v = -1;
        if (sscanf(line, "x_action=%d", &v) == 1) {
            if (v >= 0 && v < X_ACT_COUNT) sCfg.x_action = v;
        }
        else if (sscanf(line, "slot=%d", &v) == 1) {
            if (v >= 0 && v < RB_SLOT_COUNT) sCfg.slot = v;
        }
        else if (sscanf(line, "hud_pos=%d", &v) == 1) {
            if (v >= 0 && v < RB_POS_COUNT) sCfg.hud_pos = v;
        }
        else if (sscanf(line, "visual_filter=%d", &v) == 1) {
            if (v >= 0 && v < RB_FILTER_COUNT) sCfg.visual_filter = v;
        }
        else if (sscanf(line, "autosave_interval=%d", &v) == 1) {
            if (v >= 0 && v < 7) sCfg.autosave_interval = v;
        }
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
    fprintf(f, "x_action=%d\n", sCfg.x_action);
    fprintf(f, "slot=%d\n", sCfg.slot);
    fprintf(f, "hud_pos=%d\n", sCfg.hud_pos);
    fprintf(f, "visual_filter=%d\n", sCfg.visual_filter);
    fprintf(f, "autosave_interval=%d\n", sCfg.autosave_interval);
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
        const struct GBA* gba = sCore ? sCore->board : NULL;
        if (!rb_rom_identity(gba) || memcmp(sRomSha256, data + off, 32) != 0) break;

        off += 32;

        sPack.glyph_bytes = ((size_t)sPack.glyph_w * sPack.glyph_h + 7) / 8;
        size_t glyph_table = (size_t)sPack.glyph_count * (4 + sPack.glyph_bytes);
        size_t entry_table = (size_t)sPack.entry_count * 12;
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
            sPack.entries[i].first_glyph = rd32(data + off + 4);
            sPack.entries[i].glyph_count = (uint16_t)rd32(data + off + 8);
            off += 12;
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

static int rb_find_dialogue_entry(uint16_t text_id, uint8_t page, RBEntry** out) {
    if (rb_find_entry(text_id, page, out)) return 1;

    /* Adapters that advance page on an A press can briefly overshoot the
     * built pages while the next message loads.  Only those games clamp down
     * to the closest earlier page; otherwise a missing page is a genuine gap
     * and must fall through to the no-translation path. */
    if (sAdapter && sAdapter->page_slack) {
        for (int earlier = (int)page - 1; earlier >= 0; earlier--)
            if (rb_find_entry(text_id, (uint8_t)earlier, out)) return 1;
    }

    /* A long translation which only has page 0 is scrolled in the HUD, not
     * split into invented pack pages.  It may therefore serve later game
     * dialogue pages.  Once an id has any real non-zero pack page, however,
     * a missing page is a genuine gap and must fall through to FFFF. */
    int has_page_zero = 0;
    int has_nonzero_page = 0;
    for (uint32_t i = 0; i < sPack.entry_count; i++) {
        RBEntry* entry = &sPack.entries[i];
        if (entry->text_id != text_id) continue;
        if (entry->page == 0) has_page_zero = 1;
        else has_nonzero_page = 1;
    }
    if (has_page_zero && !has_nonzero_page)
        return rb_find_entry(text_id, 0, out);
    return 0;
}
static void rb_dialogue_read(struct mCore* core, uint16_t keys) {
    if (!sPack.loaded || !core || !sAdapter) {
        if (sDlgActive) sDlgChanged = 1;
        sDlgActive = 0;
        sDlgGlyphCount = 0;
        return;
    }
    uint16_t textId;
    uint8_t page;
    if (!sAdapter->read_dialogue(core, keys, &textId, &page)) {
        if (sDlgActive) sDlgChanged = 1;
        sDlgActive = 0;
        sDlgGlyphCount = 0;
        return;
    }
    if (!sDlgActive || textId != sDlgTextId || page != sDlgPage) {
        sDlgTextId = textId;
        sDlgPage = page;
        sDlgChanged = 1;
        sHudScroll = 0;
    }
    sDlgActive = 1;

    RBEntry* e = NULL;
    if (rb_find_dialogue_entry(sDlgTextId, sDlgPage, &e)) {
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

static void glyph_color(pixel_t* fb, unsigned p, int x, int y, uint16_t index, pixel_t c) {
    if (!sPack.loaded || index >= sPack.glyph_count) return;
    int gw = sPack.glyph_w, gh = sPack.glyph_h;
    const uint8_t* bmp = sPack.bits + (size_t)index * sPack.glyph_bytes;
    for (int gy = 0; gy < gh; gy++) {
        int dy = y + gy;
        if (dy < 0 || dy >= RB_FB_H) continue;
        for (int gx = 0; gx < gw; gx++) {
            int bit = gy * gw + gx;
            if (!(bmp[bit >> 3] & (0x80 >> (bit & 7)))) continue;
            int dx = x + gx;
            if (dx >= 0 && dx < RB_FB_W) fb[dy * p + dx] = c;
        }
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
static char sToastMsg[64];
static int sToastTicks;
static int sVolumeKnown;
static int sVolumeLevel;
static int sVolumeSequenceKnown;
static unsigned long sVolumeSequence;
static int sVolumePollFrames;
static int sVolumeTicks;

static void poll_volume_level(void) {
    if (sVolumePollFrames > 0) {
        sVolumePollFrames--;
        return;
    }
    sVolumePollFrames = 5;

    const char* event_path = getenv("BASEOS_VOLUME_EVENT");
    if (!event_path || !*event_path) event_path = "/run/baseos-volume.sequence";
    unsigned long sequence = 0;
    FILE* event_file = fopen(event_path, "r");
    if (event_file) {
        char event_line[24];
        if (fgets(event_line, sizeof(event_line), event_file)) {
            char* event_end = NULL;
            unsigned long parsed = strtoul(event_line, &event_end, 10);
            if (event_end != event_line) sequence = parsed;
        }
        fclose(event_file);
    }
    int event_changed = 0;
    if (!sVolumeSequenceKnown) {
        sVolumeSequenceKnown = 1;
        sVolumeSequence = sequence;
    } else if (sVolumeSequence != sequence) {
        sVolumeSequence = sequence;
        event_changed = 1;
    }

    const char* path = getenv("BASEOS_VOLUME_STATE");
    if (!path || !*path) path = "/run/baseos-volume.percent";
    FILE* f = fopen(path, "r");
    if (!f) return;
    char line[16];
    if (!fgets(line, sizeof(line), f)) {
        fclose(f);
        return;
    }
    fclose(f);

    char* end = NULL;
    long value = strtol(line, &end, 10);
    if (end == line || value < 0 || value > 100) return;
    if (!sVolumeKnown) {
        sVolumeKnown = 1;
        sVolumeLevel = (int)value;
        if (event_changed) sVolumeTicks = 45;
        return;
    }
    int level_changed = sVolumeLevel != (int)value;
    if (level_changed) sVolumeLevel = (int)value;
    if (event_changed || level_changed) sVolumeTicks = 45;
}

static void set_toast(const char* msg) {
    snprintf(sToastMsg, sizeof(sToastMsg), "%s", msg);
    sToastTicks = 120;
}

static void rb_state_path(int slot, char* out, size_t out_sz) {
    const char* dir = getenv("RETROBILINGUAL_DIR");
    if (!dir) dir = "/storage/.config/pocketjs";
    snprintf(out, out_sz, "%s/retrobilingual-slot%d.state", dir, slot + 1);
}

static int rb_slot_has_data(int slot) {
    char path[512];
    rb_state_path(slot, path, sizeof(path));
    if (access(path, R_OK) == 0) return 1;
    if (slot == 0) {
        const char* dir = getenv("RETROBILINGUAL_DIR");
        if (!dir) dir = "/storage/.config/pocketjs";
        snprintf(path, sizeof(path), "%s/retrobilingual-quick.state", dir);
        if (access(path, R_OK) == 0) return 1;
    }
    return 0;
}

typedef struct {
    int valid;
    char time_str[16];
    char area_name[24];
    int hearts;
    int rupees;
} RBSlotInfo;

static const char* const sLocationNames[] = {
    "UNKNOWN",          "MT. CRENEL",       "CRENEL BASE",      "CASTOR WILDS",
    "WIND RUINS",       "ROYAL VALLEY",     "TRILBY HIGHLANDS", "WESTERN WOOD",
    "CASTLE GARDEN",    "NORTH HYRULE",     "HYRULE TOWN",      "SOUTH HYRULE",
    "VEIL SPRINGS",     "VEIL FALLS",       "LON LON RANCH",    "EASTERN HILLS",
    "CLOUD TOPS",       "LAKE HYLIA",       "MINISH WOODS",     "SANCTUARY",
    "MINISH VILLAGE",   "MELARI MINES",     "HYRULE CASTLE",    "DEEPWOOD SHRINE",
    "DEEPWOOD SHRINE",  "CAVE OF FLAMES",   "FORTRESS OF WINDS","DROPLET TEMPLE",
    "PALACE OF WINDS",  "DARK CASTLE",      "ROYAL CRYPT",      "BIGGORON DUNGEON"
};

static void rb_get_slot_info(int slot, RBSlotInfo* info) {
    if (!info) return;
    memset(info, 0, sizeof(*info));

    char path[512];
    rb_state_path(slot, path, sizeof(path));
    struct stat st;
    if (stat(path, &st) != 0) {
        if (slot == 0) {
            const char* dir = getenv("RETROBILINGUAL_DIR");
            if (!dir) dir = "/storage/.config/pocketjs";
            snprintf(path, sizeof(path), "%s/retrobilingual-quick.state", dir);
            if (stat(path, &st) != 0) return;
        } else {
            return;
        }
    }

    info->valid = 1;
    struct tm* tm_info = localtime(&st.st_mtime);
    if (tm_info) {
        strftime(info->time_str, sizeof(info->time_str), "%m/%d %H:%M", tm_info);
    }

    /* If this is a real GBA serialized state (mGBA is 0x61000 bytes), read stats and area */
    if (st.st_size >= 0x61000) {
        FILE* f = fopen(path, "rb");
        if (f) {
            uint8_t max_hp = 0;
            uint16_t rup = 0;
            uint8_t loc = 0;
            if (fseek(f, 0x23AEB, SEEK_SET) == 0 && fread(&max_hp, 1, 1, f) == 1) {
                info->hearts = max_hp / 8;
            }
            if (fseek(f, 0x23B00, SEEK_SET) == 0) {
                uint8_t b[2];
                if (fread(b, 1, 2, f) == 2) {
                    rup = (uint16_t)(b[0] | (b[1] << 8));
                    info->rupees = (int)rup;
                }
            }
            if (fseek(f, 0x54A91, SEEK_SET) == 0 && fread(&loc, 1, 1, f) == 1) {
                if (loc < (sizeof(sLocationNames) / sizeof(sLocationNames[0]))) {
                    snprintf(info->area_name, sizeof(info->area_name), "%s", sLocationNames[loc]);
                } else {
                    snprintf(info->area_name, sizeof(info->area_name), "AREA %d", loc);
                }
            }
            fclose(f);
        }
    }
}

static int rb_state_save_path(struct mCore* core, const char* path) {
    if (!core || !core->stateSize || !core->saveState) return 0;
    size_t size = core->stateSize(core);
    if (!size) return 0;
    void* buf = malloc(size);
    if (!buf) return 0;
    if (!core->saveState(core, buf)) {
        free(buf);
        return 0;
    }
    FILE* f = fopen(path, "wb");
    if (!f) {
        free(buf);
        return 0;
    }
    size_t written = fwrite(buf, 1, size, f);
    fclose(f);
    free(buf);
    return written == size;
}

static int rb_slot_save(struct mCore* core, int slot) {
    char path[512];
    rb_state_path(slot, path, sizeof(path));
    return rb_state_save_path(core, path);
}

static void rb_auto_state_path(char* out, size_t out_sz) {
    const char* dir = getenv("RETROBILINGUAL_DIR");
    if (!dir) dir = "/storage/.config/pocketjs";
    snprintf(out, out_sz, "%s/retrobilingual-autosave.state", dir);
}


static int rb_slot_load(struct mCore* core, int slot) {
    if (!core || !core->stateSize || !core->loadState) return 0;
    char path[512];
    rb_state_path(slot, path, sizeof(path));
    FILE* f = fopen(path, "rb");
    if (!f) {
        if (slot == 0) {
            const char* dir = getenv("RETROBILINGUAL_DIR");
            if (!dir) dir = "/storage/.config/pocketjs";
            snprintf(path, sizeof(path), "%s/retrobilingual-quick.state", dir);
            f = fopen(path, "rb");
        }
        if (!f) return -1;
    }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    size_t expected = core->stateSize(core);
    if (sz <= 0 || (size_t)sz != expected) {
        fclose(f);
        return 0;
    }
    void* buf = malloc(expected);
    if (!buf) {
        fclose(f);
        return 0;
    }
    if (fread(buf, 1, expected, f) != expected) {
        free(buf);
        fclose(f);
        return 0;
    }
    fclose(f);
    int ok = core->loadState(core, buf);
    if (ok) {
        if (sStateSize != expected) {
            free(sStateBuf);
            sStateBuf = malloc(expected);
            sStateSize = expected;
        }
        if (sStateBuf) memcpy(sStateBuf, buf, expected);
    }
    free(buf);
    return ok ? 1 : 0;
}

static void do_save(struct mCore* core) {
    int ok = rb_slot_save(core, sCfg.slot);
    char buf[48];
    if (ok) snprintf(buf, sizeof(buf), "SAVED TO SLOT %d", sCfg.slot + 1);
    else snprintf(buf, sizeof(buf), "SAVE FAILED!");
    set_toast(buf);
}

static void do_load(struct mCore* core) {
    int res = rb_slot_load(core, sCfg.slot);
    char buf[48];
    if (res == 1) snprintf(buf, sizeof(buf), "LOADED SLOT %d", sCfg.slot + 1);
    else if (res == -1) snprintf(buf, sizeof(buf), "SLOT %d IS EMPTY", sCfg.slot + 1);
    else snprintf(buf, sizeof(buf), "LOAD FAILED!");
    set_toast(buf);
}

static int64_t rb_monotonic_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void rb_auto_save_tick_at(struct mCore* core, int64_t now_ms) {
    if (!sAutoSaveClockStarted) {
        sAutoSaveLastTimeMs = now_ms;
        sAutoSaveClockStarted = 1;
    }
    int minutes = sAutoSaveMinutes[sCfg.autosave_interval];
    if (minutes == 0) {
        sAutoSaveLastTimeMs = now_ms;
        return;
    }
    if (now_ms < sAutoSaveLastTimeMs || now_ms - sAutoSaveLastTimeMs < (int64_t)minutes * 60000) return;

    char path[512];
    rb_auto_state_path(path, sizeof(path));
    int ok = rb_state_save_path(core, path);
    sAutoSaveLastTimeMs = now_ms;
    set_toast(ok ? "AUTO SAVED" : "AUTO SAVE FAILED");
}

static void rb_auto_save_tick(struct mCore* core) {
    rb_auto_save_tick_at(core, rb_monotonic_ms());
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
    sAutoSaveLastTimeMs = rb_monotonic_ms();
    sAutoSaveClockStarted = 1;
}

static void request_save(struct mCore* core) {
    if (rb_slot_has_data(sCfg.slot)) {
        rb_pause(core);
        sState = RB_CONFIRM_OVERWRITE;
    } else {
        do_save(core);
        rb_resume(core);
        sState = RB_GAME;
    }
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
    if (!gba) return;
    int first = !sInitialized;
    sInitialized = 1;
    if (first) {
        sCore = core;
        rb_paths();
        rb_config_load();
        rb_rom_identity(gba);
        rb_pack_load();
    }
    poll_volume_level();

    int y_pressed = input && input(0, RETRO_DEVICE_JOYPAD, 0, RETRO_DEVICE_ID_JOYPAD_Y);
    int y_just = y_pressed && !sPrevY;
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
        if (y_just || x_just || edge(now, prev, RB_KEY_B)) { sState = RB_MENU; *keys = 0; goto done; }
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
        if (edge(now, prev, RB_KEY_DOWN)) sMenuCursor = (sMenuCursor + 1) % 6;
        if (edge(now, prev, RB_KEY_UP)) sMenuCursor = (sMenuCursor + 5) % 6;
        if (sMenuCursor == 0 || sMenuCursor == 1) {
            if (edge(now, prev, RB_KEY_RIGHT)) { sCfg.slot = (sCfg.slot + 1) % RB_SLOT_COUNT; rb_config_save(); }
            if (edge(now, prev, RB_KEY_LEFT)) { sCfg.slot = (sCfg.slot + RB_SLOT_COUNT - 1) % RB_SLOT_COUNT; rb_config_save(); }
        } else if (sMenuCursor == 2) {
            if (edge(now, prev, RB_KEY_RIGHT)) { sCfg.x_action = (sCfg.x_action + 1) % X_ACT_COUNT; rb_config_save(); }
            if (edge(now, prev, RB_KEY_LEFT)) { sCfg.x_action = (sCfg.x_action + X_ACT_COUNT - 1) % X_ACT_COUNT; rb_config_save(); }
        } else if (sMenuCursor == 3) {
            if (edge(now, prev, RB_KEY_RIGHT)) { sCfg.hud_pos = (sCfg.hud_pos + 1) % RB_POS_COUNT; rb_config_save(); }
            if (edge(now, prev, RB_KEY_LEFT)) { sCfg.hud_pos = (sCfg.hud_pos + RB_POS_COUNT - 1) % RB_POS_COUNT; rb_config_save(); }
        } else if (sMenuCursor == 4) {
            if (edge(now, prev, RB_KEY_RIGHT)) { sCfg.visual_filter = (sCfg.visual_filter + 1) % RB_FILTER_COUNT; rb_config_save(); set_toast(sFilterNames[sCfg.visual_filter]); }
            if (edge(now, prev, RB_KEY_LEFT)) { sCfg.visual_filter = (sCfg.visual_filter + RB_FILTER_COUNT - 1) % RB_FILTER_COUNT; rb_config_save(); set_toast(sFilterNames[sCfg.visual_filter]); }
        } else if (sMenuCursor == 5) {
            if (edge(now, prev, RB_KEY_RIGHT)) sCfg.autosave_interval = (sCfg.autosave_interval + 1) % 7;
            if (edge(now, prev, RB_KEY_LEFT)) sCfg.autosave_interval = (sCfg.autosave_interval + 6) % 7;
            if (edge(now, prev, RB_KEY_RIGHT) || edge(now, prev, RB_KEY_LEFT)) {
                sAutoSaveLastTimeMs = rb_monotonic_ms();
                sAutoSaveClockStarted = 1;
                rb_config_save();
            }
        }

        if (y_just || edge(now, prev, RB_KEY_B)) {
            rb_resume(core);
            sState = RB_GAME;
        } else if (edge(now, prev, RB_KEY_A)) {
            switch (sMenuCursor) {
            case 0: request_save(core); break;
            case 1:
                do_load(core);
                sAutoSaveLastTimeMs = rb_monotonic_ms();
                sAutoSaveClockStarted = 1;
                sState = RB_GAME;
                break;
            case 2: sCfg.x_action = (sCfg.x_action + 1) % X_ACT_COUNT; rb_config_save(); break;
            case 3: sCfg.hud_pos = (sCfg.hud_pos + 1) % RB_POS_COUNT; rb_config_save(); break;
            case 4: sCfg.visual_filter = (sCfg.visual_filter + 1) % RB_FILTER_COUNT; rb_config_save(); set_toast(sFilterNames[sCfg.visual_filter]); break;
            case 5:
                sCfg.autosave_interval = (sCfg.autosave_interval + 1) % 7;
                sAutoSaveLastTimeMs = rb_monotonic_ms();
                sAutoSaveClockStarted = 1;
                rb_config_save();
                break;
            default: break;
            }
        }
        *keys = 0;
        goto done;
    }

    if (sState == RB_CONFIRM_OVERWRITE) {
        if (edge(now, prev, RB_KEY_A)) {
            do_save(core);
            rb_resume(core);
            sState = RB_GAME;
        } else if (y_just || edge(now, prev, RB_KEY_B)) {
            set_toast("SAVE CANCELLED");
            rb_resume(core);
            sState = RB_GAME;
        }
        *keys = 0;
        goto done;
    }

    if (sState == RB_SUBTITLE) {
        if (x_just || y_just || edge(now, prev, RB_KEY_B) || chord_down((uint16_t)now, sCfg.chord[ACT_SUBTITLE])) {
            rb_resume(core);
            sState = RB_GAME;
        } else if (edge(now, prev, RB_KEY_RIGHT)) {
            sHudScroll += 2;
        } else if (edge(now, prev, RB_KEY_LEFT) && sHudScroll >= 2) {
            sHudScroll -= 2;
        }
        *keys = 0;
        goto done;
    }

    /* RB_GAME */
    rb_auto_save_tick(core);
    if (y_just) {
        rb_pause(core);
        sState = RB_MENU;
        sMenuCursor = 0;
    } else if (x_just) {
        if (sCfg.x_action == X_ACT_SUBTITLE) {
            rb_dialogue_read(core, 0);
            sHudScroll = 0;
            rb_pause(core);
            sState = RB_SUBTITLE;
        } else if (sCfg.x_action == X_ACT_SAVE) {
            request_save(core);
        } else if (sCfg.x_action == X_ACT_LOAD) {
            do_load(core);
        }
    } else {
        for (int a = 0; a < ACT_COUNT; a++) {
            int c = chord_down((uint16_t)now, sCfg.chord[a]);
            if (c && !sPrevAction[a]) {
                if (a == ACT_SAVE) request_save(core);
                else if (a == ACT_LOAD) do_load(core);
                else if (a == ACT_SUBTITLE) {
                    rb_dialogue_read(core, 0);
                    sHudScroll = 0;
                    rb_pause(core);
                    sState = RB_SUBTITLE;
                }
            }
            sPrevAction[a] = c;
        }
    }

    if (sState != RB_GAME) *keys = 0;
    else rb_dialogue_read(core, (uint16_t)now);

done:
    sPrevKeys = now;
    sPrevX = x_pressed;
    sPrevY = y_pressed;
}

int retrobilingual_should_run_frame(struct mCore* core) {
    (void)core;
    return sState == RB_GAME;
}

static pixel_t sCleanFrame[RB_FB_H * 256];
static int sHasCleanFrame = 0;

void retrobilingual_draw(struct mCore* core, void* pixels, unsigned width,
                         unsigned height, unsigned pitch)
{
    if (!sInitialized || width != RB_FB_W || height != RB_FB_H) return;
    pixel_t* fb = (pixel_t*)pixels;
    unsigned p = PITCH_PIXELS(pitch);
    size_t frame_bytes = height * pitch;

    if (sState == RB_GAME || !sHasCleanFrame) {
        if (frame_bytes <= sizeof(sCleanFrame)) {
            memcpy(sCleanFrame, pixels, frame_bytes);
            sHasCleanFrame = 1;
        }
    } else {
        if (sHasCleanFrame && frame_bytes <= sizeof(sCleanFrame)) {
            memcpy(pixels, sCleanFrame, frame_bytes);
        }
    }

    if (sState == RB_SUBTITLE) {
        /* Clean non-intrusive floating HUD: no full screen shading, no modal frame, no title/footer */
        uint32_t start = sDlgGlyphStart;
        uint16_t total_glyphs = sDlgGlyphCount;
        int is_notice = 0;
        if (!total_glyphs) {
            RBEntry* notice = NULL;
            if (rb_find_entry(0xFFFF, 0, &notice)) {
                start = notice->first_glyph;
                total_glyphs = notice->glyph_count;
                is_notice = 1;
            }
        }

        if (total_glyphs && sPack.loaded) {
            int line_starts[RB_MAX_TEXT + 1];
            int line_counts[RB_MAX_TEXT + 1];
            int line_n = 0;
            int cur_start = 0;
            int cur_count = 0;

            for (uint16_t i = 0; i < total_glyphs; i++) {
                uint16_t idx = sPack.indices[start + i];
                if (idx == 0xFFFF) {
                    if (line_n < RB_MAX_TEXT + 1) {
                        line_starts[line_n] = cur_start;
                        line_counts[line_n] = cur_count;
                        line_n++;
                    }
                    cur_start = i + 1;
                    cur_count = 0;
                } else {
                    cur_count++;
                    /* Auto soft-wrap if single line reaches 15 glyphs */
                    if (cur_count >= 15 && i + 1 < total_glyphs && sPack.indices[start + i + 1] != 0xFFFF) {
                        if (line_n < RB_MAX_TEXT + 1) {
                            line_starts[line_n] = cur_start;
                            line_counts[line_n] = cur_count;
                            line_n++;
                        }
                        cur_start = i + 1;
                        cur_count = 0;
                    }
                }
            }
            if (line_n < RB_MAX_TEXT + 1 && cur_count > 0) {
                line_starts[line_n] = cur_start;
                line_counts[line_n] = cur_count;
                line_n++;
            }
            if (line_n == 0) line_n = 1;
            if (sHudScroll >= line_n) sHudScroll = line_n - 1;
            if (sHudScroll < 0) sHudScroll = 0;
            int visible_lines = line_n - sHudScroll;
            if (visible_lines > 3) visible_lines = 3;
            int max_w = 0;
            for (int l = 0; l < visible_lines; l++) {
                int lw = line_counts[sHudScroll + l] * sPack.glyph_w;
                if (lw > max_w) max_w = lw;
            }
            int has_more_lines = sHudScroll + visible_lines < line_n;
#ifdef RB_HOST_TEST
            sHudFirstVisibleLine = sHudScroll;
#endif
            if (max_w > RB_FB_W - 16) max_w = RB_FB_W - 16;

            int line_h = sPack.glyph_h + 3;
            int total_h = visible_lines * line_h - 3;
            if (total_h < 12) total_h = 12;

            /* Determine whether dialogue box is at bottom, top, or center */
            int target_y;
            if (sCfg.hud_pos == RB_POS_BOTTOM) {
                target_y = 106 + (38 - total_h) / 2;
            } else if (sCfg.hud_pos == RB_POS_TOP) {
                target_y = 14 + (38 - total_h) / 2;
            } else if (sCfg.hud_pos == RB_POS_CENTER) {
                target_y = (RB_FB_H - total_h) / 2;
            } else {
                /* RB_POS_AUTO: Auto-dodge in-game dialogue box:
                 * If in-game dialogue is at BOTTOM -> translation HUD appears at TOP.
                 * If in-game dialogue is at TOP    -> translation HUD appears at BOTTOM.
                 */
                int top_dark = 0, bottom_dark = 0;
                static const int xs[] = { 60, 120, 180 };
                for (int i = 0; i < 3; i++) {
                    int x = xs[i];
                    if ((fb[20 * p + x] & 0x7BEF) <= 0x0842) top_dark++;
                    if ((fb[120 * p + x] & 0x7BEF) <= 0x0842) bottom_dark++;
                }
                int in_game_box_at_bottom = (bottom_dark > top_dark);
                target_y = in_game_box_at_bottom ? (14 + (38 - total_h) / 2) : (106 + (38 - total_h) / 2);
            }
            if (target_y < 8) target_y = 8;
            if (target_y + total_h > RB_FB_H - 8) target_y = RB_FB_H - 8 - total_h;

            int pill_pad_x = 8;
            int pill_pad_y = 4;
            int pill_x = (RB_FB_W - max_w) / 2 - pill_pad_x;
            int pill_y = target_y - pill_pad_y;
            int pill_w = max_w + pill_pad_x * 2;
            int pill_h = total_h + pill_pad_y * 2;
            if (pill_x < 4) { pill_x = 4; pill_w = RB_FB_W - 8; }

            /* Subtle dark slate backing pill covering dialogue area cleanly */
            for (int r = pill_y; r < pill_y + pill_h; r++) {
                if (r < 0 || r >= RB_FB_H) continue;
                for (int c = pill_x; c < pill_x + pill_w; c++) {
                    if (c < 0 || c >= RB_FB_W) continue;
                    if ((r == pill_y || r == pill_y + pill_h - 1) &&
                        (c == pill_x || c == pill_x + pill_w - 1)) continue;
                    fb[r * p + c] = 0x0842;
                }
            }
            /* Clean subtle border */
            for (int c = pill_x + 1; c < pill_x + pill_w - 1; c++) {
                if (pill_y >= 0 && pill_y < RB_FB_H && c >= 0 && c < RB_FB_W)
                    fb[pill_y * p + c] = 0x2128;
                if (pill_y + pill_h - 1 >= 0 && pill_y + pill_h - 1 < RB_FB_H && c >= 0 && c < RB_FB_W)
                    fb[(pill_y + pill_h - 1) * p + c] = 0x2128;
            }
            for (int r = pill_y + 1; r < pill_y + pill_h - 1; r++) {
                if (r >= 0 && r < RB_FB_H && pill_x >= 0 && pill_x < RB_FB_W)
                    fb[r * p + pill_x] = 0x2128;
                if (r >= 0 && r < RB_FB_H && pill_x + pill_w - 1 >= 0 && pill_x + pill_w - 1 < RB_FB_W)
                    fb[r * p + pill_x + pill_w - 1] = 0x2128;
            }

            /* Draw centered lines with drop shadow and crisp text */
            for (int l = 0; l < visible_lines; l++) {
                int source_line = sHudScroll + l;
                int lw = line_counts[source_line] * sPack.glyph_w;
                int lx = (RB_FB_W - lw) / 2;
                if (lx < 8) lx = 8;
                int ly = target_y + l * line_h;
                for (int g = 0; g < line_counts[source_line]; g++) {
                    uint16_t idx = sPack.indices[start + line_starts[source_line] + g];
                    int gx = lx + g * sPack.glyph_w;
                    glyph_color(fb, p, gx + 1, ly + 1, idx, 0x0000);
                    glyph_color(fb, p, gx, ly, idx, is_notice ? 0xCE79 : 0xFFFF);
                }
            }
            if (has_more_lines)
                rect(fb, p, pill_x + pill_w - 5, pill_y + pill_h - 5, 2, 2, 0xFFFF);
        } else {
            int nw = 14 * 6;
            int nx = (RB_FB_W - nw) / 2;
            int ny = 24;
            rect(fb, p, nx - 4, ny - 3, nw + 8, 14, 0x0842);
            ui_text(fb, p, nx, ny, "NO TRANSLATION", 0xFFFF);
        }
    } else if (sState == RB_MENU || sState == RB_BINDINGS) {
        int mw = 192, mh = sState == RB_MENU ? 132 : 110;
        int mx = (RB_FB_W - mw) / 2, my = 12;
        rect(fb, p, mx - 2, my - 2, mw + 4, mh + 4, 0x7BEF);
        rect(fb, p, mx, my, mw, mh, 0x0000);
        if (sState == RB_MENU) {
            static const char* labels[6] = {
                "QUICK SAVE", "QUICK LOAD", "X BUTTON", "POSITION", "FILTER", "AUTO SAVE"
            };
            static const char* x_names[X_ACT_COUNT] = {
                "TRANSLATE", "SAVE", "LOAD"
            };
            static const char* pos_names[RB_POS_COUNT] = {
                "AUTO", "TOP", "CENTER", "BOTTOM"
            };
            for (int i = 0; i < 6; i++) {
                int iy = my + 5 + i * 11;
                if (i == sMenuCursor) rect(fb, p, mx + 2, iy - 2, mw - 4, 10, 0x2965);
                ui_text(fb, p, mx + 8, iy, labels[i], 0xFFFF);
                if (i == 0 || i == 1) {
                    char buf[24];
                    int has_data = rb_slot_has_data(sCfg.slot);
                    uint16_t slot_col = has_data ? 0x2FE5 : 0x7BEF; /* Green if has data, Gray if empty */
                    snprintf(buf, sizeof(buf), "< SLOT %d >", sCfg.slot + 1);
                    ui_text(fb, p, mx + mw - 62, iy, buf, slot_col);
                } else if (i == 2) {
                    ui_text(fb, p, mx + mw - 62, iy, x_names[sCfg.x_action], 0xFFE0);
                } else if (i == 3) {
                    ui_text(fb, p, mx + mw - 48, iy, pos_names[sCfg.hud_pos], 0xFFE0);
                } else if (i == 4) {
                    char buf[24];
                    snprintf(buf, sizeof(buf), "< %s >", sFilterNames[sCfg.visual_filter]);
                    ui_text(fb, p, mx + mw - 80, iy, buf, 0x07FF);
                } else if (i == 5) {
                    char buf[24];
                    snprintf(buf, sizeof(buf), "< %s >", sAutoSaveNames[sCfg.autosave_interval]);
                    ui_text(fb, p, mx + mw - 62, iy, buf, sCfg.autosave_interval ? 0x2FE5 : 0x7BEF);
                }
            }

            /* Slot details card */
            rect(fb, p, mx + 4, my + 78, mw - 8, 1, 0x2965);

            RBSlotInfo info;
            rb_get_slot_info(sCfg.slot, &info);

            char l1[64];
            char l2[64];
            uint16_t col1 = info.valid ? 0x2FE5 : 0x7BEF;
            uint16_t col2 = info.valid ? 0xFFFF : 0x7BEF;

            if (info.valid) {
                if (info.area_name[0]) {
                    snprintf(l1, sizeof(l1), "SLOT %d: %s", sCfg.slot + 1, info.area_name);
                    snprintf(l2, sizeof(l2), "%d HEARTS  %dR   %s", info.hearts, info.rupees, info.time_str);
                } else {
                    snprintf(l1, sizeof(l1), "SLOT %d: SAVED STATE", sCfg.slot + 1);
                    snprintf(l2, sizeof(l2), "SAVED %s", info.time_str);
                }
            } else {
                snprintf(l1, sizeof(l1), "SLOT %d: (EMPTY SLOT)", sCfg.slot + 1);
                snprintf(l2, sizeof(l2), "NO SAVED STATE DATA");
            }

            ui_text(fb, p, mx + 8, my + 82, l1, col1);
            ui_text(fb, p, mx + 8, my + 93, l2, col2);
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
        ui_text(fb, p, 4, RB_FB_H - 10, "Y/B:CLOSE  A:OK  < >:SLOT/OPTION", 0xAD55);
    } else if (sState == RB_CONFIRM_OVERWRITE) {
        int mw = 180, mh = 64;
        int mx = (RB_FB_W - mw) / 2, my = (RB_FB_H - mh) / 2;
        rect(fb, p, mx - 2, my - 2, mw + 4, mh + 4, 0x0000);
        rect(fb, p, mx - 1, my - 1, mw + 2, mh + 2, 0xF800);
        rect(fb, p, mx, my, mw, mh, 0x0000);

        char title[32];
        snprintf(title, sizeof(title), "OVERWRITE SLOT %d?", sCfg.slot + 1);
        ui_text(fb, p, mx + (mw - (int)strlen(title) * 6) / 2, my + 8, title, 0xFFE0);

        RBSlotInfo info;
        rb_get_slot_info(sCfg.slot, &info);
        if (info.valid && info.area_name[0]) {
            char l1[36];
            snprintf(l1, sizeof(l1), "%s", info.area_name);
            ui_text(fb, p, mx + (mw - (int)strlen(l1) * 6) / 2, my + 22, l1, 0x2FE5);
            char l2[36];
            snprintf(l2, sizeof(l2), "%s", info.time_str);
            ui_text(fb, p, mx + (mw - (int)strlen(l2) * 6) / 2, my + 32, l2, 0xCE79);
        } else {
            const char* sub = "SLOT HAS EXISTING DATA";
            ui_text(fb, p, mx + (mw - (int)strlen(sub) * 6) / 2, my + 26, sub, 0xCE79);
        }

        rect(fb, p, mx + 6, my + 44, mw - 12, 1, 0x2965);
        const char* act = "A:OVERWRITE   B:CANCEL";
        ui_text(fb, p, mx + (mw - (int)strlen(act) * 6) / 2, my + 48, act, 0xFFFF);
    }

    if (sVolumeTicks > 0) {
        const int box_x = RB_FB_W - 98;
        const int box_y = 5;
        const int bar_x = box_x + 26;
        const int bar_w = 38;
        char value[8];
        snprintf(value, sizeof(value), "%d%%", sVolumeLevel);
        rect(fb, p, box_x, box_y, 94, 17, 0x7BEF);
        rect(fb, p, box_x + 1, box_y + 1, 92, 15, 0x0842);
        ui_text(fb, p, box_x + 4, box_y + 5, "VOL", 0xFFFF);
        rect(fb, p, bar_x, box_y + 5, bar_w, 7, 0x39E7);
        int fill = bar_w * sVolumeLevel / 100;
        if (fill > 0) rect(fb, p, bar_x, box_y + 5, fill, 7, 0x07E0);
        ui_text(fb, p, box_x + 68, box_y + 5, value, 0xFFE0);
        if (sState == RB_GAME) sVolumeTicks--;
    }

    if (sToastTicks > 0) {
        int tw = (int)strlen(sToastMsg) * 6 + 12;
        int tx = (RB_FB_W - tw) / 2;
        int ty = 8;
        rect(fb, p, tx - 1, ty - 1, tw + 2, 14, 0x7BEF);
        for (int r = ty; r < ty + 12; r++)
            for (int c = tx; c < tx + tw; c++)
                fb[r * p + c] = 0x1084;
        ui_text(fb, p, tx + 6, ty + 2, sToastMsg, 0xFFFF);
        if (sState == RB_GAME) sToastTicks--;
    }
    (void)core;
}

void retrobilingual_present(void* in_pixels, unsigned in_w, unsigned in_h, unsigned in_pitch,
                            void** out_pixels, unsigned* out_w, unsigned* out_h, unsigned* out_pitch)
{
    if (!in_pixels || in_w != RB_FB_W || in_h != RB_FB_H) {
        if (out_pixels) *out_pixels = in_pixels;
        if (out_w) *out_w = in_w;
        if (out_h) *out_h = in_h;
        if (out_pitch) *out_pitch = in_pitch;
        return;
    }
    rb_init_filter_luts();

    const uint16_t* src_base = (const uint16_t*)in_pixels;
    unsigned src_pitch_pixels = in_pitch >> 1;
    int mode = sCfg.visual_filter;
    if (mode < 0 || mode >= RB_FILTER_COUNT) mode = RB_FILTER_OFF;

    for (unsigned y = 0; y < RB_FB_H; y++) {
        const uint16_t* src = src_base + y * src_pitch_pixels;
        uint16_t* row0 = sScaleFrame + (y * 3 + 0) * RB_OUT_W;
        uint16_t* row1 = sScaleFrame + (y * 3 + 1) * RB_OUT_W;
        uint16_t* row2 = sScaleFrame + (y * 3 + 2) * RB_OUT_W;

        switch (mode) {
        case RB_FILTER_OFF:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t c = src[x];
                row0[x * 3 + 0] = c; row0[x * 3 + 1] = c; row0[x * 3 + 2] = c;
                row1[x * 3 + 0] = c; row1[x * 3 + 1] = c; row1[x * 3 + 2] = c;
                row2[x * 3 + 0] = c; row2[x * 3 + 1] = c; row2[x * 3 + 2] = c;
            }
            break;

        case RB_FILTER_LCD_GRID:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t c = src[x];
                uint16_t c50 = (c + (c & 0x0821)) >> 1;
                uint16_t c75 = (c + c50 + ((c ^ c50) & 0x0821)) >> 1;
                row0[x * 3 + 0] = c;   row0[x * 3 + 1] = c;   row0[x * 3 + 2] = c75;
                row1[x * 3 + 0] = c;   row1[x * 3 + 1] = c;   row1[x * 3 + 2] = c75;
                row2[x * 3 + 0] = c75; row2[x * 3 + 1] = c75; row2[x * 3 + 2] = c50;
            }
            break;

        case RB_FILTER_GBA_COLOR:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t cg = sGbaColorLut[src[x]];
                row0[x * 3 + 0] = cg; row0[x * 3 + 1] = cg; row0[x * 3 + 2] = cg;
                row1[x * 3 + 0] = cg; row1[x * 3 + 1] = cg; row1[x * 3 + 2] = cg;
                row2[x * 3 + 0] = cg; row2[x * 3 + 1] = cg; row2[x * 3 + 2] = cg;
            }
            break;

        case RB_FILTER_LCD_COLOR:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t cg = sGbaColorLut[src[x]];
                uint16_t c50 = (cg + (cg & 0x0821)) >> 1;
                uint16_t c75 = (cg + c50 + ((cg ^ c50) & 0x0821)) >> 1;
                row0[x * 3 + 0] = cg;  row0[x * 3 + 1] = cg;  row0[x * 3 + 2] = c75;
                row1[x * 3 + 0] = cg;  row1[x * 3 + 1] = cg;  row1[x * 3 + 2] = c75;
                row2[x * 3 + 0] = c75; row2[x * 3 + 1] = c75; row2[x * 3 + 2] = c50;
            }
            break;

        case RB_FILTER_CRT_SCANLINE:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t c = src[x];
                uint16_t c50 = (c + (c & 0x0821)) >> 1;
                row0[x * 3 + 0] = c;   row0[x * 3 + 1] = c;   row0[x * 3 + 2] = c;
                row1[x * 3 + 0] = c;   row1[x * 3 + 1] = c;   row1[x * 3 + 2] = c;
                row2[x * 3 + 0] = c50; row2[x * 3 + 1] = c50; row2[x * 3 + 2] = c50;
            }
            break;

        case RB_FILTER_SUBPIXEL_RGB:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t c = src[x];
                uint16_t cr = (c & 0xF800) | ((c >> 2) & 0x01E0) | ((c >> 2) & 0x0007);
                uint16_t cg = ((c >> 2) & 0x3800) | (c & 0x07E0) | ((c >> 2) & 0x0007);
                uint16_t cb = ((c >> 2) & 0x3800) | ((c >> 2) & 0x01E0) | (c & 0x001F);
                uint16_t c50 = (c + (c & 0x0821)) >> 1;
                row0[x * 3 + 0] = cr;  row0[x * 3 + 1] = cg;  row0[x * 3 + 2] = cb;
                row1[x * 3 + 0] = cr;  row1[x * 3 + 1] = cg;  row1[x * 3 + 2] = cb;
                row2[x * 3 + 0] = c50; row2[x * 3 + 1] = c50; row2[x * 3 + 2] = c50;
            }
            break;

        case RB_FILTER_GB_DMG:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t cd = sGbDmgLut[src[x]];
                uint16_t c50 = (cd + (cd & 0x0821)) >> 1;
                uint16_t c75 = (cd + c50 + ((cd ^ c50) & 0x0821)) >> 1;
                row0[x * 3 + 0] = cd;  row0[x * 3 + 1] = cd;  row0[x * 3 + 2] = c75;
                row1[x * 3 + 0] = cd;  row1[x * 3 + 1] = cd;  row1[x * 3 + 2] = c75;
                row2[x * 3 + 0] = c75; row2[x * 3 + 1] = c75; row2[x * 3 + 2] = c50;
            }
            break;

        case RB_FILTER_GB_POCKET:
            for (unsigned x = 0; x < RB_FB_W; x++) {
                uint16_t cp = sGbPocketLut[src[x]];
                uint16_t c50 = (cp + (cp & 0x0821)) >> 1;
                uint16_t c75 = (cp + c50 + ((cp ^ c50) & 0x0821)) >> 1;
                row0[x * 3 + 0] = cp;  row0[x * 3 + 1] = cp;  row0[x * 3 + 2] = c75;
                row1[x * 3 + 0] = cp;  row1[x * 3 + 1] = cp;  row1[x * 3 + 2] = c75;
                row2[x * 3 + 0] = c75; row2[x * 3 + 1] = c75; row2[x * 3 + 2] = c50;
            }
            break;
        }
    }

    if (out_pixels) *out_pixels = sScaleFrame;
    if (out_w) *out_w = RB_OUT_W;
    if (out_h) *out_h = RB_OUT_H;
    if (out_pitch) *out_pitch = RB_OUT_W * sizeof(uint16_t);
}

#ifdef RB_HOST_TEST
int rb_test_pack_loaded(void) { return sPack.loaded; }
int rb_test_state(void) { return (int)sState; }
int rb_test_dialogue_page(void) { return (int)sDlgPage; }
int rb_test_glyphs(void) { return (int)sDlgGlyphCount; }
int rb_test_slot(void) { return sCfg.slot; }
int rb_test_slot_has_data(int slot) { return rb_slot_has_data(slot); }
int rb_test_hud_pos(void) { return sCfg.hud_pos; }
int rb_test_hud_scroll(void) { return sHudScroll; }
int rb_test_hud_first_visible_line(void) { return sHudFirstVisibleLine; }
int rb_test_visual_filter(void) { return sCfg.visual_filter; }
int rb_test_autosave_interval(void) { return sCfg.autosave_interval; }
void rb_test_autosave_start_at(int64_t now_ms) { sAutoSaveClockStarted = 0; sAutoSaveLastTimeMs = now_ms; }
void rb_test_autosave_tick_at(struct mCore* core, int64_t now_ms) { rb_auto_save_tick_at(core, now_ms); }
const char* rb_test_toast(void) { return sToastTicks > 0 ? sToastMsg : ""; }
int rb_test_slot_info(int slot, char* area_out, size_t area_sz, int* hearts_out, int* rupees_out) {
    RBSlotInfo info;
    rb_get_slot_info(slot, &info);
    if (!info.valid) return 0;
    if (area_out && area_sz) snprintf(area_out, area_sz, "%s", info.area_name);
    if (hearts_out) *hearts_out = info.hearts;
    if (rupees_out) *rupees_out = info.rupees;
    return 1;
}
#endif
