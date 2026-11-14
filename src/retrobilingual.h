/* RetroBilingual mGBA core integration.
 * SPDX-License-Identifier: MPL-2.0
 */
#ifndef RETROBILINGUAL_H
#define RETROBILINGUAL_H

#include <stdint.h>

struct mCore;
typedef int16_t (*retro_input_state_t)(unsigned port, unsigned device, unsigned index, unsigned id);

/* Filter game input, detect the X menu key and the subtitle chord. */
void retrobilingual_process_input(struct mCore* core, uint16_t* keys, retro_input_state_t input);

/* False while the menu or the subtitle overlay is holding the game. */
int retrobilingual_should_run_frame(struct mCore* core);

/* Composite menu or subtitle into the GBA framebuffer before video_cb. */
void retrobilingual_draw(struct mCore* core, void* pixels, unsigned width, unsigned height, unsigned pitch);

#endif
