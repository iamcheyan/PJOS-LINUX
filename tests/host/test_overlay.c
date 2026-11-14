/* Host harness: drives the real retrobilingual.c state machine and renderer. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host_stubs.h"

#include "../src/retrobilingual.h"

int rb_test_pack_loaded(void);
int rb_test_state(void);
int rb_test_dialogue_page(void);
int rb_test_glyphs(void);

enum { RB_STATE_GAME = 0, RB_STATE_MENU = 1, RB_STATE_SUBTITLE = 2 };

static int x_down;
static int16_t input_cb(unsigned port, unsigned device, unsigned index, unsigned id) {
    (void)port; (void)device; (void)index;
    return id == RETRO_DEVICE_ID_JOYPAD_X ? (int16_t)x_down : 0;
}
static size_t state_size(struct mCore* core) { (void)core; return 64; }
static int state_save(struct mCore* core, void* buf) { (void)core; memset(buf, 0x5A, 64); return 1; }
static int state_load(struct mCore* core, const void* buf) { (void)core; return ((const unsigned char*)buf)[0] == 0x5A; }

static uint8_t* read_file(const char* path, size_t* size) {
    FILE* f = fopen(path, "rb");
    if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t* data = malloc((size_t)n);
    if (!data || fread(data, 1, (size_t)n, f) != (size_t)n) exit(1);
    fclose(f);
    *size = (size_t)n;
    return data;
}

int main(int argc, char** argv) {
    if (argc != 2) { fprintf(stderr, "usage: %s <fake-rom>\n", argv[0]); return 2; }
    size_t rom_size;
    uint8_t* rom = read_file(argv[1], &rom_size);
    uint32_t* wram = calloc(0x40000, 1);
    assert(rom && wram);

    struct GBA gba = {0};
    gba.memory.rom = rom;
    gba.memory.romSize = rom_size;
    gba.memory.wram = wram;
    gba.romCrc32 = 0x6CE771A5u;

    struct mCore core = {0};
    core.board = &gba;
    core.stateSize = state_size;
    core.saveState = state_save;
    core.loadState = state_load;

    uint16_t keys = 0;
    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_pack_loaded() == 1);

    uint8_t* ewram = (uint8_t*)wram;
    uint8_t* msg = ewram + 0x50;
    uint8_t* render = ewram + 0x22780;
    msg[0] = 0x01;
    msg[8] = 0x01;
    msg[9] = 0x02; /* text id 0x0201 */
    render[0x89] = 3;

    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_glyphs() > 0);

    /* Page advance: WAIT(3) -> ROLL(4) increments the page. */
    render[0x89] = 4;
    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_dialogue_page() == 1);
    assert(rb_test_glyphs() > 0);

    /* Default chord: L (bit 9) + Select (bit 2). */
    keys = (1u << 9) | (1u << 2);
    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_state() == RB_STATE_SUBTITLE);
    assert(retrobilingual_should_run_frame(&core) == 0);

    static uint16_t fb[240 * 160];
    memset(fb, 0x11, sizeof(fb));
    retrobilingual_draw(&core, fb, 240, 160, 240 * 2);
    int ink = 0;
    for (int y = 160 - 34; y < 160; y++)
        for (int x = 0; x < 240; x++)
            if (fb[y * 240 + x] == 0xFFFF) ink++;
    assert(ink > 50);

    /* Release and press the chord again: back to the game frame. */
    keys = 0;
    retrobilingual_process_input(&core, &keys, input_cb);
    keys = (1u << 9) | (1u << 2);
    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_state() == RB_STATE_GAME);
    assert(retrobilingual_should_run_frame(&core) == 1);

    /* X opens the menu and pauses; X closes it. */
    x_down = 1; keys = 0;
    retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_state() == RB_STATE_MENU);
    assert(retrobilingual_should_run_frame(&core) == 0);
    memset(fb, 0x11, sizeof(fb));
    retrobilingual_draw(&core, fb, 240, 160, 240 * 2);
    ink = 0;
    for (int y = 0; y < 160; y++)
        for (int x = 0; x < 240; x++)
            if (fb[y * 240 + x] == 0xFFFF) ink++;
    assert(ink > 20);
    x_down = 0; retrobilingual_process_input(&core, &keys, input_cb);
    x_down = 1; retrobilingual_process_input(&core, &keys, input_cb);
    assert(rb_test_state() == RB_STATE_GAME);
    assert(retrobilingual_should_run_frame(&core) == 1);

    puts("host overlay test: pack gate, page tracking, chord pause, subtitle and menu draw OK");
    return 0;
}
