#include "adapters/adapter.h"
#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/* Camelot: Golden Sun: The Opened Seal.
 *
 * The clean Japanese AGSJ01 rev0 ROM remains the production profile. The
 * RG34XX also contains an AGSJ-labelled patched dump whose dialogue is
 * already Chinese; it retains the Japanese message IDs and EWRAM cursor.
 */
#define GOLDEN_SUN_JP_ROM_SIZE 0x00800000u
#define GOLDEN_SUN_JP_SHA256 "088bedae4bad8b67e87ff10035a898d3639f3182d486fe5a5d113bab223e0a26"

#define GOLDEN_SUN_RG34XX_ROM_SIZE 0x008D4000u
#define GOLDEN_SUN_RG34XX_SHA256 "f4e431616b920ecb572349f06dcdefd34c15789d2032216e27fe9f7ee36703b5"

#define GOLDEN_SUN_CN2024_ROM_SIZE 0x00B0E9B0u
#define GOLDEN_SUN_CN2024_SHA256 "f566de927b4ccf95e55686553db3089c26b842158d49a2a91472a8b6ba1419bc"

/* Internal libretro keymap bit for A (keymap[0]); golden_sun_read() only
 * sees the filtered bitmask built by libretro.c. */
#define GS_KEY_A (1u << 0)

/* The dialogue box renders glyph tiles into VRAM starting at 0x06002000.
 * Its content is stable once a page has finished drawing, which distinguishes
 * "press A to advance the page" from "press A to fast-forward the typewriter".
 */
#define GS_TEXT_TILE_OFFSET 0x2000u
#define GS_TEXT_TILE_BYTES 0x400u

static uint16_t sLastId;
static uint8_t sPage;
static uint16_t sPrevKeys;
static uint32_t sLastHash;
static uint8_t sStableFrames;
static uint8_t sActive;

static uint32_t gs_text_hash(const struct GBA* gba) {
    if (!gba || !gba->video.vram) return 0;
    const uint8_t* tiles = (const uint8_t*)gba->video.vram + GS_TEXT_TILE_OFFSET;
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; i < GS_TEXT_TILE_BYTES; i++)
        hash = (hash ^ tiles[i]) * 16777619u;
    return hash;
}

static void golden_sun_reset(void) {
    sLastId = 0;
    sPage = 0;
    sPrevKeys = 0;
    sLastHash = 0;
    sStableFrames = 0;
    sActive = 0;
}

static int golden_sun_read(struct mCore* core, uint16_t keys,
                           uint16_t* out_text_id, uint8_t* out_page) {
    if (!core || !out_text_id || !out_page) return 0;
    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba || !gba->memory.wram) return 0;

    /* AGSJ stores the current message-table ID at EWRAM 0x020301D8. Pressing
     * A either advances this ID or flips the page of the same message when
     * the text contains control 0x01. A standalone 0x01 is the only page
     * break; the 0x01 operand of a 0x11 name insertion is not one. */
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    uint16_t text_id = (uint16_t)(ewram[0x301D8] | ((uint16_t)ewram[0x301D9] << 8));
    if (text_id == 0 || text_id == 0xFFFF) {
        sActive = 0;
        sPage = 0;
        sPrevKeys = keys;
        return 0;
    }

    uint32_t hash = gs_text_hash(gba);
    if (sActive && text_id == sLastId && hash == sLastHash) {
        if (sStableFrames < 0xFF) sStableFrames++;
    } else {
        sStableFrames = 0;
    }
    sLastHash = hash;

    if (!sActive || text_id != sLastId) {
        sLastId = text_id;
        sPage = 0;
        sStableFrames = 0;
    } else if ((keys & GS_KEY_A) && !(sPrevKeys & GS_KEY_A) && sStableFrames >= 4) {
        if (sPage < 0xFF) sPage++;
        sStableFrames = 0;
    }
    sPrevKeys = keys;
    sActive = 1;

    *out_text_id = text_id;
    *out_page = sPage;
    return 1;
}

const RBAdapter g_rb_adapter_golden_sun = {
    .game_id = "golden_sun_jp",
    .title = "Golden Sun: The Opened Seal (Japan, AGSJ01 rev0)",
    .rom_size = GOLDEN_SUN_JP_ROM_SIZE,
    .sha256_hex = GOLDEN_SUN_JP_SHA256,
    .reset = golden_sun_reset,
    .read_dialogue = golden_sun_read,
    .page_slack = 1,
};

const RBAdapter g_rb_adapter_golden_sun_rg34xx = {
    .game_id = "golden_sun_rg34xx_f4",
    .title = "Golden Sun: The Opened Seal (RG34XX patched AGSJ dump; Chinese text)",
    .rom_size = GOLDEN_SUN_RG34XX_ROM_SIZE,
    .sha256_hex = GOLDEN_SUN_RG34XX_SHA256,
    .reset = golden_sun_reset,
    .read_dialogue = golden_sun_read,
    .page_slack = 1,
};

const RBAdapter g_rb_adapter_golden_sun_cn2024 = {
    .game_id = "golden_sun_cn2024",
    .title = "Golden Sun: The Opened Seal (2024 CN public beta, verification)",
    .rom_size = GOLDEN_SUN_CN2024_ROM_SIZE,
    .sha256_hex = GOLDEN_SUN_CN2024_SHA256,
    .reset = golden_sun_reset,
    .read_dialogue = golden_sun_read,
    .page_slack = 1,
};
