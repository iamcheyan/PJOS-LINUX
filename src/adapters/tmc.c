#include "adapters/adapter.h"
#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>
#include <string.h>

/* The Legend of Zelda: The Minish Cap (Japan) */
#define TMC_JP_ROM_SIZE 0x01000000
#define TMC_JP_SHA256   "16ac2572ba17e9cb2a70093d41f97ef8cff66c56417e45ea98adacdc51bb4b38"

static uint16_t sTmcTextId;
static uint8_t  sTmcPage;
static uint8_t  sTmcRender;

static void tmc_reset(void) {
    sTmcTextId = 0;
    sTmcPage = 0;
    sTmcRender = 0;
}

static int tmc_read(struct mCore* core, uint16_t keys, uint16_t* out_text_id, uint8_t* out_page) {
    (void)keys;
    if (!core) return 0;
    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba || !gba->memory.wram) return 0;

    /*
     * EWRAM layout for TMC dialogue engine (zeldaret/tmc linker.ld):
     * 0x02000050: Message gMessage
     *   0x02000050: u8 state (MESSAGE_ACTIVE = 0x7F mask)
     *   0x02000058: u16 textIndex
     * 0x02022780: TextRender gTextRender
     *   0x02022788: u16 textIndex (in gTextRender.message)
     *   0x020227A8: u16 textIndex (in gTextRender.curToken)
     *   0x02022809: u8 renderStatus (0x02022780 + 0x89)
     *               3 = RENDER_WAIT (typewriter finished, waiting for player A button)
     *               4 = RENDER_ROLL (player pressed A to flip to next page)
     */
    const uint8_t* wram = (const uint8_t*)gba->memory.wram;
    uint8_t state = wram[0x50];
    if (!(state & 0x7F)) {
        return 0;
    }

    uint16_t textId = *(const uint16_t*)(wram + 0x58);
    if (textId == 0 || textId == 0xFFFF) {
        textId = *(const uint16_t*)(wram + 0x22788);
    }
    if (textId == 0 || textId == 0xFFFF) {
        textId = *(const uint16_t*)(wram + 0x227A8);
    }
    if (textId == 0 || textId == 0xFFFF) {
        return 0;
    }

    uint8_t render = wram[0x22809];

    if (textId == 0 || textId == 0xFFFF) {
        return 0;
    }

    if (textId != sTmcTextId) {
        sTmcTextId = textId;
        sTmcPage = 0;
    } else if (sTmcRender == 3 && render == 4) {
        if (sTmcPage < 0xFF) sTmcPage++;
    }
    sTmcRender = render;

    *out_text_id = sTmcTextId;
    *out_page = sTmcPage;
    return 1;
}

const RBAdapter g_rb_adapter_tmc = {
    .game_id = "zelda_minish_cap",
    .title = "The Legend of Zelda: The Minish Cap (Japan)",
    .rom_size = TMC_JP_ROM_SIZE,
    .sha256_hex = TMC_JP_SHA256,
    .reset = tmc_reset,
    .read_dialogue = tmc_read,
    .page_slack = 0,
};
