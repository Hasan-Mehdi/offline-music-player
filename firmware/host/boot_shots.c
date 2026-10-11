/* Render the Coda OS boot animation (firmware/ui/boot.c, the code the device runs) to PNG
 * frames at 30 fps: the mock to look at before it goes on the H2.
 *   boot_shots <out_dir> [scale]
 */
#include <stdio.h>
#include <stdlib.h>

#include "boot.h"
#include "fx.h"
#include "gfx.h"
#include "plat_host.h"

static uint16_t fb[LCD_W * LCD_H];

int main(int argc, char **argv)
{
    if (argc < 2) { printf("usage: boot_shots <out_dir> [scale]\n"); return 2; }
    int scale = argc > 2 ? atoi(argv[2]) : 2;
    gfx g;
    g_init(&g, fb, LCD_W, LCD_H, LCD_W);
    fx_init();
    int n = 0;
    for (uint32_t t = 0; t <= BOOT_MS + 200; t += 33, n++) {
        char p[600];
        boot_draw(&g, t);
        snprintf(p, sizeof p, "%s/boot_%03d.png", argv[1], n);
        plat_host_png(p, fb, LCD_W, LCD_H, scale);
    }
    printf("%d frames -> %s\n", n, argv[1]);
    return 0;
}
