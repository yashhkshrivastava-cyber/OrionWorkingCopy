#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static void log_line(const char *msg) {
    const char *home = getenv("HOME");
    if (!home) {
        return;
    }
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/Library/Logs/Orion-launch.log", home);
    FILE *file = fopen(path, "a");
    if (!file) {
        return;
    }
    time_t now = time(NULL);
    fprintf(file, "%ld  %s\n", (long)now, msg);
    fclose(file);
}

int main(void) {
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) {
        log_line("could not resolve executable path");
        return 1;
    }

    char resolved[PATH_MAX];
    if (realpath(exe, resolved) == NULL) {
        strncpy(resolved, exe, sizeof(resolved) - 1);
        resolved[sizeof(resolved) - 1] = '\0';
    }

    char dirbuf[PATH_MAX];
    strncpy(dirbuf, resolved, sizeof(dirbuf) - 1);
    dirbuf[sizeof(dirbuf) - 1] = '\0';
    char *dir = dirname(dirbuf);

    char script[PATH_MAX];
    snprintf(script, sizeof(script), "%s/launch", dir);
    log_line(script);

    if (access(script, X_OK) != 0) {
        log_line("launch script missing or not executable");
        return 1;
    }

    char *args[] = {"/bin/bash", script, NULL};
    execv("/bin/bash", args);
    log_line("execv(/bin/bash) failed");
    return 1;
}
