#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <linux/input.h>
#include <sys/stat.h>
#include <sys/wait.h>

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

static const char *volume_control;

static void apply_volume(int vol) {
    char level[4];
    snprintf(level, sizeof(level), "%d", vol);
    pid_t child = fork();
    if (child == 0) {
        execl(volume_control, volume_control, "volume", level, "--no-beep", (char *)NULL);
        _exit(127);
    }
    if (child > 0) {
        while (waitpid(child, NULL, 0) < 0 && errno == EINTR) {}
    }
}

int main(int argc, char **argv) {
    if (argc != 3 || argv[2][0] != '/') {
        fprintf(stderr, "usage: trimui-volumed <volume-input-node> <volume-control>\n");
        return 1;
    }
    volume_control = argv[2];
    int fd = open(argv[1], O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        perror(argv[1]);
        return 1;
    }

    if (daemon(1, 0) < 0) {
        perror("daemon");
        return 1;
    }

    int pid_fd = open("/tmp/trimui-volumed.pid", O_RDWR | O_CREAT, 0644);
    if (pid_fd >= 0) {
        if (lockf(pid_fd, F_TLOCK, 0) < 0) {
            /* Already running */
            return 0;
        }
        if (ftruncate(pid_fd, 0) == 0) {
            char pbuf[32];
            int plen = snprintf(pbuf, sizeof(pbuf), "%d\n", getpid());
            (void)write(pid_fd, pbuf, plen);
        }
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
