#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <libfdt.h>
#include "native-handoff.h"
#include "native-generated.h"
#ifdef BASEOS_NATIVE_DIAGNOSTIC
#include "native-trace-constants.h"
#endif

extern int custom_unpack(unsigned char *, unsigned long, const unsigned char *, unsigned long *);
extern void native_enable_mmu(void);
extern uint64_t native_ticks(void);
extern void native_kernel_enter(void) __attribute__((noreturn));

static char command_line[2048];
static uint64_t times[7];

static void checkpoint(unsigned stage)
{
#ifdef BASEOS_NATIVE_DIAGNOSTIC
    *(volatile uint32_t *)0x0700013c = 0x42530000u | stage;
    asm volatile("dsb sy" ::: "memory");
#else
    (void)stage;
#endif
}

static uint32_t little32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint32_t record_hash(const struct baseos_native_record *record)
{
    const unsigned char *p = (const void *)record;
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; i < sizeof(*record); i++)
        hash = (hash ^ (i >= 196 && i < 200 ? 0 : p[i])) * 16777619u;
    return hash;
}

#ifdef BASEOS_NATIVE_DIAGNOSTIC
static uint32_t byte_hash(const unsigned char *bytes, unsigned count)
{
    uint32_t hash = 2166136261u;
    while (count--) hash = (hash ^ *bytes++) * 16777619u;
    return hash;
}
#endif

static int checked_extent(uint32_t *offset, uint32_t bytes, uint32_t limit, uint32_t *begin)
{
    if (bytes > limit || bytes > limit - *offset || bytes > 0xfffff800u) return -1;
    uint32_t rounded = (bytes + 2047u) & ~2047u;
    if (rounded > limit - *offset) return -1;
    *begin = *offset;
    *offset += rounded;
    return 0;
}

static void hex_digits(char *out, uint32_t word, unsigned digits)
{
    for (unsigned i = 0; i < digits; i++)
        out[i] = "0123456789abcdef"[(word >> ((digits - 1 - i) * 4)) & 15];
}

static int make_command_line(const unsigned char *image)
{
    const struct baseos_native_record *record = (void *)BASEOS_NATIVE_RECORD_ADDRESS;
    static const char *const reasons[] = {"button", "irq", "usb", "charger", "battery", "unknow"};
    volatile uint32_t *sid = (void *)0x03006000;
    char serial[20];
    hex_digits(serial, sid[0x204 / 4] >> 20, 3);
    hex_digits(serial + 3, sid[0x208 / 4], 8);
    hex_digits(serial + 11, sid[0x20c / 4], 8);
    serial[19] = 0;
    const char *panel = BASEOS_PANEL_RULE == 0 ? "old" : "boe";
    if (BASEOS_PANEL_RULE == 2) {
        volatile uint32_t *pio = (void *)0x0300b000;
        pio[0x90 / 4] &= ~(15u << 24);
        pio[0xac / 4] = (pio[0xac / 4] & ~(3u << 12)) | (1u << 12);
        asm volatile("dmb sy" ::: "memory");
        panel = pio[0xa0 / 4] & 0x40 ? "old" : "boe";
    }
    /* Android v2 has two separately bounded command-line fields. */
    char android[1537];
    size_t first = strnlen((const char *)image + 64, 512);
    size_t extra = strnlen((const char *)image + 608, 1024);
    if (first == 512 || extra == 1024) return -1;
    memcpy(android, image + 64, first);
    memcpy(android + first, image + 608, extra);
    android[first + extra] = 0;
    size_t used = 0;
    for (const char *p = baseos_bootargs_template; *p;) {
        const char *value = NULL;
        unsigned skip = 0;
        if (!strncmp(p, "@SERIAL@", 8)) { value = serial; skip = 8; }
        else if (!strncmp(p, "@PANEL@", 7)) { value = panel; skip = 7; }
        else if (!strncmp(p, "@ANDROID@", 9)) { value = android; skip = 9; }
        else if (!strncmp(p, "@BOOTREASON@", 12)) { value = reasons[record->boot_reason]; skip = 12; }
        if (value) {
            size_t bytes = strlen(value);
            if (bytes >= sizeof(command_line) - used) return -1;
            memcpy(command_line + used, value, bytes);
            used += bytes;
            p += skip;
        } else {
            if (used + 1 >= sizeof(command_line)) return -1;
            command_line[used++] = *p++;
        }
    }
    command_line[used] = 0;
    return 0;
}

int baseos_prepare_kernel(void)
{
    const struct baseos_native_record *record = (void *)BASEOS_NATIVE_RECORD_ADDRESS;
    const unsigned char *image = (void *)BASEOS_NATIVE_IMAGE_ADDRESS;
    if (record->magic != BASEOS_NATIVE_MAGIC || record->version != BASEOS_NATIVE_RECORD_VERSION ||
        record->bytes != sizeof(*record) || record->model != BASEOS_MODEL_ID ||
        record->image_bytes != BASEOS_IMAGE_BYTES || record->image_fnv != BASEOS_IMAGE_FNV ||
        memcmp(record->generation, baseos_generation, 32) || record_hash(record) != record->record_fnv ||
        record->ram_bytes < 0x10000000ull || record->ram_bytes != (uint64_t)(record->dram_words[7] >> 16) << 20 ||
        record->dram_type != record->dram_words[1] ||
        !baseos_boot_reason_valid(record->boot_reason, record->boot_reason_source)) return 1;
    if (record->image_bytes < 2048 || record->image_bytes > BASEOS_NATIVE_IMAGE_CAPACITY ||
        memcmp(image, "ANDROID!", 8) || little32(image + 36) != 2048 ||
        little32(image + 40) != 2 || little32(image + 1644) != 1660 ||
        little32(image + 24) || little32(image + 1632)) return 2;
    uint32_t kernel_bytes = little32(image + 8), initrd_bytes = little32(image + 16);
    uint32_t dtb_bytes = little32(image + 1648), offset = 2048, kernel, initrd, dtb;
    if (!kernel_bytes || !dtb_bytes || initrd_bytes > 0x100000 || dtb_bytes > BASEOS_NATIVE_FDT_CAPACITY ||
        checked_extent(&offset, kernel_bytes, record->image_bytes, &kernel) ||
        checked_extent(&offset, initrd_bytes, record->image_bytes, &initrd) ||
        checked_extent(&offset, dtb_bytes, record->image_bytes, &dtb) ||
        offset != record->image_bytes) return 3;
    times[0] = record->started_ticks;
    times[1] = record->read_started_ticks;
    times[2] = record->loaded_ticks;
    times[3] = native_ticks();
    checkpoint(44);
    unsigned long output_bytes = kernel_bytes;
    if (custom_unpack((void *)0x40080000, 0x01f80000, image + kernel, &output_bytes)) return 4;
#ifdef BASEOS_NATIVE_DIAGNOSTIC
    if (output_bytes != BASEOS_KERNEL_BYTES ||
        byte_hash((void *)0x40080000, output_bytes) != BASEOS_KERNEL_FNV) return 12;
#endif
    times[4] = native_ticks();
    checkpoint(45);
    if (output_bytes < 64 || little32((const void *)0x40080038) != 0x644d5241) return 5;
    memcpy((void *)0x42000000, image + initrd, initrd_bytes);
    void *tree = (void *)BASEOS_NATIVE_FDT_ADDRESS;
    if (fdt_check_full(image + dtb, dtb_bytes) ||
        fdt_open_into(image + dtb, tree, BASEOS_NATIVE_FDT_CAPACITY)) return 6;
    int dram = fdt_path_offset(tree, "/dram");
    for (unsigned i = 0; i < 24; i++)
        if (fdt_setprop_u32(tree, dram, baseos_dram_properties[i], record->dram_words[i])) return 7;
    int memory = fdt_path_offset(tree, "/memory@40000000");
    fdt64_t memory_reg[2] = {cpu_to_fdt64(0x40000000), cpu_to_fdt64(record->ram_bytes)};
    if (fdt_setprop(tree, memory, "reg", memory_reg, sizeof(memory_reg))) return 8;
    int chosen = fdt_path_offset(tree, "/chosen");
    if (make_command_line(image) ||
        fdt_setprop_string(tree, chosen, "bootargs", command_line) ||
        fdt_setprop_u64(tree, chosen, "linux,initrd-start", 0x42000000) ||
        fdt_setprop_u64(tree, chosen, "linux,initrd-end", 0x42000000 + initrd_bytes) ||
        fdt_add_mem_rsv(tree, 0x42000000, initrd_bytes) ||
        fdt_setprop(tree, chosen, "baseos,native-boot", record->generation, 32)) return 9;
    /* Image input carries BaseOS's late USB policy; retain the proved HDMI deferral. */
    int hdmi = fdt_path_offset(tree, "/soc@03000000/hdmi@06000000");
    if (hdmi >= 0 && fdt_setprop_string(tree, hdmi, "status", "late")) return 10;
    times[5] = native_ticks();
    times[6] = native_ticks();
    fdt64_t stamps[7];
    for (unsigned i = 0; i < 7; i++) stamps[i] = cpu_to_fdt64(times[i]);
    if (fdt_setprop(tree, chosen, "baseos,native-timing", stamps, sizeof(stamps))) return 11;
#ifdef BASEOS_NATIVE_DIAGNOSTIC
    volatile uint32_t *proof = (void *)0x4a300100;
    proof[0] = fdt_totalsize(tree);
    proof[1] = byte_hash(tree, proof[0]);
#endif
    checkpoint(46);
    return 0;
}

static __attribute__((noinline)) void release_display_sram(void)
{
    volatile uint32_t *system = (void *)0x03000000;
    system[0] &= 1u << 31;
    system[1] &= ~(1u << 24);
    asm volatile("dsb sy" ::: "memory");
}

void baseos_loader_boot(void)
{
    checkpoint(41);
    volatile uint32_t *table = (void *)0x4a0f8000;
    for (unsigned i = 0; i < 4096; i++)
        table[i] = (i << 20) | (i == 0 || (i >= 0x400 && i < 0x500) ? 0x1c0e : 0x10c16);
    checkpoint(42);
    native_enable_mmu();
    checkpoint(43);
    int error = baseos_prepare_kernel();
    if (!error) {
        release_display_sram();
        checkpoint(47);
        native_kernel_enter();
    }
    checkpoint(0x8000u | error);
    /* Bring-up uses the already established restore-first watchdog recovery. */
    for (;;) asm volatile("wfi");
}
