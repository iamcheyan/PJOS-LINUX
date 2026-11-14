/* Host-test stubs for compiling src/retrobilingual.c without mGBA. */
#ifndef RB_HOST_STUBS_H
#define RB_HOST_STUBS_H

#include <stddef.h>
#include <stdint.h>

typedef int16_t (*retro_input_state_t)(unsigned port, unsigned device, unsigned index, unsigned id);

enum {
    RETRO_DEVICE_JOYPAD = 1,
    RETRO_DEVICE_ID_JOYPAD_B = 0,
    RETRO_DEVICE_ID_JOYPAD_Y = 1,
    RETRO_DEVICE_ID_JOYPAD_SELECT = 2,
    RETRO_DEVICE_ID_JOYPAD_START = 3,
    RETRO_DEVICE_ID_JOYPAD_UP = 4,
    RETRO_DEVICE_ID_JOYPAD_DOWN = 5,
    RETRO_DEVICE_ID_JOYPAD_LEFT = 6,
    RETRO_DEVICE_ID_JOYPAD_RIGHT = 7,
    RETRO_DEVICE_ID_JOYPAD_A = 8,
    RETRO_DEVICE_ID_JOYPAD_X = 9,
    RETRO_DEVICE_ID_JOYPAD_L = 10,
    RETRO_DEVICE_ID_JOYPAD_R = 11,
};

struct GBA {
    struct {
        uint8_t* rom;
        uint32_t* wram;
        size_t romSize;
    } memory;
    uint32_t romCrc32;
};

struct VFile {
    void (*close)(struct VFile*);
};

struct mCore {
    void* board;
    size_t (*stateSize)(struct mCore*);
    int (*saveState)(struct mCore*, void*);
    int (*loadState)(struct mCore*, const void*);
};

static inline struct VFile* VFileOpen(const char* path, int flags) {
    (void)path;
    (void)flags;
    return NULL;
}
static inline int mCoreSaveStateNamed(struct mCore* core, struct VFile* vf, int flags) {
    (void)core;
    (void)vf;
    (void)flags;
    return 0;
}
static inline int mCoreLoadStateNamed(struct mCore* core, struct VFile* vf, int flags) {
    (void)core;
    (void)vf;
    (void)flags;
    return 0;
}

#endif
