/* RetroBilingual mGBA core integration.
 * SPDX-License-Identifier: MPL-2.0
 */
#ifndef RETROBILINGUAL_H
#define RETROBILINGUAL_H

#include <stdint.h>

struct mCore;
typedef int16_t (*retro_input_state_t)(unsigned port, unsigned device, unsigned index, unsigned id);

/* Set the loaded ROM path to allow companion translation pack discovery. */
void retrobilingual_set_rom_path(const char* path);

/* Filter game input, detect the X menu key and the subtitle chord. */
void retrobilingual_process_input(struct mCore* core, uint16_t* keys, retro_input_state_t input);

/* False while the menu or the subtitle overlay is holding the game. */
int retrobilingual_should_run_frame(struct mCore* core);

/* Composite menu or subtitle into the GBA framebuffer before video_cb. */
void retrobilingual_draw(struct mCore* core, void* pixels, unsigned width, unsigned height, unsigned pitch);

typedef enum {
    RB_FILTER_OFF = 0,
    RB_FILTER_LCD_GRID = 1,
    RB_FILTER_GBA_COLOR = 2,
    RB_FILTER_LCD_COLOR = 3,
    RB_FILTER_CRT_SCANLINE = 4,
    RB_FILTER_SUBPIXEL_RGB = 5,
    RB_FILTER_GB_DMG = 6,
    RB_FILTER_GB_POCKET = 7,
    RB_FILTER_COUNT = 8
} RBVisualFilter;

/* Output post-processed 720x480 frame for libretro videoCallback */
void retrobilingual_present(void* in_pixels, unsigned in_w, unsigned in_h, unsigned in_pitch,
                            void** out_pixels, unsigned* out_w, unsigned* out_h, unsigned* out_pitch);

#endif
