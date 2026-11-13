#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <linux/input.h>

static int send_ipc(const char *sock_path, const char *json_cmd) {
    if (!sock_path || !*sock_path) return -1;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    write(fd, json_cmd, strlen(json_cmd));
    write(fd, "\n", 1);
    close(fd);
    return 0;
}

static int read_volume(void) {
    FILE *f = fopen("/run/baseos-volume.percent", "r");
    if (!f) return 50;
    int val = 50;
    if (fscanf(f, "%d", &val) != 1) val = 50;
    fclose(f);
    if (val < 0) val = 0;
    if (val > 100) val = 100;
    return val;
}

static void step_volume(int delta) {
    int cur = read_volume();
    int next = cur + delta;
    if (next < 0) next = 0;
    if (next > 100) next = 100;
    char cmd[128];
    snprintf(cmd, sizeof(cmd), "/storage/System/compat/bin/heya-control volume %d >/dev/null 2>&1 &", next);
    system(cmd);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: baseos-mpv-keys <mpv_pid> [ipc_sock]\n");
        return 1;
    }
    pid_t mpv_pid = (pid_t)atoi(argv[1]);
    const char *sock_path = (argc > 2) ? argv[2] : NULL;

    int fd1 = open("/dev/input/event1", O_RDONLY | O_NONBLOCK);
    int fd2 = open("/dev/input/event2", O_RDONLY | O_NONBLOCK);
    int fd3 = open("/dev/input/event3", O_RDONLY | O_NONBLOCK);

    struct pollfd pfds[3];
    int n_pfds = 0;
    if (fd1 >= 0) { pfds[n_pfds].fd = fd1; pfds[n_pfds].events = POLLIN; n_pfds++; }
    if (fd2 >= 0) { pfds[n_pfds].fd = fd2; pfds[n_pfds].events = POLLIN; n_pfds++; }
    if (fd3 >= 0) { pfds[n_pfds].fd = fd3; pfds[n_pfds].events = POLLIN; n_pfds++; }

    if (n_pfds == 0) {
        fprintf(stderr, "baseos-mpv-keys: no input devices\n");
        return 1;
    }

    struct input_event ev;
    while (kill(mpv_pid, 0) == 0) {
        int ret = poll(pfds, n_pfds, 200);
        if (ret < 0 && errno == EINTR) continue;
        if (ret <= 0) continue;

        for (int i = 0; i < n_pfds; i++) {
            if (!(pfds[i].revents & POLLIN)) continue;
            while (read(pfds[i].fd, &ev, sizeof(ev)) == sizeof(ev)) {
                if (ev.type == EV_KEY && ev.value == 1) { // Key down
                    switch (ev.code) {
                        case 305: // Physical B on RG34XX (Back): QUIT playback
                        case 310: // BTN_TL (Physical Select)
                        case 311: // BTN_TR (Physical Start)
                        case 1:   // KEY_ESC
                            send_ipc(sock_path, "{\"command\":[\"quit\"]}");
                            kill(mpv_pid, SIGTERM);
                            return 0;

                        case 304: // Physical A on RG34XX (Confirm): PAUSE / RESUME
                        case 57:  // KEY_SPACE
                        case 28:  // KEY_ENTER
                            send_ipc(sock_path, "{\"command\":[\"cycle\",\"pause\"]}");
                            break;

                        case 103: // KEY_UP
                        case 115: // KEY_VOLUMEUP
                            send_ipc(sock_path, "{\"command\":[\"add\",\"volume\",5]}");
                            step_volume(5);
                            break;

                        case 108: // KEY_DOWN
                        case 114: // KEY_VOLUMEDOWN
                            send_ipc(sock_path, "{\"command\":[\"add\",\"volume\",-5]}");
                            step_volume(-5);
                            break;

                        case 105: // KEY_LEFT
                        case 314: // BTN_TL2 / L shoulder
                            send_ipc(sock_path, "{\"command\":[\"seek\",-5,\"relative\"]}");
                            break;

                        case 106: // KEY_RIGHT
                        case 315: // BTN_TR2 / R shoulder
                            send_ipc(sock_path, "{\"command\":[\"seek\",5,\"relative\"]}");
                            break;
                    }
                } else if (ev.type == EV_ABS) {
                    if (ev.code == 0x11) { // ABS_HAT0Y (D-pad vertical)
                        if (ev.value < 0) {
                            send_ipc(sock_path, "{\"command\":[\"add\",\"volume\",5]}");
                            step_volume(5);
                        } else if (ev.value > 0) {
                            send_ipc(sock_path, "{\"command\":[\"add\",\"volume\",-5]}");
                            step_volume(-5);
                        }
                    } else if (ev.code == 0x10) { // ABS_HAT0X (D-pad horizontal)
                        if (ev.value < 0) {
                            send_ipc(sock_path, "{\"command\":[\"seek\",-5,\"relative\"]}");
                        } else if (ev.value > 0) {
                            send_ipc(sock_path, "{\"command\":[\"seek\",5,\"relative\"]}");
                        }
                    }
                }
            }
        }
    }

    if (fd1 >= 0) close(fd1);
    if (fd2 >= 0) close(fd2);
    if (fd3 >= 0) close(fd3);
    return 0;
}
