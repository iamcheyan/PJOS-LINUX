#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "native-logo.h"
#include "native-display.h"
#include "boot-logo-pixels.h"
#include "panel-spi9.h"
#include "early-display-generated.h"

enum display_operation_kind { DISPLAY_UPDATE, DISPLAY_WRITE, DISPLAY_FRAMEBUFFER,
                              DISPLAY_DELAY_US, DISPLAY_POLL, DISPLAY_BARRIER };
struct display_operation {
    uint32_t kind, address, clear_mask, set_bits, timeout_us;
};

/* Generated tables follow these declarations and contain only pinned constants. */
#include "early-display-operations.h"

static uint32_t read32(void *context, uint32_t address)
{
    (void)context;
    return *(volatile uint32_t *)(uintptr_t)address;
}

static void write32(void *context, uint32_t address, uint32_t value)
{
    (void)context;
    *(volatile uint32_t *)(uintptr_t)address = value;
}

static void barrier(void *context)
{
    (void)context;
    asm volatile("dmb sy" ::: "memory");
}

static uint64_t ticks(void)
{
    uint64_t value;
    asm volatile("mrs %0, cntpct_el0" : "=r"(value));
    return value;
}

static __attribute__((noinline)) int wait_us(uint32_t microseconds)
{
    uint64_t start = ticks();
    for (unsigned remaining = 100000000u; remaining; --remaining)
        if (ticks() - start >= (uint64_t)microseconds * 24u) return 0;
    return -1;
}

static void update(uint32_t address, uint32_t mask, uint32_t value)
{
    uint32_t old = read32(NULL, address);
    barrier(NULL);
    barrier(NULL);
    write32(NULL, address, (old & ~mask) | value);
}

static __attribute__((noinline)) int apply(const struct display_operation *operations, size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        const struct display_operation *op = &operations[i];
        if (op->kind == DISPLAY_BARRIER) {
            asm volatile("dsb sy" ::: "memory");
        } else if (op->kind == DISPLAY_DELAY_US) {
            if (wait_us(op->set_bits)) return -1;
        } else if (op->kind == DISPLAY_POLL) {
            uint64_t start = ticks();
            unsigned remaining = 100000000u;
            while ((read32(NULL, op->address) & op->clear_mask) != op->set_bits) {
                if (!--remaining || ticks() - start >= (uint64_t)op->timeout_us * 24u) return -1;
            }
        } else if (op->kind == DISPLAY_UPDATE) {
            update(op->address, op->clear_mask, op->set_bits);
        } else if (op->kind == DISPLAY_WRITE || op->kind == DISPLAY_FRAMEBUFFER) {
            barrier(NULL);
            write32(NULL, op->address, op->set_bits +
                    (op->kind == DISPLAY_FRAMEBUFFER ? BASEOS_NATIVE_LOGO_PIXEL_ADDRESS : 0));
        } else return -1;
    }
    asm volatile("dsb sy" ::: "memory");
    return 0;
}

static int prepare_panel(void)
{
    update(0x0300b124u, 0xff000000u, 0x11000000u);
    update(0x0300b130u, 0x8000u, 0x8000u);
    if (wait_us(30000)) return -1;
    update(0x0300b130u, 0x4000u, 0x4000u);
    if (wait_us(15000)) return -1;
    update(0x0300b130u, 0x4000u, 0);
    if (wait_us(50000)) return -1;
    update(0x0300b130u, 0x4000u, 0x4000u);
    if (wait_us(100000)) return -1;
    if (BASEOS_PANEL_RULE < 2) return BASEOS_PANEL_RULE;
    update(0x0300b090u, 0x0f000000u, 0x06000000u);
    if (BASEOS_PANEL_PULL_UP) update(0x0300b0acu, 0x3000u, 0x1000u);
    return !(read32(NULL, 0x0300b0a0u) & 0x40u);
}

static int initialize_panel(unsigned panel)
{
    struct baseos_panel_spi9 port = {{NULL, read32, write32, barrier}, 0};
    const uint16_t *stream = panel ? baseos_panel_boe : baseos_panel_old;
    size_t count = panel ? sizeof(baseos_panel_boe) / sizeof(*stream) : sizeof(baseos_panel_old) / sizeof(*stream);
    for (size_t i = 0; i < count; ++i) {
        unsigned op = stream[i];
        if (op & 0x8000u) {
            if (wait_us((op & 0x7fffu) * 1000u)) return -1;
        } else baseos_panel_spi9_send(&port, (uint8_t)op, op & 0x100u);
    }
    return 0;
}

static void clean_pixels(size_t bytes)
{
    uint64_t ctr;
    asm volatile("mrs %0, ctr_el0" : "=r"(ctr));
    uintptr_t line = (uintptr_t)4 << ((ctr >> 16) & 15);
    uintptr_t start = BASEOS_NATIVE_LOGO_PIXEL_ADDRESS;
    for (uintptr_t address = start & ~(line - 1); address < start + bytes; address += line)
        asm volatile("dc cvac, %0" :: "r"(address) : "memory");
    asm volatile("dsb sy" ::: "memory");
}

static int scanline_advances(void)
{
    uint32_t first = (read32(NULL, 0x065110fcu) >> 16) & 0xfffu;
    uint64_t start = ticks();
    for (unsigned remaining = 100000000u; remaining; --remaining) {
        if (((read32(NULL, 0x065110fcu) >> 16) & 0xfffu) != first) return 0;
        if (ticks() - start >= 2400000u) return -1;
    }
    return -1;
}

__attribute__((section(".text.entry"))) int baseos_early_display(const struct baseos_native_logo *logo)
{
    struct baseos_native_display *record = (void *)BASEOS_NATIVE_DISPLAY_ADDRESS;
    memset(record, 0, sizeof(*record));
    const unsigned char *bmp = (void *)BASEOS_NATIVE_LOGO_BMP_ADDRESS;
    size_t pixel_bytes = BASEOS_LOGO_WIDTH * BASEOS_LOGO_HEIGHT * 4u;
    if (logo->magic != BASEOS_NATIVE_LOGO_MAGIC || logo->reserved ||
        logo->bytes > BASEOS_NATIVE_LOGO_CAPACITY || !logo->bytes ||
        baseos_logo_hash(bmp, logo->bytes) != logo->fnv ||
        !baseos_logo_pixels(bmp, logo->bytes, BASEOS_LOGO_WIDTH, BASEOS_LOGO_HEIGHT,
                            (void *)BASEOS_NATIVE_LOGO_PIXEL_ADDRESS, BASEOS_NATIVE_LOGO_CAPACITY)) return -2;
    clean_pixels(pixel_bytes);
    /* Release the SRAM bridge exactly as stock does before display ownership. */
    update(0x03000000u, 0x7fffffffu, 0);
    update(0x03000004u, 0x01000000u, 0);
    asm volatile("dsb sy" ::: "memory");
    if (apply(baseos_display_prepare, sizeof(baseos_display_prepare) / sizeof(*baseos_display_prepare))) return -1;
    int panel = prepare_panel();
    if (panel < 0 || initialize_panel((unsigned)panel) || wait_us(50000) ||
        apply(baseos_display_publish, sizeof(baseos_display_publish) / sizeof(*baseos_display_publish)) ||
        apply(baseos_display_enable, sizeof(baseos_display_enable) / sizeof(*baseos_display_enable)) ||
        wait_us(100000) || scanline_advances() || apply(baseos_display_backlight,
                              sizeof(baseos_display_backlight) / sizeof(*baseos_display_backlight))) return -1;
    struct baseos_native_display next = {0};
    next.magic = BASEOS_NATIVE_DISPLAY_MAGIC;
    next.version = 1;
    next.bytes = sizeof(next);
    next.panel = (unsigned)panel;
    next.logo_bytes = logo->bytes;
    next.logo_fnv = logo->fnv;
    next.pixel_fnv = baseos_logo_hash((void *)BASEOS_NATIVE_LOGO_PIXEL_ADDRESS, (unsigned)pixel_bytes);
    memcpy(next.generation, baseos_generation, sizeof(next.generation));
    next.shown_ticks = ticks();
    next.fnv = baseos_display_hash(&next);
    memcpy((unsigned char *)record + 4, (const unsigned char *)&next + 4, sizeof(next) - 4);
    asm volatile("dsb sy" ::: "memory");
    record->magic = next.magic;
    asm volatile("dsb sy" ::: "memory");
    return panel;
}
