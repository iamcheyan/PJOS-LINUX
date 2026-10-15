/* MMC and all mutable SPL state end here, before the vendor monitor reset. */
#include <mmc.h>
#include <blk.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <asm/arch/pmic_bus.h>
#include <linux/string.h>
#include "native-handoff.h"
#include "native-generated.h"
#include "native-logo.h"
#include "native-display.h"
#include "boot-logo-file.h"
#ifdef BASEOS_RAW_CAPSULE
#include "raw-capsule-generated.h"
#endif

DECLARE_GLOBAL_DATA_PTR;
extern int baseos_dram_power;
extern u32 dram_probe_attempts, dram_probe_selected_type;
extern const u32 *baseos_selected_vendor_params(void);
extern void sunxi_board_init(void);
extern void baseos_checkpoint(struct blk_desc *, u32);
extern int baseos_native_cache_on(void);
extern void baseos_native_cache_off(void);

int baseos_native_bootreason(unsigned int *reason, unsigned int *source)
{
    u8 value;
    *reason = BASEOS_BOOT_UNKNOWN;
    *source = BASEOS_BOOT_SOURCE_UNKNOWN;
    if (!pmic_bus_read(0x20, &value)) {
        switch (value) {
        case 1: *reason = BASEOS_BOOT_BUTTON; break;
        case 2: *reason = BASEOS_BOOT_IRQ; break;
        case 4:
            *reason = !pmic_bus_read(0, &value) && (value & 8) ?
                BASEOS_BOOT_CHARGER : BASEOS_BOOT_USB;
            break;
        case 8: *reason = BASEOS_BOOT_CHARGER; break;
        case 16: *reason = BASEOS_BOOT_BATTERY; break;
        }
    }
    if (*reason != BASEOS_BOOT_UNKNOWN) {
        *source = BASEOS_BOOT_SOURCE_POWERON;
    } else if (!pmic_bus_read(0xf0, &value) && (value & 8)) {
        /* Vendor consumes this whole scratch byte, only for unknown startup. */
        if (pmic_bus_write(0xf0, 0)) return -1;
        *reason = BASEOS_BOOT_CHARGER;
        *source = BASEOS_BOOT_SOURCE_PMU_FALLBACK;
    }
    return 0;
}

static void baseos_vendor_pll_power(void)
{
    /* The vendor kernel gates these outputs at bit 27; boot0 supplies bit 31. */
    static const u16 offsets[] = {0x28, 0x30, 0x40, 0x48, 0x50, 0x58, 0x60, 0xe0, 0x78};
    for (unsigned int i = 0; i < ARRAY_SIZE(offsets); i++) {
        void *reg = (void *)(0x03001000ul + offsets[i]);
        writel(readl(reg) | BIT(31), reg);
    }
}

static u32 fnv(const u8 *bytes, unsigned int size)
{
    u32 hash = 2166136261u;
    for (unsigned int i = 0; i < size; i += 4) {
        u32 word = *(const u32 *)(bytes + i);
        for (unsigned shift = 0; shift < 32; shift += 8)
            hash = (hash ^ (word >> shift & 255)) * 16777619u;
    }
    return hash;
}

static int logo_read(void *context, uint32_t lba, uint32_t blocks, void *output)
{
    return blk_dread(context, lba, blocks, output) == blocks;
}

static void load_boot_logo(struct blk_desc *card)
{
    struct baseos_native_logo *logo = (void *)BASEOS_NATIVE_LOGO_RECORD_ADDRESS;
    memset(logo, 0, sizeof(*logo));
    const struct baseos_logo_io io = {card, logo_read};
    uint32_t bytes = 0;
    unsigned char *bmp = (void *)BASEOS_NATIVE_LOGO_BMP_ADDRESS;
    if (!baseos_logo_file(&io, BASEOS_LOGO_PARTITION_SECTOR, BASEOS_LOGO_PARTITION_SECTORS,
                         bmp, BASEOS_NATIVE_LOGO_CAPACITY, &bytes)) return;
    logo->bytes = bytes;
    logo->fnv = baseos_logo_hash(bmp, bytes);
    asm volatile("dmb sy" ::: "memory");
    logo->magic = BASEOS_NATIVE_LOGO_MAGIC;
}

int baseos_vendor_handoff(struct blk_desc *card, u32 *result, const u8 *stock)
{
#ifdef BASEOS_RAW_CAPSULE
    (void)stock;
    const u8 *board = baseos_raw_board;
#else
    const u8 *board = stock + 0xf0;
#endif
    u64 level, started, reading, loaded;
    asm volatile("mrs %0, CurrentEL; mrs %1, cntpct_el0" : "=r"(level), "=r"(started));
    if (level != 12 || result[46] != 16) return -1;
    baseos_checkpoint(card, 30);
    baseos_dram_power = 1;
    sunxi_board_init();
    unsigned int boot_reason, boot_reason_source;
    if (baseos_native_bootreason(&boot_reason, &boot_reason_source)) return -1;
    baseos_vendor_pll_power();
    result[9] = gd->ram_size;
    result[40] = dram_probe_attempts;
    result[41] = dram_probe_selected_type;
    baseos_checkpoint(card, 31);
    if (gd->ram_size < 0x10000000ul || baseos_native_cache_on()) return -1;
    asm volatile("mrs %0, cntpct_el0" : "=r"(reading));
    struct baseos_native_display *display = (void *)BASEOS_NATIVE_DISPLAY_ADDRESS;
    memset(display, 0, sizeof(*display));
    load_boot_logo(card);
    u8 *package = (void *)0x42e00000;
    if (blk_dread(card, BASEOS_FIRMWARE_SECTOR, BASEOS_FIRMWARE_BYTES / 512, package) != BASEOS_FIRMWARE_BYTES / 512 ||
        fnv(package, BASEOS_FIRMWARE_BYTES) != BASEOS_FIRMWARE_FNV) return -1;
    for (unsigned i = 0; i < ARRAY_SIZE(baseos_firmware_extents); i++) {
        const struct baseos_firmware_extent *item = &baseos_firmware_extents[i];
        if (item->offset > BASEOS_FIRMWARE_BYTES || item->bytes > BASEOS_FIRMWARE_BYTES - item->offset) return -1;
        memcpy((void *)(ulong)item->destination, package + item->offset, item->bytes);
    }
    if (blk_dread(card, BASEOS_IMAGE_SECTOR, BASEOS_IMAGE_BYTES / 512,
                  (void *)BASEOS_NATIVE_IMAGE_ADDRESS) != BASEOS_IMAGE_BYTES / 512 ||
        fnv((void *)BASEOS_NATIVE_IMAGE_ADDRESS, BASEOS_IMAGE_BYTES) != BASEOS_IMAGE_FNV) return -1;
    asm volatile("mrs %0, cntpct_el0" : "=r"(loaded));
    baseos_checkpoint(card, 32);
    u8 *uboot = (void *)0x4a000000, *monitor = (void *)0x48000000;
    const u32 *parameters = baseos_selected_vendor_params();
    memcpy(uboot + 0x30, parameters, 128);
    *(u32 *)(uboot + 0x4f8) = gd->ram_size >> 20;
    *(u32 *)(uboot + 0x4f4) = 0x140000;
    *(u32 *)(uboot + 0xe4) = 1;
    uboot[0x4e8] = 0;
    uboot[0x4e9] = 1;
    uboot[0x4ea] = 0;
    memcpy(monitor + 0x30, parameters, 128);
    memcpy(monitor + 0x24, board, 8);
    *(u32 *)(monitor + 0xb0) = 0x4a200000;
    struct baseos_native_record *record = (void *)BASEOS_NATIVE_RECORD_ADDRESS;
    memset(record, 0, sizeof(*record));
    record->magic = BASEOS_NATIVE_MAGIC;
    record->version = BASEOS_NATIVE_RECORD_VERSION;
    record->bytes = sizeof(*record);
    record->model = BASEOS_MODEL_ID;
    record->ram_bytes = gd->ram_size;
    record->started_ticks = started;
    record->read_started_ticks = reading;
    record->loaded_ticks = loaded;
    record->dram_type = dram_probe_selected_type;
    memcpy(record->dram_words, parameters, 128);
    memcpy(record->board, board, 8);
    record->image_bytes = BASEOS_IMAGE_BYTES;
    record->image_fnv = BASEOS_IMAGE_FNV;
    memcpy(record->generation, baseos_generation, 32);
    record->boot_reason = boot_reason;
    record->boot_reason_source = boot_reason_source;
    record->record_fnv = fnv((void *)record, sizeof(*record));
    baseos_checkpoint(card, 34);
#if !defined(BASEOS_PERSISTENT) && !defined(BASEOS_RAW_CAPSULE)
    writel(0x42530022, (void *)0x0700013c);
#endif
#ifdef BASEOS_RAW_CAPSULE
    extern void baseos_raw_adopt(void);
    baseos_raw_adopt();
#endif
    writel(0x14af, (void *)0x030090b0);
    baseos_native_cache_off();
#if !defined(BASEOS_PERSISTENT) && !defined(BASEOS_RAW_CAPSULE)
    writel(0x42530023, (void *)0x0700013c);
#endif
    ulong rvbar = (readl((void *)0x03000024) & 7) == 2 ? 0x08100040 : 0x09010040;
    writel(0x48000000, (void *)rvbar);
    writel(0, (void *)(rvbar + 4));
#if !defined(BASEOS_PERSISTENT) && !defined(BASEOS_RAW_CAPSULE)
    writel(0x42530024, (void *)0x0700013c);
#endif
    asm volatile("dsb sy; isb; mov x0, %0; movz x1, #0x44; movk x1, #0x810, lsl #16; "
                 "mov x2, #3; mov x3, %1; msr rmr_el3, x2; isb; 1: wfi; b 1b"
                 :: "r"(0x48000000ul), "r"(rvbar + 4) : "x0", "x1", "x2", "x3", "memory");
    return -1;
}
