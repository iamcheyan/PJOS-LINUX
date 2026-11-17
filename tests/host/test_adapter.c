#include "adapters/adapter.h"
#include "host_stubs.h"

#include <string.h>

static uint16_t text_id;
static uint8_t render;
static uint8_t page;

static void reset(void) {
    text_id = 0;
    render = 0;
    page = 0;
}

static int read_dialogue(struct mCore* core, uint16_t keys,
                         uint16_t* out_text_id, uint8_t* out_page) {
    (void)keys;
    if (!core || !core->board) return 0;
    const struct GBA* gba = core->board;
    if (!gba->memory.wram) return 0;
    const uint8_t* ewram = (const uint8_t*)gba->memory.wram;
    if (!(ewram[0x50] & 0x7F)) return 0;
    uint16_t next = (uint16_t)(ewram[0x58] | (ewram[0x59] << 8));
    uint8_t state = ewram[0x22809];
    if (!next || next == 0xFFFF) return 0;
    if (next != text_id) {
        text_id = next;
        page = 0;
    } else if (render == 3 && state == 4 && page < 0xFF) {
        page++;
    }
    render = state;
    *out_text_id = text_id;
    *out_page = page;
    return 1;
}

const RBAdapter g_rb_adapter_tmc = {
    .game_id = "host_fixture",
    .title = "Host adapter fixture",
    .rom_size = 16 * 1024 * 1024,
    .sha256_hex = "f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b",
    .reset = reset,
    .read_dialogue = read_dialogue,
};

const RBAdapter g_rb_adapter_golden_sun = {0};
const RBAdapter g_rb_adapter_golden_sun_cn2024 = {0};

const RBAdapter* rb_adapter_match(uint32_t rom_size, const uint8_t sha256[32]) {
    return rom_size == 16 * 1024 * 1024 && sha256 ? &g_rb_adapter_tmc : 0;
}
