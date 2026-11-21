#include "adapters/adapter.h"

#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/* Fire Emblem: The Sacred Stones, Japanese BE8J01 rev0. The clean 16 MiB
 * dump matches the fireemblem8j decompilation's SHA-1. */
#define FE8_JA_ROM_SIZE 0x01000000u
#define FE8_JA_SHA256 "44fd343625ab9e6b90f63a80758c15066d526e6873fae91474006314a5ead464"

/* Locations confirmed from the matching FE8J disassembly and a live run. */
#define FE8_ACTIVE_MSG_OFFSET  0x0002B6A8u /* EWRAM 0x0202B6A8 sActiveMsg */
#define FE8_MSG_BUFFER_OFFSET  0x0002A6A8u /* EWRAM 0x0202A6A8 sMsgString */
#define FE8_MSG_BUFFER_SIZE    0x00001000u
#define FE8_PROC_ARRAY_OFFSET  0x00024E68u /* EWRAM 0x02024E68 sProcArray */
#define FE8_PROC_SIZE          0x0000006Cu
#define FE8_PROC_COUNT         64u
#define FE8_TALK_SCRIPT        0x085B90F0u /* gProcScr_Talk */
#define FE8_TALK_STATE_OFFSET  0x00000040u /* IWRAM 0x03000040 sTalkStateCore */
#define FE8_TALK_STR_OFFSET    0x00u
#define FE8_PAGE_WAIT_CODE     0x03u

static void fe8_reset(void) {
}

static int fe8_read_dialogue(struct mCore* core, uint16_t keys,
                             uint16_t* out_text_id, uint8_t* out_page) {
    (void)keys;
    if (!core || !core->board || !out_text_id || !out_page) return 0;

    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba->memory.wram || !gba->memory.iwram) return 0;
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    const uint8_t* iwram = (const uint8_t*)gba->memory.iwram;

    int talk_active = 0;
    for (unsigned i = 0; i < FE8_PROC_COUNT; ++i) {
        const uint8_t* proc = ewram + FE8_PROC_ARRAY_OFFSET + i * FE8_PROC_SIZE;
        uint32_t script = (uint32_t)proc[0] | ((uint32_t)proc[1] << 8)
            | ((uint32_t)proc[2] << 16) | ((uint32_t)proc[3] << 24);
        if (script == FE8_TALK_SCRIPT) {
            talk_active = 1;
            break;
        }
    }
    if (!talk_active) return 0;

    const uint8_t* talk = iwram + FE8_TALK_STATE_OFFSET;
    uint32_t str_addr = (uint32_t)talk[FE8_TALK_STR_OFFSET]
        | ((uint32_t)talk[FE8_TALK_STR_OFFSET + 1] << 8)
        | ((uint32_t)talk[FE8_TALK_STR_OFFSET + 2] << 16)
        | ((uint32_t)talk[FE8_TALK_STR_OFFSET + 3] << 24);
    uint32_t buf_addr = 0x02000000u + FE8_MSG_BUFFER_OFFSET;
    if (str_addr < buf_addr || str_addr >= buf_addr + FE8_MSG_BUFFER_SIZE)
        return 0;

    uint32_t text_id = (uint32_t)ewram[FE8_ACTIVE_MSG_OFFSET]
        | ((uint32_t)ewram[FE8_ACTIVE_MSG_OFFSET + 1] << 8)
        | ((uint32_t)ewram[FE8_ACTIVE_MSG_OFFSET + 2] << 16)
        | ((uint32_t)ewram[FE8_ACTIVE_MSG_OFFSET + 3] << 24);
    if (text_id > 0xFFFFu) return 0;

    const uint8_t* text = ewram + FE8_MSG_BUFFER_OFFSET;
    uint32_t cursor = str_addr - buf_addr;
    unsigned waits = 0;
    for (uint32_t i = 0; i < cursor; ++i)
        if (text[i] == FE8_PAGE_WAIT_CODE) waits++;
    if (waits > 0xFFu) waits = 0xFFu;

    *out_text_id = (uint16_t)text_id;
    *out_page = (uint8_t)(waits > 0 ? waits - 1u : 0u);
    return 1;
}

const RBAdapter g_rb_adapter_fe8 = {
    .game_id = "fe8_jp",
    .title = "Fire Emblem: The Sacred Stones (Japan, BE8J01 rev0)",
    .rom_size = FE8_JA_ROM_SIZE,
    .sha256_hex = FE8_JA_SHA256,
    .reset = fe8_reset,
    .read_dialogue = fe8_read_dialogue,
    .page_slack = 0,
};
