#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <linux/input.h>
#include <sys/stat.h>

#define STATE_DIR "/run"
#define FALLBACK_DIR "/tmp"

static int get_current_volume(void) {
    int vol = 70;
    FILE *f = fopen(STATE_DIR "/baseos-volume.percent", "r");
    if (!f) f = fopen(FALLBACK_DIR "/baseos-volume.percent", "r");
    if (f) {
        if (fscanf(f, "%d", &vol) != 1) vol = 70;
        fclose(f);
    }
    if (vol < 0) vol = 0;
    if (vol > 100) vol = 100;
    return vol;
}

static unsigned long get_current_sequence(void) {
    unsigned long seq = 0;
    FILE *f = fopen(STATE_DIR "/baseos-volume.sequence", "r");
    if (!f) f = fopen(FALLBACK_DIR "/baseos-volume.sequence", "r");
    if (f) {
        if (fscanf(f, "%lu", &seq) != 1) seq = 0;
        fclose(f);
    }
    return seq;
}

static void apply_volume(int vol) {
    if (vol < 0) vol = 0;
    if (vol > 100) vol = 100;

    /* Write percentage */
    FILE *f = fopen(STATE_DIR "/baseos-volume.percent", "w");
    if (f) { fprintf(f, "%d\n", vol); fclose(f); }
    f = fopen(FALLBACK_DIR "/baseos-volume.percent", "w");
    if (f) { fprintf(f, "%d\n", vol); fclose(f); }

    /* Increment sequence to notify HUD */
    unsigned long seq = get_current_sequence() + 1;
    f = fopen(STATE_DIR "/baseos-volume.sequence", "w");
    if (f) { fprintf(f, "%lu\n", seq); fclose(f); }
    f = fopen(FALLBACK_DIR "/baseos-volume.sequence", "w");
    if (f) { fprintf(f, "%lu\n", seq); fclose(f); }

    /* Set ALSA volume:
     * TrimUI Allwinner A133 sndcodec:
     * LINEOUT volume: range 0-31
     * Headphone: range 0-7
     */
    int lineout = (vol * 31 + 50) / 100;
    int hp = (vol * 7 + 50) / 100;
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "amixer -q -c 0 sset 'LINEOUT volume' %d >/dev/null 2>&1 &", lineout);
    system(cmd);
    snprintf(cmd, sizeof(cmd), "amixer -q -c 0 sset 'Headphone' %d >/dev/null 2>&1 &", hp);
    system(cmd);
}

int main(int argc, char **argv) {
    const char *dev = argc > 1 ? argv[1] : "/dev/input/event0";
    int fd = open(dev, O_RDONLY);
    if (fd < 0) {
        perror("open event0");
        return 1;
    }

    if (daemon(1, 0) < 0) {
        perror("daemon");
        return 1;
    }

    struct input_event ev;
    int current_vol = get_current_volume();
    apply_volume(current_vol);

    while (read(fd, &ev, sizeof(ev)) == sizeof(ev)) {
        if (ev.type == EV_KEY && (ev.value == 1 || ev.value == 2)) {
            if (ev.code == KEY_VOLUMEUP) {
                current_vol = get_current_volume() + 5;
                if (current_vol > 100) current_vol = 100;
                apply_volume(current_vol);
            } else if (ev.code == KEY_VOLUMEDOWN) {
                current_vol = get_current_volume() - 5;
                if (current_vol < 0) current_vol = 0;
                apply_volume(current_vol);
            }
        }
    }

    close(fd);
    return 0;
}
