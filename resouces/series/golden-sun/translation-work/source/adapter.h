#ifndef RB_ADAPTER_H
#define RB_ADAPTER_H

#include <stdint.h>
#include <stddef.h>

struct mCore;

typedef struct {
    const char* game_id;
    const char* title;
    uint32_t rom_size;
    const char* sha256_hex;
    /* Reset adapter internal state (e.g. on game reset or state load) */
    void (*reset)(void);
    /* Returns 1 if active dialogue text is found, 0 otherwise.
     * keys is the current RetroPad key bitmask; adapters that track pages may
     * consume it. */
    int (*read_dialogue)(struct mCore* core, uint16_t keys,
                         uint16_t* out_text_id, uint8_t* out_page);
    /* Page indices advance on A presses for this game, so a stale index may
     * overshoot the built pages while the next message is loading. */
    uint8_t page_slack;
} RBAdapter;

/* Built-in game adapters */
extern const RBAdapter g_rb_adapter_tmc;
extern const RBAdapter g_rb_adapter_golden_sun;
extern const RBAdapter g_rb_adapter_golden_sun_rg34xx;
extern const RBAdapter g_rb_adapter_golden_sun_cn2024;
const RBAdapter* rb_adapter_match(uint32_t rom_size, const uint8_t sha256[32]);

#endif /* RB_ADAPTER_H */
