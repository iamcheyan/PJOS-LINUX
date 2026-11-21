#include "adapters/adapter.h"

#include <string.h>

static int rom_matches(uint32_t size, const uint8_t sha256[32],
                       const RBAdapter* adapter) {
    if (size != adapter->rom_size || !sha256) return 0;
    uint8_t expected[32];
    for (unsigned i = 0; i < sizeof(expected); i++) {
        unsigned hi = (unsigned char)adapter->sha256_hex[i * 2];
        unsigned lo = (unsigned char)adapter->sha256_hex[i * 2 + 1];
        hi = hi >= '0' && hi <= '9' ? hi - '0' : hi - 'a' + 10;
        lo = lo >= '0' && lo <= '9' ? lo - '0' : lo - 'a' + 10;
        expected[i] = (uint8_t)((hi << 4) | lo);
    }
    return memcmp(sha256, expected, sizeof(expected)) == 0;
}

const RBAdapter* rb_adapter_match(uint32_t rom_size, const uint8_t sha256[32]) {
    if (rom_matches(rom_size, sha256, &g_rb_adapter_tmc)) return &g_rb_adapter_tmc;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_golden_sun))
        return &g_rb_adapter_golden_sun;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_golden_sun_rg34xx))
        return &g_rb_adapter_golden_sun_rg34xx;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_golden_sun_cn2024))
        return &g_rb_adapter_golden_sun_cn2024;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_fe6)) return &g_rb_adapter_fe6;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_fe7)) return &g_rb_adapter_fe7;
    if (rom_matches(rom_size, sha256, &g_rb_adapter_fe8)) return &g_rb_adapter_fe8;
    return 0;
}
