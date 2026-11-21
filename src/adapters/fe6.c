#include "adapters/adapter.h"

#include <mgba/core/core.h>
#include <mgba/internal/gba/gba.h>

/* Fire Emblem: The Binding Blade, Japanese AFEJ01 rev0. The clean 8 MiB
 * dump matches the FE6 decompilation's sha1 and has this SHA-256. */
#define FE6_JA_ROM_SIZE 0x00800000u
#define FE6_JA_SHA256 "e62288883544705b18f1a0753896fdd865a628fb4589135813b16a972a4c1557"

/* Exact EWRAM/IWRAM locations from the matching FE6 decompilation symbols. */
#define FE6_ACTIVE_MSG_OFFSET  0x0002A404u /* EWRAM 0x0202A404 sActiveMsg */
#define FE6_MSG_BUFFER_OFFSET  0x00029404u /* EWRAM 0x02029404 sMsgString */
#define FE6_MSG_BUFFER_SIZE    0x00001000u
#define FE6_PROC_ARRAY_OFFSET  0x00023CC4u /* EWRAM 0x02023CC4 sProcArray */
#define FE6_PROC_SIZE          0x0000006Cu
#define FE6_PROC_COUNT         64u
#define FE6_TALK_SCRIPT        0x085C3D04u /* ProcScr_Talk */
#define FE6_TALK_STATE_OFFSET  0x00000038u /* IWRAM 0x03000038 sTalkStObj */
#define FE6_TALK_STR_OFFSET    0x00u
#define FE6_PAGE_WAIT_CODE     0x03u

static void fe6_reset(void) {
}

static int fe6_read_dialogue(struct mCore* core, uint16_t keys,
                             uint16_t* out_text_id, uint8_t* out_page) {
    (void)keys;
    if (!core || !core->board || !out_text_id || !out_page) return 0;

    const struct GBA* gba = (const struct GBA*)core->board;
    if (!gba->memory.wram || !gba->memory.iwram) return 0;
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    const uint8_t* iwram = (const uint8_t*)gba->memory.iwram;

    /* A talk proc exists while a dialogue is open, including the final
     * "press A" wait. Once it ends, the cached sActiveMsg/str must not keep
     * the HUD open. */
    int talk_active = 0;
    for (unsigned i = 0; i < FE6_PROC_COUNT; ++i) {
        uint32_t script = 0;
        const uint8_t* proc = ewram + FE6_PROC_ARRAY_OFFSET + i * FE6_PROC_SIZE;
        script = (uint32_t)proc[0] | ((uint32_t)proc[1] << 8)
            | ((uint32_t)proc[2] << 16) | ((uint32_t)proc[3] << 24);
        if (script == FE6_TALK_SCRIPT) {
            talk_active = 1;
            break;
        }
    }
    if (!talk_active) return 0;

    const uint8_t* talk = iwram + FE6_TALK_STATE_OFFSET;
    uint32_t str_addr = (uint32_t)talk[FE6_TALK_STR_OFFSET]
        | ((uint32_t)talk[FE6_TALK_STR_OFFSET + 1] << 8)
        | ((uint32_t)talk[FE6_TALK_STR_OFFSET + 2] << 16)
        | ((uint32_t)talk[FE6_TALK_STR_OFFSET + 3] << 24);
    uint32_t buf_addr = 0x02000000u + FE6_MSG_BUFFER_OFFSET;
    if (str_addr < buf_addr || str_addr >= buf_addr + FE6_MSG_BUFFER_SIZE)
        return 0;

    uint32_t text_id = (uint32_t)ewram[FE6_ACTIVE_MSG_OFFSET]
        | ((uint32_t)ewram[FE6_ACTIVE_MSG_OFFSET + 1] << 8)
        | ((uint32_t)ewram[FE6_ACTIVE_MSG_OFFSET + 2] << 16)
        | ((uint32_t)ewram[FE6_ACTIVE_MSG_OFFSET + 3] << 24);
    if (text_id > 0xFFFFu) return 0;

    /* talk.c advances str past control 0x03 before spawning the wait proc.
     * The page just displayed is therefore the count of consumed 0x03
     * controls minus one; while the first page is typing no wait has been
     * consumed yet and page 0 is correct. */
    const uint8_t* text = ewram + FE6_MSG_BUFFER_OFFSET;
    uint32_t cursor = str_addr - buf_addr;
    unsigned waits = 0;
    for (uint32_t i = 0; i < cursor; ++i)
        if (text[i] == FE6_PAGE_WAIT_CODE) waits++;
    if (waits > 0xFFu) waits = 0xFFu;

    *out_text_id = (uint16_t)text_id;
    *out_page = (uint8_t)(waits > 0 ? waits - 1u : 0u);
    return 1;
}

const RBAdapter g_rb_adapter_fe6 = {
    .game_id = "fe6_jp",
    .title = "Fire Emblem: The Binding Blade (Japan, AFEJ01 rev0)",
    .rom_size = FE6_JA_ROM_SIZE,
    .sha256_hex = FE6_JA_SHA256,
    .reset = fe6_reset,
    .read_dialogue = fe6_read_dialogue,
    .page_slack = 0,
};
