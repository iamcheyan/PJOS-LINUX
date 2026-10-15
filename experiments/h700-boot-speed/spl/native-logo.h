#ifndef BASEOS_NATIVE_LOGO_H
#define BASEOS_NATIVE_LOGO_H

#define BASEOS_NATIVE_LOGO_MAGIC 0x31474f4cu
#define BASEOS_NATIVE_LOGO_RECORD_ADDRESS 0x4a300200u
#define BASEOS_NATIVE_LOGO_BMP_ADDRESS 0x4b400000u
#define BASEOS_NATIVE_LOGO_PIXEL_ADDRESS 0x4b000000u
#define BASEOS_NATIVE_LOGO_CAPACITY 0x00400000u

struct baseos_native_logo {
    unsigned int magic, bytes, fnv, reserved;
};
_Static_assert(sizeof(struct baseos_native_logo) == 16, "native logo descriptor ABI");

static inline unsigned int baseos_logo_hash(const unsigned char *bytes, unsigned int count)
{
    unsigned int hash = 2166136261u;
    while (count--) hash = (hash ^ *bytes++) * 16777619u;
    return hash;
}

#endif
