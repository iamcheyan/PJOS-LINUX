#include "adapter.h"
#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/*
 * Adapter Template for New Retro Games
 * -------------------------------------
 * To support a new GBA game:
 * 1. Find the ROM size and SHA-256 hash.
 * 2. Use mGBA / No$gba memory search / watchpoint to find:
 *    - The RAM address containing the current message / dialogue ID.
 *    - The RAM address or state machine tracking the dialogue page / line advance.
 * 3. Implement read_dialogue() below to extract (text_id, page).
 * 4. Add your adapter to the registry in retrobilingual.c.
 */

/* Example: My Game (Japan) */
#define MYGAME_ROM_SIZE 0x01000000
#define MYGAME_SHA256   "0000000000000000000000000000000000000000000000000000000000000000"

static uint16_t sMyGameTextId;
static uint8_t  sMyGamePage;

static void mygame_reset(void) {
    sMyGameTextId = 0;
    sMyGamePage = 0;
}

static int mygame_read(struct mCore* core, uint16_t* out_text_id, uint8_t* out_page) {
    if (!core) return 0;
    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba || !gba->memory.ewram) return 0;

    /*
     * Example: Read dialogue ID from EWRAM offset.
     * Replace 0x0200XXXX with your game's dialogue pointer or index address.
     */
    /* uint32_t addr = 0x0200XXXX; */
    /* uint16_t textId = *(const uint16_t*)(gba->memory.ewram + (addr - 0x02000000)); */

    /* If no dialogue is currently showing, return 0 */
    /* if (textId == 0) return 0; */

    /* Track page turns on A button or state changes */
    /* ... */

    /* *out_text_id = textId; */
    /* *out_page = sMyGamePage; */
    /* return 1; */
    return 0;
}

const RBAdapter g_rb_adapter_template = {
    .game_id = "my_game",
    .title = "Template Game Title",
    .rom_size = MYGAME_ROM_SIZE,
    .sha256_hex = MYGAME_SHA256,
    .reset = mygame_reset,
    .read_dialogue = mygame_read,
};
