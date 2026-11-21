#include "adapters/adapter.h"

#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/* Fire Emblem: The Blazing Blade, Japanese AE7J01 rev0. The clean 16 MiB
 * dump matches the FireEmblem7J decompilation's SHA-1. */
#define FE7_JA_ROM_SIZE 0x01000000u
#define FE7_JA_SHA256 "7ec691a7411864ab51765028156c5b8a3c23a317d23c95fbf07ac201212e25c0"

/* Exact locations from the matching FE7J decompilation symbols. */
#define FE7_ACTIVE_MSG_OFFSET  0x0002B5B0u /* EWRAM 0x0202B5B0 sActiveMsg */
#define FE7_MSG_BUFFER_OFFSET  0x0002A5B0u /* EWRAM 0x0202A5B0 sMsgString */
#define FE7_MSG_BUFFER_SIZE    0x00001000u
#define FE7_PROC_ARRAY_OFFSET  0x00024E20u /* EWRAM 0x02024E20 sProcArray */
#define FE7_PROC_SIZE          0x0000006Cu
#define FE7_PROC_COUNT         64u
#define FE7_TALK_SCRIPT        0x08BFFB84u /* ProcScr_Talk */
#define FE7_TALK_STATE_OFFSET  0x00000040u /* IWRAM 0x03000040 sTalkStObj */
#define FE7_TALK_STR_OFFSET    0x00u
#define FE7_PAGE_WAIT_CODE     0x03u

static void fe7_reset(void) {
}

static int fe7_read_dialogue(struct mCore* core, uint16_t keys,
                             uint16_t* out_text_id, uint8_t* out_page) {
    (void)keys;
    if (!core || !core->board || !out_text_id || !out_page) return 0;

    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba->memory.wram || !gba->memory.iwram) return 0;
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    const uint8_t* iwram = (const uint8_t*)gba->memory.iwram;

    int talk_active = 0;
    for (unsigned i = 0; i < FE7_PROC_COUNT; ++i) {
        const uint8_t* proc = ewram + FE7_PROC_ARRAY_OFFSET + i * FE7_PROC_SIZE;
        uint32_t script = (uint32_t)proc[0] | ((uint32_t)proc[1] << 8)
            | ((uint32_t)proc[2] << 16) | ((uint32_t)proc[3] << 24);
        if (script == FE7_TALK_SCRIPT) {
            talk_active = 1;
            break;
        }
    }
    if (!talk_active) return 0;

    const uint8_t* talk = iwram + FE7_TALK_STATE_OFFSET;
    uint32_t str_addr = (uint32_t)talk[FE7_TALK_STR_OFFSET]
        | ((uint32_t)talk[FE7_TALK_STR_OFFSET + 1] << 8)
        | ((uint32_t)talk[FE7_TALK_STR_OFFSET + 2] << 16)
        | ((uint32_t)talk[FE7_TALK_STR_OFFSET + 3] << 24);
    uint32_t buf_addr = 0x02000000u + FE7_MSG_BUFFER_OFFSET;
    if (str_addr < buf_addr || str_addr >= buf_addr + FE7_MSG_BUFFER_SIZE)
        return 0;

    uint32_t text_id = (uint32_t)ewram[FE7_ACTIVE_MSG_OFFSET]
        | ((uint32_t)ewram[FE7_ACTIVE_MSG_OFFSET + 1] << 8)
        | ((uint32_t)ewram[FE7_ACTIVE_MSG_OFFSET + 2] << 16)
        | ((uint32_t)ewram[FE7_ACTIVE_MSG_OFFSET + 3] << 24);
    if (text_id > 0xFFFFu) return 0;

    const uint8_t* text = ewram + FE7_MSG_BUFFER_OFFSET;
    uint32_t cursor = str_addr - buf_addr;
    unsigned waits = 0;
    for (uint32_t i = 0; i < cursor; ++i)
        if (text[i] == FE7_PAGE_WAIT_CODE) waits++;
    if (waits > 0xFFu) waits = 0xFFu;

    *out_text_id = (uint16_t)text_id;
    *out_page = (uint8_t)(waits > 0 ? waits - 1u : 0u);
    return 1;
}

const RBAdapter g_rb_adapter_fe7 = {
    .game_id = "fe7_jp",
    .title = "Fire Emblem: The Blazing Blade (Japan, AE7J01 rev0)",
    .rom_size = FE7_JA_ROM_SIZE,
    .sha256_hex = FE7_JA_SHA256,
    .reset = fe7_reset,
    .read_dialogue = fe7_read_dialogue,
    .page_slack = 0,
};
