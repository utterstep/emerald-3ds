// Headless mGBA driver for screen checks. Reads commands from stdin:
//   run N                 run N frames, no keys
//   hold KEYS N           hold KEYS (e.g. A, A+B, UP, START) for N frames
//   tap KEYS [N]          hold KEYS 2 frames, then release for N frames (default 20)
//   shot FILE.png         write the current frame
//   savestate FILE / loadstate FILE
//   sav FILE              load a battery save (before the first frame); the game
//                         writes to a copy in memory, FILE itself is never changed
//   savout FILE           write the battery save as it is now (after an in-game save)
//   rtc SECONDS           the cartridge clock starts at this Unix time and runs with
//                         the emulated frames (default 1767268800, 2026-01-01 12:00 UTC),
//                         so runs are repeatable; give it before the first frame
//   w8|w16|w32 ADDR VAL   bus write;  r8|r16|r32 ADDR  bus read (printed)
//   until ADDR VAL MASK N run until (r32(ADDR) & MASK) == VAL, at most N frames
//   untilnot ADDR VAL MASK N  run until (r32(ADDR) & MASK) != VAL, at most N frames
//   dump ADDR LEN FILE    write LEN bytes of the bus from ADDR to FILE
//   wfile ADDR FILE       write FILE's bytes to the bus at ADDR
//   echo TEXT             print TEXT (for logs)
//   regs                  print the CPU's registers r0-r15
//   tapuntil KEYS N ADDR VAL MASK [MAX]  tap KEYS every N frames until
//                         (r32(ADDR) & MASK) == VAL, at most MAX frames (default 6000)
// Numbers: addresses, values, masks and lengths are hex; frame counts decimal.
// The library's build flags first: struct mCore has fields under USE_DEBUGGERS.
#include <mgba/flags.h>
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/gba/gba.h>
#include <mgba-util/vfs.h>
#include <png.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static color_t *gBuf;
static unsigned gW, gH;

static void silent(struct mLogger *l, int c, enum mLogLevel lv, const char *f, va_list a) {}

static uint32_t keys_of(const char *s) {
    static const char *names[] = {"A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L"};
    uint32_t k = 0;
    char tmp[128];
    snprintf(tmp, sizeof tmp, "%s", s);
    for (char *t = strtok(tmp, "+"); t; t = strtok(NULL, "+"))
        for (int i = 0; i < 10; i++)
            if (!strcmp(t, names[i])) k |= 1u << i;
    return k;
}

static void shot(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return; }
    png_structp p = png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    png_infop info = png_create_info_struct(p);
    png_init_io(p, f);
    png_set_IHDR(p, info, gW, gH, 8, PNG_COLOR_TYPE_RGB, PNG_INTERLACE_NONE, PNG_COMPRESSION_TYPE_DEFAULT, PNG_FILTER_TYPE_DEFAULT);
    png_write_info(p, info);
    unsigned char *row = malloc(gW * 3);
    for (unsigned y = 0; y < gH; y++) {
        for (unsigned x = 0; x < gW; x++) {
            uint32_t c = gBuf[y * gW + x];
            row[x * 3] = c & 0xFF; row[x * 3 + 1] = (c >> 8) & 0xFF; row[x * 3 + 2] = (c >> 16) & 0xFF;
        }
        png_write_row(p, row);
    }
    png_write_end(p, NULL);
    png_destroy_write_struct(&p, &info);
    free(row);
    fclose(f);
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: mgbarig ROM < script\n"); return 2; }
    static struct mLogger logger = {.log = silent};
    mLogSetDefaultLogger(&logger);
    struct mCore *core = mCoreFind(argv[1]);
    if (!core || !core->init(core)) { fprintf(stderr, "no core\n"); return 1; }
    mCoreInitConfig(core, NULL);
    core->desiredVideoDimensions(core, &gW, &gH);
    gBuf = calloc(gW * gH, sizeof(color_t));
    core->setVideoBuffer(core, gBuf, gW);
    if (!mCoreLoadFile(core, argv[1])) { fprintf(stderr, "cannot load %s\n", argv[1]); return 1; }
    core->rtc.override = RTC_FAKE_EPOCH;
    core->rtc.value = 1767268800LL * 1000;
    char line[512], cmd[32], a[256];
    unsigned long n, v, m, n2;
    int started = 0;
    while (fgets(line, sizeof line, stdin)) {
        if (line[0] == '#' || sscanf(line, "%31s", cmd) != 1) continue;
        // Arguments after the command word.
        const char *arg = line + strspn(line, " \t") + strlen(cmd);
        if (!strcmp(cmd, "sav") && sscanf(arg, "%255s", a) == 1) {
            // A copy in memory: a test save stays as it is however the game saves.
            FILE *f = fopen(a, "rb");
            static unsigned char sav[0x20000];
            size_t sz = f ? fread(sav, 1, sizeof sav, f) : 0;
            if (f) fclose(f);
            struct VFile *vf = sz ? VFileMemChunk(sav, sz) : NULL;
            if (!vf || !core->loadSave(core, vf)) fprintf(stderr, "sav %s failed\n", a);
            continue;
        }
        if (!strcmp(cmd, "rtc") && sscanf(arg, "%lu", &n) == 1) {
            core->rtc.override = RTC_FAKE_EPOCH;
            core->rtc.value = (int64_t)n * 1000;
            continue;
        }
        if (!started) { core->reset(core); started = 1; }
        if (!strcmp(cmd, "run") && sscanf(arg, "%lu", &n) == 1) {
            core->setKeys(core, 0);
            while (n--) core->runFrame(core);
        } else if (!strcmp(cmd, "hold") && sscanf(arg, "%255s %lu", a, &n) == 2) {
            core->setKeys(core, keys_of(a));
            while (n--) core->runFrame(core);
            core->setKeys(core, 0);
        } else if (!strcmp(cmd, "tap") && sscanf(arg, "%255s", a) == 1) {
            if (sscanf(arg, "%255s %lu", a, &n) < 2) n = 20;
            core->setKeys(core, keys_of(a));
            core->runFrame(core); core->runFrame(core);
            core->setKeys(core, 0);
            while (n--) core->runFrame(core);
        } else if (!strcmp(cmd, "shot") && sscanf(arg, "%255s", a) == 1) {
            shot(a);
        } else if (!strcmp(cmd, "savout") && sscanf(arg, "%255s", a) == 1) {
            void *sram = NULL;
            size_t sz = core->savedataClone(core, &sram);
            FILE *f = fopen(a, "wb");
            if (!f || !sz || fwrite(sram, 1, sz, f) != sz) fprintf(stderr, "savout %s failed\n", a);
            else printf("savout %s: %zu bytes\n", a, sz);
            if (f) fclose(f);
            free(sram);
        } else if (!strcmp(cmd, "savestate") && sscanf(arg, "%255s", a) == 1) {
            size_t sz = core->stateSize(core);
            void *st = malloc(sz);
            core->saveState(core, st);
            FILE *f = fopen(a, "wb"); fwrite(st, 1, sz, f); fclose(f); free(st);
        } else if (!strcmp(cmd, "loadstate") && sscanf(arg, "%255s", a) == 1) {
            size_t sz = core->stateSize(core);
            void *st = malloc(sz);
            FILE *f = fopen(a, "rb");
            if (!f || fread(st, 1, sz, f) != sz || !core->loadState(core, st)) fprintf(stderr, "loadstate %s failed\n", a);
            if (f) fclose(f);
            free(st);
        } else if (!strcmp(cmd, "w8") && sscanf(arg, "%lx %lx", &n, &v) == 2) {
            core->busWrite8(core, n, v);
        } else if (!strcmp(cmd, "w16") && sscanf(arg, "%lx %lx", &n, &v) == 2) {
            core->busWrite16(core, n, v);
        } else if (!strcmp(cmd, "w32") && sscanf(arg, "%lx %lx", &n, &v) == 2) {
            core->busWrite32(core, n, v);
        } else if (!strcmp(cmd, "r8") && sscanf(arg, "%lx", &n) == 1) {
            printf("%08lx: %02x\n", n, core->busRead8(core, n));
        } else if (!strcmp(cmd, "r16") && sscanf(arg, "%lx", &n) == 1) {
            printf("%08lx: %04x\n", n, core->busRead16(core, n));
        } else if (!strcmp(cmd, "r32") && sscanf(arg, "%lx", &n) == 1) {
            printf("%08lx: %08x\n", n, core->busRead32(core, n));
        } else if (!strcmp(cmd, "dump") && sscanf(arg, "%lx %lx %255s", &n, &v, a) == 3) {
            FILE *f = fopen(a, "wb");
            for (unsigned long i = 0; f && i < v; i++) fputc(core->busRead8(core, n + i), f);
            if (f) fclose(f); else perror(a);
        } else if (!strcmp(cmd, "wfile") && sscanf(arg, "%lx %255s", &n, a) == 2) {
            FILE *f = fopen(a, "rb");
            int c;
            if (!f) perror(a);
            for (unsigned long i = 0; f && (c = fgetc(f)) != EOF; i++) core->busWrite8(core, n + i, c);
            if (f) fclose(f);
        } else if ((!strcmp(cmd, "until") || !strcmp(cmd, "untilnot")) && sscanf(arg, "%lx %lx %lx", &n, &v, &m) == 3) {
            unsigned long addr = n, want = v, mask = m, max = 600;
            int neg = !strcmp(cmd, "untilnot");
            sscanf(arg, "%lx %lx %lx %lu", &addr, &want, &mask, &max);
            core->setKeys(core, 0);
            unsigned long i = 0;
            while (i < max && (((core->busRead32(core, addr) & mask) == want) == neg)) { core->runFrame(core); i++; }
            printf("%s %08lx: %lu frames%s\n", cmd, addr, i, i == max ? " (timeout)" : "");
        } else if (!strcmp(cmd, "regs")) {
            // The CPU's registers (where a hang loops: sample it a few times).
            struct ARMCore *cpu = ((struct GBA *)core->board)->cpu;
            for (int i = 0; i < 16; i++) printf("r%d=%08x%s", i, (unsigned)cpu->gprs[i], i == 15 ? "\n" : " ");
        } else if (!strcmp(cmd, "tapuntil") && sscanf(arg, "%255s %lu %lx %lx %lx", a, &n, &v, &m, &n2) == 5) {
            // tap KEYS every N frames until (r32(ADDR) & MASK) == VAL (checked every frame)
            unsigned long addr = v, want = m, mask = n2, max = 6000, i = 0;
            sscanf(arg, "%*s %*u %*x %*x %*x %lu", &max);
            uint32_t k = keys_of(a);
            while (i < max && (core->busRead32(core, addr) & mask) != want) {
                core->setKeys(core, (i % n) < 2 ? k : 0);
                core->runFrame(core);
                i++;
            }
            core->setKeys(core, 0);
            printf("tapuntil %08lx: %lu frames%s\n", addr, i, i == max ? " (timeout)" : "");
        } else if (!strcmp(cmd, "echo")) {
            fputs(arg + strspn(arg, " \t"), stdout);
        } else {
            fprintf(stderr, "?? %s", line);
        }
        fflush(stdout);
    }
    core->deinit(core);
    return 0;
}
